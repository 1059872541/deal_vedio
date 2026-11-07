# -*- coding: utf-8 -*-
"""vedio.progress —— 批次进度表（`{批次}/进度.md`）

**定位：这是记录，不是证据。**

- 环节跑成功 → 打 ✓；失败或跳过 → 什么都不改；**永不把 ✓ 擦回 `·`**
- 人可以直接改这个表（改错、擦掉、加备注都行）；程序只动它刚跑过的那几格
- 表格解析不了 → 备份成 `.bak` 再重建，绝不闷头覆盖

**为什么不做文件校验**：每个环节都有人兜底 —— 录是人在录、剪是人在剪、
字幕要人导进草稿审查、交付前人会再看一眼。准确性来自甲方压力和人的记忆。
程序再验一遍，验得出的只是"文件现在在不在"，验不出"这件事做没做过"，
还得付 ffprobe 的代价。

**为什么表格外面原样保留**：人在表头下面加几行备注、加一列"备注"，都不该被
程序吃掉。所以只有中间的表格块归程序管，`pre` / `post` 原样带回。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

#: 文件名（放在批次根目录，和 `标题.md` 平级）
FILE_NAME = "进度.md"

#: 所有环节。顺序即表格列序。
STAGES: tuple[str, ...] = ("剪辑", "字幕", "导出", "拼接", "命名", "台账")

#: 空单元格
EMPTY = "·"

#: 打勾
DONE = "✓"

#: 首列名
NAME_COLUMN = "合集"

#: 哪一列是"合集名" —— 用于校验解析结果像不像我们自己的表
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


class ProgressFormatError(Exception):
    """表格结构不是我们认得的形状（比如表头被删了）。"""


def _cells(line: str) -> list[str]:
    """把 `| a | b |` 拆成 ['a', 'b']（容忍首尾没竖线、单元格里有空格）"""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [c.strip() for c in text.split("|")]


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _separator(width: int) -> str:
    return "|" + "|".join(["---"] * width) + "|"


@dataclass
class ProgressTable:
    """一张进度表。只有中间的表格块归程序管，前后文本原样保留。"""

    pre: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    post: list[str] = field(default_factory=list)

    # ── 构造 ──

    @classmethod
    def create(cls, batch_name: str, collections: list[str],
               ignored: Optional[list[str]] = None) -> "ProgressTable":
        pre = [
            f"# 进度 · {batch_name}",
            "",
            "> 人可以直接改这个表。程序只会在环节真正跑成功时把格子打勾，**不会把 ✓ 改回去**。",
            "> 想退回状态就自己擦成 `·`；表格被改乱了也不怕，程序会先备份再重建。",
            "",
        ]
        header = [NAME_COLUMN, *STAGES]
        rows = [[name] + [EMPTY] * len(STAGES) for name in collections]
        post: list[str] = []
        if ignored:
            post = ["", "## 已忽略", "",
                    "这些目录不参与流水线（`game.yaml` 的 `ignore_collections`）：", ""]
            post += [f"- `{name}`" for name in ignored]
            post.append("")
        return cls(pre=pre, header=header, rows=rows, post=post)

    # ── 读写 ──

    @classmethod
    def parse(cls, text: str) -> "ProgressTable":
        """解析已有文件。

        Raises:
            ProgressFormatError: 找不到表格 / 表头第一列不是 `合集`
        """
        lines = text.splitlines()
        start = next((i for i, ln in enumerate(lines) if ln.strip().startswith("|")), None)
        if start is None:
            raise ProgressFormatError("找不到表格（没有任何以 | 开头的行）")

        header = _cells(lines[start])
        if not header or header[0] != NAME_COLUMN:
            raise ProgressFormatError(f"表头第一列应该是「{NAME_COLUMN}」，实际是 {header[:1]}")

        # 第二行是分隔行（|---|），容忍它缺失
        body_start = start + 1
        if body_start < len(lines) and _SEPARATOR_RE.match(lines[body_start]):
            body_start += 1

        rows: list[list[str]] = []
        idx = body_start
        while idx < len(lines) and lines[idx].strip().startswith("|"):
            cells = _cells(lines[idx])
            # 补齐/截断到表头宽度，免得少一列就整行错位
            cells = (cells + [""] * len(header))[:len(header)]
            rows.append(cells)
            idx += 1

        return cls(pre=lines[:start], header=header, rows=rows, post=lines[idx:])

    @classmethod
    def load(cls, path: Path) -> "ProgressTable":
        return cls.parse(Path(path).read_text(encoding="utf-8-sig"))

    def render(self) -> str:
        lines = list(self.pre)
        lines.append(_row(self.header))
        lines.append(_separator(len(self.header)))
        lines.extend(_row(r) for r in self.rows)
        lines.extend(self.post)
        return "\n".join(lines).rstrip("\n") + "\n"

    def save(self, path: Path) -> None:
        """原子写：先写 .tmp 再替换。

        否则进程写到一半崩了，会留下一张"看起来像实况"的半截表格。
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(self.render(), encoding="utf-8", newline="\n")
        os.replace(tmp, target)

    def save_or_rebuild(self, path: Path, batch_name: str,
                        collections: list[str],
                        ignored: Optional[list[str]] = None) -> bool:
        """保存；如果原文件解析不了，先备份成 `.bak` 再重建。

        Returns:
            True = 重建过（调用方可以告诉用户"原文件已备份"）
        """
        target = Path(path)
        if not target.is_file():
            self.save(target)
            return False
        try:
            type(self).load(target)
            self.save(target)
            return False
        except (ProgressFormatError, OSError, UnicodeDecodeError):
            backup = target.with_name(target.name + ".bak")
            try:
                backup.write_bytes(target.read_bytes())
            except OSError:
                pass
            type(self).create(batch_name, collections, ignored).save(target)
            return True

    # ── 操作 ──

    def collections(self) -> list[str]:
        return [r[0] for r in self.rows if r and r[0]]

    def ensure(self, collection: str) -> bool:
        """确保有这个合集的行。返回 True 表示新加了一行。"""
        if collection in self.collections():
            return False
        self.rows.append([collection] + [EMPTY] * (len(self.header) - 1))
        return True

    def cell(self, collection: str, stage: str) -> Optional[str]:
        col = self._column(stage)
        for row in self.rows:
            if row and row[0] == collection:
                return row[col]
        return None

    def set_cell(self, collection: str, stage: str, value: str = DONE) -> bool:
        """把一个格子的值改掉。返回 True 表示真的变了。

        **不擦 ✓**：新值是 `·` 而旧值是 ✓ 时直接拒绝 —— 退回状态只能人来做。
        """
        if value == EMPTY and not self._allow_reset:
            existing = self.cell(collection, stage)
            if existing not in (None, EMPTY):
                return False

        self.ensure(collection)
        col = self._column(stage)
        for row in self.rows:
            if row and row[0] == collection:
                if row[col] == value:
                    return False
                row[col] = value
                return True
        return False

    #: 允许程序把格子擦回 `·`（默认禁止；只有测试和"重建"场景会打开）
    _allow_reset: bool = False

    def _column(self, stage: str) -> int:
        try:
            return self.header.index(stage)
        except ValueError:
            raise ProgressFormatError(
                f"表头里没有「{stage}」列（当前列：{'、'.join(self.header)}）") from None


