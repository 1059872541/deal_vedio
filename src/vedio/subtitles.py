# -*- coding: utf-8 -*-
"""vedio.subtitles —— SRT 解析、打补丁、加行号（纯函数，不碰路径）

取代旧的 `words/updateSRT.py`（139 行，带 `sys.argv` 和 print 副作用）。
拆成可测的纯函数：

    parse_srt(text)        → [Block]
    apply_patch(blocks, {行号: 新文本})
    render_srt(blocks)     → text
    patch_file(...)        → 组合上面三步读写文件
    add_line_numbers(text) → "1:xxx\\n2:yyy"

两个格式约定（都是实测定下来的，见 `docs/目标架构.md` §5）：

1. **纠正补丁格式**：`行号:纠正后内容`，一行一条。这是"差分"模型 ——
   模型只回有错的行，没提的行保持原样。
2. **输出 SRT 编码**：UTF-8 **无 BOM** + CRLF。实测剪映自己导出的 srt
   就是这个格式（头 3 字节 `1\\r\\n`，7232 个 CRLF、0 个裸 LF）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional

#: SRT 时间轴行
_TIME_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*$"
)

#: 补丁行：`12:纠正后的内容`，也容忍 `12|内容`
_PATCH_RE = re.compile(r"^\s*(\d+)\s*[:|]\s?(.*)$")


@dataclass
class Block:
    """一个字幕块"""

    index: int
    start: str                # 原样保留时间字符串
    end: str
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def as_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "end": self.end, "text": self.text}


# ─────────────────────────── 解析 ───────────────────────────

def normalize_newlines(text: str) -> str:
    """统一成 `\\n`（读进来可能是 CRLF / CR / LF 混着）"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_srt(text: str) -> list[Block]:
    """解析 SRT。

    容忍：BOM、CRLF、块间多余空行、序号不连续（按出现顺序重排）。
    宁可宽松也不要丢字幕 —— 丢一条就少一句校对。
    """
    content = normalize_newlines(text.lstrip("\ufeff"))
    blocks: list[Block] = []
    current: Optional[Block] = None

    for raw in content.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if current is not None:
                blocks.append(current)
                current = None
            continue

        if current is None:
            # 期待序号行；如果不是，说明这个块没有序号，直接当时间轴处理
            stripped = line.strip()
            if stripped.isdigit():
                current = Block(index=int(stripped), start="", end="", lines=[])
                continue
            m = _TIME_RE.match(line)
            if m:
                current = Block(index=len(blocks) + 1, start=m.group(1), end=m.group(2), lines=[])
            continue

        if not current.start:
            m = _TIME_RE.match(line)
            if m:
                current.start, current.end = m.group(1), m.group(2)
            # 既不是序号也不是时间轴 → 丢掉这行（通常是垃圾）
            continue

        current.lines.append(line)

    if current is not None:
        blocks.append(current)
    return blocks


def render_srt(blocks: Iterable[Block], *, crlf: bool = True) -> str:
    """输出 SRT。**序号按顺序重排**，块间空一行，末尾不留多余空行。"""
    out: list[str] = []
    for i, b in enumerate(blocks, 1):
        out.append(str(i))
        out.append(f"{b.start} --> {b.end}")
        out.extend(b.lines if b.lines else [""])
        out.append("")
    text = "\n".join(out).rstrip("\n") + "\n"
    return text.replace("\n", "\r\n") if crlf else text


# ─────────────────────────── 补丁 ───────────────────────────

def parse_patch(text: str) -> dict[int, str]:
    """解析 `行号:内容`。

    续行（没有行号前缀的行）归到上一条 —— 旧实现支持多行纠正，
    这里保持一致。空行和无法识别的行忽略。
    """
    patch: dict[int, str] = {}
    last: Optional[int] = None
    for raw in normalize_newlines(text.lstrip("\ufeff")).split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _PATCH_RE.match(line)
        if m:
            last = int(m.group(1))
            patch[last] = m.group(2).rstrip()
        elif last is not None:
            patch[last] = (patch[last] + "\n" + line.strip()).strip("\n")
    return patch


