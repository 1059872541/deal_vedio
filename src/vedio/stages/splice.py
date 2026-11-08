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
from .. import progress
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
    #: 失败时删掉的半成品（免得占着空间还被当成成品）
    removed: list[str] = field(default_factory=list)
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
            "removed": self.removed,
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
                  encode: dict, timeout: float = 3600,
                  fps: Optional[float] = None) -> None:
    """回退路径：filter_complex 拼接 + 重编码。

    只有 copy 走不通才走这里。慢 20 倍以上，但能兜住"片头片尾参数不一致" ——
    实测就是这种情况：正片 30fps、片头片尾 25fps，`-c copy` 拼出来时间戳作废
    （视频显示 20 小时）。这里统一 `fps` 再拼，才是对的。
    """
    if len(parts) != 3:
        raise SpliceError("bad_concat", f"回退拼接收 3 个输入，收到 {len(parts)} 个")
    fps_part = f",fps={fps:g}" if fps else ""
    filt = "".join(
        f"[{i}:v]setsar=1{fps_part},format=yuv420p[v{i}];"
        f"[{i}:a]aresample=async=1:first_pts=0[a{i}];"
        for i in range(3)
    )
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


def duration_matches(path: Path, ffprobe: str, expected: float,
                     tolerance: float = 3.0) -> bool:
    """产物时长和预期对得上吗？

    **exit code 0 不等于产物正确** —— 实测 `-c copy` 拼 25fps + 30fps 时
    ffmpeg 正常退出，但视频轨时间戳被按 timebase 比例放大 600 倍，
    显示 20 小时。所以拼完必须验一次时长，不对就回退重编码。
    """
    actual = media.probe_duration(ffprobe, path)
    if actual <= 0:
        return False
    return abs(actual - expected) <= max(tolerance, expected * 0.03)


