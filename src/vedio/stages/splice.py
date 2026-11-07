# -*- coding: utf-8 -*-
"""vedio.stages.splice —— 切分长片并拼上片头片尾

一条长片 → N 段 → 每段「片头 + 正片 + 片尾」→ `成片/`。

三个刻意的设计：

1. **切分用 `-c copy`**（不重编码）。旧实现也是这样，是对的。
2. **拼接优先用 concat demuxer + `-c copy`**；只有参数对不上时才回退重编码。
   这一条是最大的性能杠杆：重编码 20 段要 15~25 分钟，copy 只要几十秒。
   实测前提是片头/片尾与正片同分辨率/帧率/编码 —— 找不到共同参数就自动回退。
3. **拼接前必须校验片头片尾**（`AGENTS.md` §5.2）。缺了就停，不许拿别的文件顶替。

中间的分段文件拼完立刻删 —— 19 段 1080p 临时文件能吃掉几个 G。
"""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .. import context, media
from ..context import Collection, Project
from ..events import DONE, FAIL, SKIP, EventLog


class SpliceError(Exception):
    def __init__(self, code: str, message: str, hint: str = "", **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        d = {"error": self.code, "message": self.message, **self.detail}
        if self.hint:
            d["hint"] = self.hint
        return d


#: 跑 ffmpeg 的函数签名： (args: list[str], timeout: float) -> (returncode, stderr)
Runner = Callable[[Sequence[str], float], tuple[int, str]]


@dataclass
class Segment:
    """一段正片。

    ⚠ `temp` 是切出来的中间分段，`output` 是最终成片 —— **必须是两个路径**。
    早期版本把它们写成同一个，concat 会把切好的段覆盖掉。
    """

    index: int                 # 1 起
    start: float
    duration: float
    output: Path               # 最终成片
    temp: Path                 # 中间分段（拼完删除）

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "start": round(self.start, 2),
                "duration": round(self.duration, 2), "output": self.output.name}


@dataclass
class SpliceResult:
    collection: str
    status: str                       # done / skip / fail
    segments: int = 0
    outputs: list[str] = field(default_factory=list)
    mode: str = ""                    # copy / encode
    seconds: float = 0.0
    error: Optional[str] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skip")

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection, "status": self.status,
            "segments": self.segments, "outputs": self.outputs,
            "mode": self.mode, "seconds": round(self.seconds, 1),
            "error": self.error, "message": self.message,
        }


# ─────────────────────────── 计划（纯函数） ───────────────────────────

def plan_segments(total: float, body: float, count: int,
                  output_dir: Path, stem: str,
                  tolerance: float = 3.0,
                  temp_dir: Optional[Path] = None,
                  min_tail_ratio: float = 0.5) -> list[Segment]:
    """把一条长片按 `body` 切成若干段。

    两条边界规则：

    1. 剩余量不足一段（`<= body + tolerance`）→ 全部吃进这一段
    2. **尾巴碎段并进上一段**：切完如果最后一段短于 `body * min_tail_ratio`，
       合并到前一段 —— 否则会切出「第 20 集只有 5 秒」这种垃圾输出
    """
    if body <= 0:
        raise SpliceError("bad_body", f"每集正文时长必须 > 0，现在是 {body}")
    if total <= 0:
        raise SpliceError("bad_video", "长片时长为 0，检查文件是否损坏")

    temp_root = Path(temp_dir) if temp_dir else Path(output_dir) / "_segments"
    segments: list[Segment] = []
    start = 0.0
    index = 1
    while start < total - tolerance:
        remaining = total - start
        duration = body if remaining > body + tolerance else remaining
        segments.append(Segment(
            index=index,
            start=round(start, 3),
            duration=round(duration, 3),
            output=Path(output_dir) / f"{stem}-{index:02d}.mp4",
            temp=temp_root / f"{stem}-{index:02d}.seg.mp4",
        ))
        start += duration
        index += 1

    # 尾巴太短 → 并进上一段
    if len(segments) >= 2:
        tail = segments[-1]
        if tail.duration < body * min_tail_ratio:
            prev = segments[-2]
            prev.duration = round(prev.duration + tail.duration, 3)
            segments.pop()
    return segments


def expected_mismatch(segments: Sequence[Segment], count: int) -> Optional[str]:
    """段数与预期集数不一致时返回人话提示"""
    if count <= 0 or len(segments) == count:
        return None
    if len(segments) < count:
        return f"只切出 {len(segments)} 段，预期 {count} 集 —— 素材可能不够长"
    return f"切出 {len(segments)} 段，比预期 {count} 集多 —— 素材超长，或每集时长设小了"


