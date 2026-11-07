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