def apply_patch(blocks: list[Block], patch: dict[int, str]) -> tuple[list[Block], dict]:
    """把补丁应用到字幕块上。

    **按序号匹配**（不是按数组下标）：SRT 里的序号就是补丁里的行号。

    Returns:
        (新块列表, 统计) 统计含 applied / missing（补丁里找不到对应块的行号）
    """
    by_index = {b.index: b for b in blocks}
    applied = 0
    missing: list[int] = []
    for index, text in patch.items():
        block = by_index.get(index)
        if block is None:
            missing.append(index)
            continue
        lines = [ln for ln in text.split("\n")] if text else [""]
        by_index[index] = replace(block, lines=lines)
        applied += 1
    new_blocks = [by_index[b.index] for b in blocks]
    return new_blocks, {"applied": applied, "missing": sorted(missing), "total": len(blocks)}


# ─────────────────────────── 文件级 ───────────────────────────

def read_text(path: Path) -> str:
    """读文本：容忍 BOM（剪映导出的 txt 可能带）"""
    return Path(path).read_text(encoding="utf-8-sig")


def write_srt(path: Path, blocks: Iterable[Block]) -> None:
    """写 SRT：UTF-8 无 BOM + CRLF，与剪映自己导出的格式一致"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        f.write(render_srt(blocks, crlf=True))


def patch_file(srt_path: Path, patch_path: Path, out_path: Optional[Path] = None) -> dict:
    """读 srt + 补丁 → 写 `_corrected.srt`

    Returns:
        统计：{total, applied, missing, out}
    """
    srt_path = Path(srt_path)
    patch_path = Path(patch_path)
    out = Path(out_path) if out_path else srt_path.with_name(f"{srt_path.stem}_corrected.srt")

    blocks = parse_srt(read_text(srt_path))
    patch = parse_patch(read_text(patch_path))
    new_blocks, stats = apply_patch(blocks, patch)
    write_srt(out, new_blocks)
    return {**stats, "out": str(out)}


def add_line_numbers(text: str, start: int = 1) -> str:
    """给每行加 `行号:`。空行跳过（模型不需要空行）。"""
    lines = [ln.rstrip() for ln in normalize_newlines(text).split("\n")]
    numbered = [f"{i}:{ln}" for i, ln in enumerate((ln for ln in lines if ln.strip()), start)]
    return "\n".join(numbered) + ("\n" if numbered else "")


def number_file(src: Path, out: Optional[Path] = None) -> dict:
    """`xx.txt` → `xx_ordered.txt`"""
    src = Path(src)
    dst = Path(out) if out else src.with_name(f"{src.stem}_ordered.txt")
    content = add_line_numbers(read_text(src))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8", newline="\n")
    return {"out": str(dst), "lines": content.count("\n")}


# ─────────────────────────── 找输入 ───────────────────────────

def find_source_txt(directory: Path) -> Optional[Path]:
    """剪辑/ 里那份**剪映导出的**字幕 txt。

    排除中间产物：`*_ordered.txt`（我们生成的）和 `corrected.txt`（模型产出）。
    目录里有多个候选时按名字排序取第一个 —— 但正常情况应该只有一个，
    多了说明人放错了，调用方应当提示。
    """
    d = Path(directory)
    if not d.is_dir():
        return None
    cands = sorted(
        p for p in d.glob("*.txt")
        if p.is_file()
        and "_ordered" not in p.stem
        and p.stem != "corrected"
    )
    return cands[0] if cands else None


def find_source_srt(directory: Path) -> Optional[Path]:
    """剪辑/ 里那份**剪映导出的** srt。

    排除 `*_corrected.srt`（我们生成的）。同样应当只有一个。
    """
    d = Path(directory)
    if not d.is_dir():
        return None
    cands = sorted(p for p in d.glob("*.srt") if p.is_file() and "_corrected" not in p.stem)
    return cands[0] if cands else None


def find_corrected(directory: Path) -> Optional[Path]:
    d = Path(directory)
    p = d / "corrected.txt"
    return p if p.is_file() else None