# ─────────────────────────── ffmpeg 调用 ───────────────────────────

def _default_runner() -> Runner:
    def runner(args: Sequence[str], timeout: float) -> tuple[int, str]:
        try:
            result = subprocess.run(
                list(args), capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)
        return result.returncode, (result.stderr or "")
    return runner


def cut_copy(runner: Runner, ffmpeg: str, source: Path, segment: Segment,
             timeout: float = 1800) -> None:
    """按时间切一段，`-c copy` 不重编码。写到 `segment.temp`。"""
    segment.temp.parent.mkdir(parents=True, exist_ok=True)
    args = [
        ffmpeg, "-y", "-ss", f"{segment.start:.3f}", "-i", str(source),
        "-t", f"{segment.duration:.3f}", "-c", "copy",
        "-avoid_negative_ts", "make_zero", str(segment.temp),
    ]
    code, err = runner(args, timeout)
    if code != 0 or not segment.temp.exists():
        raise SpliceError("cut_failed",
                          f"第 {segment.index} 段切分失败（ffmpeg 退出码 {code}）",
                          hint=(err or "").strip().splitlines()[-1][:200] if err else "")


def _concat_list_file(parts: Sequence[Path], path: Path) -> None:
    """写 concat demuxer 的清单。**必须 UTF-8 无 BOM** —— 带 BOM 时 ffmpeg 会读不出来。"""
    lines = ["file '" + str(p).replace("'", "'\\''") + "'" for p in parts]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def concat_copy(runner: Runner, ffmpeg: str, parts: Sequence[Path], out: Path,
                work_dir: Path, timeout: float = 1800) -> bool:
    """concat demuxer + `-c copy`。参数不一致时 ffmpeg 会失败，返回 False。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    list_file = work_dir / "_concat_list.txt"
    _concat_list_file(parts, list_file)
    args = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", "-movflags", "+faststart", str(out),
    ]
    code, _ = runner(args, timeout)
    return code == 0 and out.is_file() and out.stat().st_size > 0


def concat_encode(runner: Runner, ffmpeg: str, parts: Sequence[Path], out: Path,
                  encode: dict, timeout: float = 3600) -> None:
    """回退路径：filter_complex 拼接 + 重编码。

    只有 copy 失败才走这里。慢 20 倍以上，但能兜住"片头片尾参数不一致"。
    """
    if len(parts) != 3:
        raise SpliceError("bad_concat", f"回退拼接收 3 个输入，收到 {len(parts)} 个")
    filt = "".join(f"[{i}:v]setsar=1[v{i}];[{i}:a]aresample=async=1:first_pts=0[a{i}];"
                   for i in range(3))
    filt += "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]"
    args = [ffmpeg, "-y"]
    for p in parts:
        args += ["-i", str(p)]
    args += [
        "-filter_complex", filt,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", str(encode.get("encoder", "libx264")),
        "-crf", str(encode.get("quality", 23)),
        "-preset", str(encode.get("preset", "medium")),
        "-pix_fmt", str(encode.get("pix_fmt", "yuv420p")),
        "-c:a", str(encode.get("audio_codec", "aac")),
        "-b:a", str(encode.get("audio_bitrate", "128k")),
        "-movflags", "+faststart", str(out),
    ]
    code, err = runner(args, timeout)
    if code != 0 or not out.is_file():
        raise SpliceError("concat_failed", "重编码拼接失败",
                          hint=(err or "").strip().splitlines()[-1][:200] if err else "")


# ─────────────────────────── 单个合集 ───────────────────────────

def find_long_video(project: Project, collection: Collection) -> Optional[Path]:
    """`剪辑/` 里那条长片：最长的视频就是它"""
    best: Optional[Path] = None
    best_len = 0.0
    for p in media.list_videos(collection.editing):
        d = media.probe_duration(project.ffprobe, p)
        if d > best_len:
            best, best_len = p, d
    return best


def splice_collection(project: Project, collection: Collection, *,
                      log: Optional[EventLog] = None,
                      runner: Optional[Runner] = None,
                      force: bool = False,
                      keep_segments: bool = False) -> SpliceResult:
    """切分 + 拼片头片尾，产出 `成片/`"""
    import time

    name = collection.name

    # ── 1. 前置：片头片尾必须齐（AGENTS.md §5.2） ──
    tpl = project.validate_templates(name)
    if not tpl["ok"]:
        first = tpl["problems"][0]["message"] if tpl["problems"] else "片头片尾未登记"
        if log is not None:
            log.emit("splice", FAIL, name, error="template_missing", message=first)
        return SpliceResult(name, "fail", error="template_missing", message=first)
    intro, outro = Path(tpl["intro"]), Path(tpl["outro"])

    # ── 2. 长片 ──
    long_video = find_long_video(project, collection)
    if long_video is None:
        if log is not None:
            log.emit("splice", FAIL, name, error="no_long_video",
                     message=f"{collection.editing} 里没有长片")
        return SpliceResult(name, "fail", error="no_long_video",
                            message=f"{collection.editing} 里没有长片")

    total = media.probe_duration(project.ffprobe, long_video)
    body = float(project.episode_body)
    count = int(project.episode_count)
    tolerance = float(project.tolerance)

    try:
        segments = plan_segments(total, body, count, collection.final,
                                 stem=name, tolerance=tolerance)
    except SpliceError as exc:
        return SpliceResult(name, "fail", error=exc.code, message=exc.message)

    if not segments:
        return SpliceResult(name, "fail", error="no_segment", message="切不出任何段")

    # 已有成片且数量够 → 跳过
    existing = media.list_videos(collection.final)
    if not force and len(existing) >= len(segments):
        if log is not None:
            log.emit("splice", SKIP, name, reason="already_done",
                     finals=len(existing), expected=len(segments))
        return SpliceResult(name, "skip", segments=len(segments),
                            outputs=[p.name for p in existing],
                            message=f"成片/ 里已有 {len(existing)} 个，跳过")

    runner = runner or _default_runner()
    ffmpeg = project.ffmpeg
    encode_cfg = dict(project.rule("encode", {}) or {})
    encoder_priority = encode_cfg.get("encoder_priority") or ["libx264"]
    encode_cfg["encoder"] = encoder_priority[0]

    started = time.time()
    if log is not None:
        log.emit("splice", "start", name, long_video=long_video.name,
                 video_seconds=round(total, 1), segments=len(segments),
                 body=body, expected=count)

    outputs: list[str] = []
    modes: list[str] = []
    warnings: list[str] = []
    mismatch = expected_mismatch(segments, count)
    if mismatch:
        warnings.append(mismatch)

    try:
        for seg in segments:
            seg.output.parent.mkdir(parents=True, exist_ok=True)
            cut_copy(runner, ffmpeg, long_video, seg)
            parts = [intro, seg.temp, outro]
            used_copy = concat_copy(runner, ffmpeg, parts, seg.output, seg.output.parent)
            mode = "copy"
            if not used_copy:
                # 参数对不上 → 回退重编码（先清掉半成品）
                if seg.output.exists():
                    seg.output.unlink()
                concat_encode(runner, ffmpeg, parts, seg.output, encode_cfg)
                mode = "encode"
            modes.append(mode)
            outputs.append(seg.output.name)
            if not keep_segments:
                _cleanup_temp(seg.temp)
    except SpliceError as exc:
        # ffmpeg 的报错尾行在 hint 里 —— 不记下来就只剩"第 7 段切分失败"，
        # 等于没线索。这一行往往是唯一能看出真正原因的东西。
        if log is not None:
            log.emit("splice", FAIL, name, error=exc.code, message=exc.message,
                     ffmpeg_hint=exc.hint or None, done=len(outputs))
        return SpliceResult(name, "fail", error=exc.code, message=exc.message,
                            outputs=outputs)

    elapsed = time.time() - started
    mode = "copy" if modes and all(m == "copy" for m in modes) else "encode"
    if log is not None:
        log.emit("splice", DONE, name, seconds=round(elapsed, 1), mode=mode,
                 outputs=len(outputs), warnings=warnings)
    return SpliceResult(name, "done", segments=len(segments), outputs=outputs,
                        mode=mode, seconds=elapsed,
                        message=f"{len(outputs)} 个成片（{mode}，{media.hhmmss(elapsed)}）")


def _cleanup_temp(path: Path) -> None:
    """删中间分段文件。删不掉不算错（磁盘权限问题不该让整批失败）。"""
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


# ─────────────────────────── 批量 ───────────────────────────

def splice_batch(project: Project, collections: Optional[list[str]] = None, *,
                 log: Optional[EventLog] = None, runner: Optional[Runner] = None,
                 force: bool = False) -> list[SpliceResult]:
    """批量拼接。一个合集失败不中断整批。"""
    if log is None:
        log = EventLog(project.log_dir)
    runner = runner or _default_runner()
    results: list[SpliceResult] = []
    for c in project.resolve_collections(collections):
        results.append(splice_collection(project, c, log=log, runner=runner, force=force))
    return results