def normalize_template(runner: Runner, ffmpeg: str, path: Path, fps: float,
                       cache_dir: Path, encode: dict,
                       timeout: float = 1800) -> Optional[Path]:
    """把片头/片尾转成和正片一致的帧率，缓存起来供 `-c copy` 使用。

    **为什么值得做**：`-c copy` 要求各段时间基一致。正片 30fps、片头片尾 25fps
    时只能重编码 —— 实测 2 分钟的成片要 80 秒，21 分钟的素材要 29 分钟。
    而 `-c copy` 是搬字节，同样的活几秒钟。

    转换只做一次（按「文件修改时间 + 目标帧率」缓存），之后每个合集都走 copy。

    Returns:
        缓存文件路径；失败返回 None（调用方退回重编码）
    """
    if not fps:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None

    key = f"{path.stem}_{int(stat.st_mtime)}_{fps:g}fps.mp4"
    out = cache_dir / key
    if out.is_file() and out.stat().st_size > 0:
        return out

    cache_dir.mkdir(parents=True, exist_ok=True)
    encoder = str(encode.get("encoder", "libx264"))
    args = [ffmpeg, "-y", "-i", str(path),
            "-vf", f"fps={fps:g},setsar=1,format=yuv420p",
            "-c:v", encoder]
    # qsv/nvenc 用 -global_quality，libx264 用 -crf
    if encoder.endswith(("_qsv", "_nvenc", "_amf")):
        args += ["-global_quality", str(encode.get("quality", 23))]
    else:
        args += ["-crf", str(encode.get("quality", 23)),
                 "-preset", str(encode.get("preset", "medium"))]
    args += ["-c:a", str(encode.get("audio_codec", "aac")),
             "-b:a", str(encode.get("audio_bitrate", "128k")),
             "-movflags", "+faststart", str(out)]

    code, _err = runner(args, timeout)
    if code != 0 or not out.is_file() or out.stat().st_size == 0:
        return None
    return out


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

    # ── 1. 前置：片头片尾必须齐（docs/状态与校验.md） ──
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
        progress.record(project, name, "拼接")
        return SpliceResult(name, "skip", segments=len(segments),
                            outputs=[p.name for p in existing],
                            message=f"成片/ 里已有 {len(existing)} 个，跳过")

    runner = runner or _default_runner()
    ffmpeg = project.ffmpeg
    encode_cfg = dict(project.rule("encode", {}) or {})
    encoder_priority = encode_cfg.get("encoder_priority") or ["libx264"]
    encode_cfg["encoder"] = encoder_priority[0]

    # ── 空间预检：动手前先确认写得下 ──
    # 实测踩过：D: 剩 0 字节，切到第 5 段才失败，报「ffmpeg 退出码 4294967268」，
    # 没人看得懂，还白写了 0.5 GB 半成品。宁可一次算清楚。
    needed = estimate_space(long_video, segments, intro, outro)
    enough, free = check_space(collection.final, needed)
    if not enough:
        msg = (f"磁盘空间不够：拼接需要约 {_gb(needed)}，目标盘只剩 {_gb(free)}。"
               f"先腾出 {_gb(needed - free)} 再跑。")
        if log is not None:
            log.emit("splice", FAIL, name, error="disk_full", message=msg,
                     needed=needed, free=free)
        return SpliceResult(name, "fail", error="disk_full", message=msg)

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

    # ── 帧率一致性：决定能不能走 copy ──
    # `-c copy` 要求各段时间基一致。实测：正片 30fps(time_base 1/15360)、
    # 片头片尾 25fps(1/25) —— 拼出来视频时间戳被放大 600 倍，2 分钟变 20 小时，
    # **而 ffmpeg 退出码是 0**。所以这里先比对，不一致就直接走重编码。
    source_fps = media.probe_fps(project.ffprobe, long_video)
    tpl_fps = {
        media.probe_fps(project.ffprobe, intro),
        media.probe_fps(project.ffprobe, outro),
    }
    fps_mismatch = bool(source_fps) and any(f and abs(f - source_fps) > 0.01 for f in tpl_fps)

    # 帧率不一致时，先把片头片尾**一次性**转成同帧率缓存起来，
    # 之后就还能走 copy —— 否则每集都要重编码，慢 14 倍（实测 80 秒/集）。
    intro_use, outro_use = intro, outro
    if fps_mismatch:
        cache_dir = project.batch_dir / "log" / "cache" / "templates"
        n_intro = normalize_template(runner, ffmpeg, intro, source_fps, cache_dir, encode_cfg)
        n_outro = normalize_template(runner, ffmpeg, outro, source_fps, cache_dir, encode_cfg)
        if n_intro is not None and n_outro is not None:
            intro_use, outro_use = n_intro, n_outro
            fps_mismatch = False
            fps_text = "、".join(f"{f:g}" for f in sorted(tpl_fps) if f)
            warnings.append(f"片头片尾 {fps_text}fps 与正片 {source_fps:g}fps 不一致，"
                            f"已缓存转换版本，本次走 copy")
            print(f"  片头片尾已转为 {source_fps:g}fps（缓存 {cache_dir}），走 copy 拼接")
    if fps_mismatch:
        fps_text = "、".join(f"{f:g}" for f in sorted(tpl_fps) if f)
        warnings.append(f"帧率不一致（正片 {source_fps:g}fps，片头片尾 {fps_text}fps）"
                        f"→ 走重编码，否则时间戳会坏")

    try:
        for seg in segments:
            seg.output.parent.mkdir(parents=True, exist_ok=True)
            cut_copy(runner, ffmpeg, long_video, seg)
            parts = [intro_use, seg.temp, outro_use]
            expected = (media.probe_duration(project.ffprobe, intro_use)
                        + seg.duration
                        + media.probe_duration(project.ffprobe, outro_use))
            used_copy = False
            if not fps_mismatch:
                used_copy = concat_copy(runner, ffmpeg, parts, seg.output, seg.output.parent)
                # copy 成功不等于产物正确 —— 时长对不上就当作失败
                if used_copy and not duration_matches(seg.output, project.ffprobe, expected):
                    warnings.append(f"第 {seg.index} 段 copy 拼接时长不符（预期约 "
                                    f"{expected:.0f} 秒），已改用重编码")
                    used_copy = False
                    try:
                        seg.output.unlink()
                    except OSError:
                        pass
            mode = "copy"
            if not used_copy:
                concat_encode(runner, ffmpeg, parts, seg.output, encode_cfg,
                              fps=source_fps or None)
                mode = "encode"
            modes.append(mode)
            outputs.append(seg.output.name)
            if not keep_segments:
                _cleanup_temp(seg.temp)
    except SpliceError as exc:
        # ffmpeg 的报错尾行在 hint 里 —— 不记下来就只剩"第 7 段切分失败"，
        # 等于没线索。这一行往往是唯一能看出真正原因的东西。
        hint = exc.hint or ""
        if not hint and exc.detail.get("returncode"):
            hint = _disk_full_hint(int(exc.detail["returncode"]), "")
        if log is not None:
            log.emit("splice", FAIL, name, error=exc.code, message=exc.message,
                     ffmpeg_hint=hint or None, done=len(outputs))
        # 清掉这一轮写的半成品，别把磁盘占着还让人以为有货
        removed = _discard_partial(collection.final, outputs)
        message = exc.message
        if hint:
            message = f"{message}（{hint}）"
        return SpliceResult(name, "fail", error=exc.code, message=message,
                            outputs=outputs, removed=removed)

    elapsed = time.time() - started
    mode = "copy" if modes and all(m == "copy" for m in modes) else "encode"
    if log is not None:
        log.emit("splice", DONE, name, seconds=round(elapsed, 1), mode=mode,
                 outputs=len(outputs), warnings=warnings)
    progress.record(project, name, "拼接")
    return SpliceResult(name, "done", segments=len(segments), outputs=outputs,
                        mode=mode, seconds=elapsed,
                        message=f"{len(outputs)} 个成片（{mode}，{media.hhmmss(elapsed)}）")