# ─────────────────────────── 便捷函数 ───────────────────────────

def write_initial(batch_dir: Path, batch_name: str, collections: list[str],
                  ignored: Optional[list[str]] = None) -> Path:
    """建批次时生成一张空表（全部 `·`）。"""
    path = Path(batch_dir) / FILE_NAME
    ProgressTable.create(batch_name, collections, ignored).save(path)
    return path


def add_collections(path: Path, batch_name: str, names: list[str],
                    ignored: Optional[list[str]] = None) -> dict[str, Any]:
    """往已有的表里追加合集行（已有的不动）。

    Returns:
        {"added": [...], "existing": [...], "rebuilt": bool}
    """
    target = Path(path)
    rebuilt = False
    if target.is_file():
        try:
            table = ProgressTable.load(target)
        except (ProgressFormatError, OSError, UnicodeDecodeError):
            backup = target.with_name(target.name + ".bak")
            try:
                backup.write_bytes(target.read_bytes())
            except OSError:
                pass
            table = ProgressTable.create(batch_name, [], ignored)
            rebuilt = True
    else:
        table = ProgressTable.create(batch_name, [], ignored)

    added, existing = [], []
    for name in names:
        if table.ensure(name):
            added.append(name)
        else:
            existing.append(name)
    table.save(target)
    return {"added": added, "existing": existing, "rebuilt": rebuilt}
