"""
FFmpeg 工具函数封装
路径: src/util/ffmpeg_utils.py

统一管理 ffmpeg/ffprobe 路径、视频时长获取、视频切割。
"""

import subprocess
from pathlib import Path

# ── 路径 ──
FFMPEG_PATH = r"D:\softwares\ffmpeg\bin\ffmpeg.exe"
FFPROBE_PATH = r"D:\softwares\ffmpeg\bin\ffprobe.exe"

# ── 常量 ──
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".ts", ".flv", ".wmv")


def get_video_duration(filepath: str | Path) -> float:
    """ffprobe 获取视频时长（秒），返回 float"""
    try:
        result = subprocess.run(
            [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
            capture_output=True, text=True, timeout=60
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def get_video_duration_int(filepath: str | Path) -> int:
    """ffprobe 获取视频时长（秒），返回 int（四舍五入）"""
    return round(get_video_duration(filepath))


def split_video(input_path: Path, cut_time: float) -> tuple[Path, Path] | None:
    """
    用 ffmpeg 关键帧切割视频（无重编码 -c copy）。

    返回:
        (前段路径, 后段路径)
        失败时返回 None，自动清理临时文件。
    """
    parent = input_path.parent
    stem = input_path.stem
    suffix = input_path.suffix

    part1 = parent / f"{stem}.part1{suffix}"
    part2 = parent / f"{stem}.part2{suffix}"

    try:
        subprocess.run(
            [FFMPEG_PATH, "-y", "-ss", "0", "-i", str(input_path),
             "-t", str(cut_time), "-c", "copy", "-map", "0",
             "-avoid_negative_ts", "make_zero", str(part1)],
            check=True, capture_output=True, timeout=3600
        )
        subprocess.run(
            [FFMPEG_PATH, "-y", "-ss", str(cut_time), "-i", str(input_path),
             "-c", "copy", "-map", "0",
             "-avoid_negative_ts", "make_zero", str(part2)],
            check=True, capture_output=True, timeout=3600
        )
        return (part1, part2)
    except Exception:
        for p in [part1, part2]:
            if p.exists():
                p.unlink()
        return None