def _discard_partial(final_dir: Path, outputs: Sequence[str]) -> list[str]:
    """删掉这一轮写到一半的成片和切片目录。返回删掉的文件名。

    只在**失败**时调用：这些文件是本轮刚写的、不完整的，留着既占空间
    又容易被误当成品（用户会以为这一集已经拼好了）。
    """
    removed: list[str] = []
    for name in outputs:
        p = Path(final_dir) / name
        try:
            if p.is_file():
                p.unlink()
                removed.append(name)
        except OSError:
            pass
    seg_dir = Path(final_dir) / "_segments"
    try:
        if seg_dir.is_dir():
            shutil.rmtree(seg_dir, ignore_errors=True)
    except OSError:
        pass
    return removed


def _cleanup_temp(path: Path) -> None:
    """删中间分段文件。删不掉不算错（磁盘权限问题不该让整批失败）。"""
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


# ─────────────────────────── 空间预检 ───────────────────────────

#: 预估之外再留的余量（成片索引、文件系统碎片、剪映临时文件）
SPACE_HEADROOM = 1.15


def estimate_space(source: Path, segments: Sequence[Segment],
                  intro: Path, outro: Path) -> int:
    """估算这次拼接要写多少字节。

    - **成片**：每集 = 片头 + 该段 + 片尾，总量 ≈ 源大小 + 集数 ×（片头 + 片尾）
    - **切片**：逐段生成、拼完一集立刻删（`keep_segments=False`），
      所以同时只多占**最大那一段**，不是源大小的又一份

    早期版本按「源 × 2」估，把同时最多 1 段的临时文件当成整体多一份，
    对 2 小时素材会高估近一倍 —— 高估会让本来跑得动的拼接被拒。
    """
    try:
        source_size = source.stat().st_size
    except OSError:
        source_size = 0
    try:
        tpl_size = intro.stat().st_size + outro.stat().st_size
    except OSError:
        tpl_size = 0
    largest = max((s.duration for s in segments), default=0.0)
    total_dur = max(sum(s.duration for s in segments), 1.0)
    # 最大那一段占源文件的比例
    one_segment = int(source_size * (largest / total_dur)) if total_dur else 0
    return int((source_size + tpl_size * len(segments) + one_segment) * SPACE_HEADROOM)


def check_space(target_dir: Path, needed: int) -> tuple[bool, int]:
    """检查目标盘剩余空间够不够。

    Returns:
        (够不够, 剩余字节)

    为什么要预检：实测踩过 —— D: 盘剩 0 字节，`splice` 切到第 5 段才失败，
    报的是「ffmpeg 退出码 4294967268」（= -28 = ENOSPC），没人看得懂；
    而且已经白写了 0.5 GB 半成品。
    """
    import shutil as _shutil

    probe = Path(target_dir)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return _shutil.disk_usage(probe).free >= needed, _shutil.disk_usage(probe).free
    except OSError:
        return True, 0          # 查不到就别拦着，别因为统计失败把正常流程卡死


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB"


def _disk_full_hint(returncode: int, stderr: str) -> str:
    """ffmpeg 非零退出时给一句人话 —— 光甩退出码等于没线索。"""
    # Windows 上 ffmpeg 把 errno 塞进退出码：4294967268 == -28 == ENOSPC
    if returncode in (-28, 4294967268) or "No space left" in stderr:
        return "磁盘空间不足（ffmpeg ENOSPC）—— 先腾出空间再跑"
    return stderr.strip().splitlines()[-1] if stderr.strip() else ""


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
