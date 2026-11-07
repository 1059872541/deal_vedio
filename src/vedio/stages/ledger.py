# -*- coding: utf-8 -*-
"""vedio.stages.ledger —— 生成台账 Excel

列序是**冻结规则**（`docs/目标架构.md` §5），改了对接方就不认：

    A 合集名 / B 精彩看点 / C 时长(秒) / D 合集时长 / E 片头时长
    F 减片头 / G 主播 / H 类别 / I 集数 / J 年份 / K 内容介绍 / L 关键字

数据从三处来：
    `标题.md`        合集全名 + 每集标题
    `成片/` + ffprobe 每集实际时长
    `合集清单.yaml`   片头时长（登记的那个文件 probe 出来）
    `game.yaml`      主播 / 类别 / 年份

**B / K / L 三列目前留空** —— 内容来源还没定（是人工写、还是让模型从字幕生成），
`TODO.md` 里记着这条。留空比编一个假值好：错的数据下游更难查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .. import media
from ..context import Collection, Project
from ..events import DONE, FAIL, EventLog
from . import rename as rename_stage

#: 冻结列序
COLUMNS = [
    "合集名", "精彩看点", "时长(秒)", "合集时长", "片头时长",
    "减片头", "主播", "类别", "集数", "年份", "内容介绍", "关键字",
]


class LedgerError(Exception):
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


@dataclass
class LedgerRow:
    collection: str
    episode: int
    title: str
    seconds: float
    collection_seconds: float
    intro_seconds: float

    @property
    def without_intro(self) -> float:
        return round(max(0.0, self.seconds - self.intro_seconds), 1)

    def as_list(self, *, collection_name: str, host: str, category: str,
                year: Any) -> list[Any]:
        return [
            collection_name,      # A 合集名
            "",                   # B 精彩看点（来源待定）
            round(self.seconds, 1),
            self.collection_seconds,
            round(self.intro_seconds, 1),
            self.without_intro,
            host,
            category,
            self.episode,
            year,
            "",                   # K 内容介绍（来源待定）
            "",                   # L 关键字（来源待定）
        ]


@dataclass
class LedgerResult:
    status: str                       # done / skip / fail
    path: Optional[Path] = None
    collections: list[str] = field(default_factory=list)
    rows: int = 0
    error: Optional[str] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skip")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": str(self.path) if self.path else None,
            "collections": self.collections,
            "rows": self.rows,
            "error": self.error,
            "message": self.message,
        }


# ─────────────────────────── 取数 ───────────────────────────

def intro_seconds(project: Project, collection: Collection) -> float:
    """这个合集的片头有多长（没登记就是 0）"""
    path = project.intro_for(collection.name)
    if path is None or not Path(path).is_file():
        return 0.0
    return media.probe_duration(project.ffprobe, Path(path))


def collect_rows(project: Project, collections: Optional[list[str]] = None
                 ) -> tuple[list[LedgerRow], list[str]]:
    """把一个合集的每集信息摊成行。

    Returns:
        (rows, problems)
    """
    rows: list[LedgerRow] = []
    problems: list[str] = []

    for collection in project.resolve_collections(collections):
        name = collection.name
        titles = project.titles_of(name)
        if not titles:
            problems.append(f"{name}: 标题.md 里没有这一节")
            continue

        intro = intro_seconds(project, collection)

        # 成片按编号对齐标题（和 rename 用同一套规则，避免两边理解不一致）
        files = media.list_videos(collection.final)
        indexed = []
        for p in files:
            idx = rename_stage.episode_index(p)
            indexed.append((idx if idx is not None else 10_000, p))
        indexed.sort()

        if not indexed:
            problems.append(f"{name}: 成片/ 里没有视频")
            continue
        if len(indexed) != len(titles):
            problems.append(f"{name}: 成片 {len(indexed)} 个，标题 {len(titles)} 条")

        durations = [media.probe_duration(project.ffprobe, p) for _, p in indexed]
        total = round(sum(durations), 1)

        for i, ((_, path), seconds) in enumerate(zip(indexed, durations)):
            title = titles[i] if i < len(titles) else path.stem
            rows.append(LedgerRow(
                collection=name, episode=i + 1, title=title,
                seconds=seconds, collection_seconds=total, intro_seconds=intro,
            ))
    return rows, problems


# ─────────────────────────── 写 Excel ───────────────────────────

def write_workbook(path: Path, rows: list[LedgerRow], project: Project) -> None:
    """写 xlsx。用 openpyxl（已在依赖里）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    ws = wb.active
    ws.title = "台账"

    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    host = project.host
    category = str(project.rule("meta.category", "") or "")
    year = project.rule("meta.year", "")

    for row in rows:
        collection_name = project.titles.full_collection_name(row.collection) or row.collection
        ws.append(row.as_list(collection_name=collection_name, host=host,
                              category=category, year=year))

    widths = [30, 14, 10, 10, 10, 10, 8, 8, 8, 8, 24, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def build_ledger(project: Project, collections: Optional[list[str]] = None, *,
                 log: Optional[EventLog] = None,
                 force: bool = False) -> LedgerResult:
    """生成 `{批次}/台账.xlsx`"""
    if log is None:
        log = EventLog(project.log_dir)

    out = project.ledger_file
    if out.is_file() and not force:
        log.emit("ledger", "skip", reason="already_done", file=out.name)
        return LedgerResult("skip", path=out, message=f"{out.name} 已存在（--force 可重写）")

    try:
        rows, problems = collect_rows(project, collections)
    except Exception as exc:                 # noqa: BLE001
        log.emit("ledger", FAIL, error=type(exc).__name__, message=str(exc))
        return LedgerResult("fail", error=type(exc).__name__, message=str(exc))

    if not rows:
        message = "没有可写的数据" + (("：" + "；".join(problems)) if problems else "")
        log.emit("ledger", FAIL, error="no_data", message=message)
        return LedgerResult("fail", error="no_data", message=message)

    try:
        write_workbook(out, rows, project)
    except Exception as exc:                 # noqa: BLE001
        log.emit("ledger", FAIL, error=type(exc).__name__, message=str(exc))
        return LedgerResult("fail", error=type(exc).__name__, message=str(exc))

    involved = sorted({r.collection for r in rows})
    log.emit("ledger", DONE, rows=len(rows), collections=involved, file=out.name,
             warnings=problems)
    return LedgerResult("done", path=out, collections=involved, rows=len(rows),
                        message=f"{len(rows)} 行 / {len(involved)} 个合集"
                                + ("（有警告）" if problems else ""))
