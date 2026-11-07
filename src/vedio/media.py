# -*- coding: utf-8 -*-
"""vedio.media —— 视频时长探测

全项目只有这一处调用 ffprobe。旧代码在 `util/ffmpeg_utils.py` 和
`auto_splice_mp4.py` 里各写了一份，还都把 ffmpeg 路径写死在模块顶部。
这里一律由调用方传入命令（来自 `conf/本机.yaml` 的 `tool.ffprobe`）。

探测失败返回 ``0.0`` 而不是抛异常：`status` 要能在"文件坏了"的情况下继续画表，
而不是整个崩掉。需要严格判定的地方（如拼接前校验）自己看返回值是否为 0。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Sequence

#: 认作视频的扩展名
VIDEO_SUFFIXES = frozenset({".mp4", ".mkv", ".mov", ".flv", ".avi", ".ts", ".m4v", ".wmv", ".webm"})


def is_video(path: Path) -> bool:
    """按扩展名判断（不看文件头，够用且快）"""
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def list_videos(directory: Path) -> list[Path]:
    """目录下所有视频（不含子目录），按名字排序"""
    d = Path(directory)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and is_video(p))


def probe_duration(ffprobe: str, path: Path, timeout: float = 60.0) -> float:
    """读视频时长（秒）。失败返回 0.0。

    Args:
        ffprobe: 命令名或绝对路径（`ffprobe` / `D:/softwares/ffmpeg/bin/ffprobe.exe`）
        path: 视频文件
        timeout: 单次探测超时。大文件在慢盘上首帧解析可能几秒，给足。
    """
    p = Path(path)
    if not p.is_file():
        return 0.0
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(p),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if result.returncode != 0:
        return 0.0
    try:
        return float((result.stdout or "").strip())
    except ValueError:
        return 0.0


def total_duration(ffprobe: str, paths: Iterable[Path]) -> float:
    """一组视频的总时长"""
    return sum(probe_duration(ffprobe, p) for p in paths)


def longest(ffprobe: str, paths: Sequence[Path]) -> tuple[Path | None, float]:
    """最长的那个视频（判断"长片是否已导出"用）"""
    best: Path | None = None
    best_len = 0.0
    for p in paths:
        d = probe_duration(ffprobe, p)
        if d > best_len:
            best, best_len = p, d
    return best, best_len


def hhmmss(seconds: float) -> str:
    """秒 → `2:05` / `1:02:03`"""
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def probe_video_info(ffprobe: str, path: Path, timeout: float = 60.0) -> dict:
    """读视频的分辨率和帧率。读不到返回空 dict。

    用途：剪映的分辨率下拉在 6.0.1 上没法用程序选（选项项在 UIA 里不可见），
    所以配置里写 `1080P` 只能"尽力而为"。**真正的把关在这里** ——
    导出完读一次产物，和配置比，不对就报出来。

    Returns:
        {"width": int, "height": int, "fps": float}，失败时 {}
    """
    p = Path(path)
    if not p.is_file():
        return {}
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(p),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    if len(lines) < 3:
        return {}
    try:
        width, height = int(lines[0]), int(lines[1])
    except ValueError:
        return {}
    fps = 0.0
    if "/" in lines[2]:
        num, _, den = lines[2].partition("/")
        try:
            fps = float(num) / float(den) if float(den) else 0.0
        except ValueError:
            fps = 0.0
    else:
        try:
            fps = float(lines[2])
        except ValueError:
            fps = 0.0
    return {"width": width, "height": height, "fps": round(fps, 2)}


def probe_fps(ffprobe: str, path: Path, timeout: float = 60.0) -> float:
    """读视频平均帧率。读不到返回 0.0。

    用途：`-c copy` 拼接要求各段帧率/timebase 一致，否则时间戳会被按
    timebase 比例放大（实测 25fps 片头 + 30fps 正片 → 2 分钟的片子
    显示 20 小时，而且 ffmpeg 退出码还是 0）。
    """
    p = Path(path)
    if not p.is_file():
        return 0.0
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1", str(p),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    raw = (result.stdout or "").strip().splitlines()
    if not raw:
        return 0.0
    value = raw[0].strip()
    try:
        if "/" in value:
            num, _, den = value.partition("/")
            return round(float(num) / float(den), 3) if float(den) else 0.0
        return round(float(value), 3)
    except ValueError:
        return 0.0


def describe_video_info(info: dict) -> str:
    """`1920x1080@30fps`；读不到就空串"""
    if not info:
        return ""
    return f"{info['width']}x{info['height']}@{info['fps']:g}fps"
