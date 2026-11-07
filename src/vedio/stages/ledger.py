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
import sys
import time
from typing import Any, Optional

from .. import media
from .. import progress
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
            collection_name,      # A 合集名（篇名-上篇/下篇）
            self.title,           # B 精彩看点 = 该集标题
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
        by_index: dict[int, Path] = {}
        for p in files:
            idx = rename_stage.episode_index(p)
            if idx is not None:
                by_index.setdefault(idx, p)
        unindexed = [p for p in files if rename_stage.episode_index(p) is None]

        if not files:
            problems.append(f"{name}: 成片/ 里没有视频")
            continue

        # **以标题为准**：一个标题一行。
        #
        # 为什么不按成片遍历：素材比目标长一点时，剪出来会多一到两个片段
        # （那是废篇，匀素材环节该处理掉的）。按成片遍历会把废篇也写进台账，
        # 甲方看到的是"多出来的集"，实际根本没这集内容。
        # 标题是人定的交付清单，台账就照它写。
        durations = {idx: media.probe_duration(project.ffprobe, p)
                     for idx, p in by_index.items()}
        total = round(sum(durations.values()), 1)

        missing: list[int] = []
        for i, title in enumerate(titles, 1):
            path = by_index.get(i)
            if path is None:
                missing.append(i)
                continue
            rows.append(LedgerRow(
                collection=name, episode=i, title=title,
                seconds=durations[i], collection_seconds=total,
                intro_seconds=intro,
            ))

        # 有标题却找不到成片 —— 这是缺集，必须报
        if missing:
            problems.append(f"{name}: 第 {'、'.join(str(i) for i in missing)} "
                            f"集找不到成片（标题有 {len(titles)} 条）")

        # 有额外成片却没有标题 —— 废篇，不进台账，但要如实说
        extras = sorted(idx for idx in by_index if idx > len(titles))
        if extras or unindexed:
            names = [by_index[i].name for i in extras] + [p.name for p in unindexed]
            problems.append(f"{name}: {len(names)} 个成片没有对应标题，"
                            f"未计入台账（废篇，可用 balance 匀素材消掉）："
                            f"{'、'.join(names[:5])}"
                            + ("…" if len(names) > 5 else ""))
    return rows, problems


# ─────────────────────────── 写 Excel ───────────────────────────

def _load_excel_generator(path: Path):
    """加载外部片单生成脚本（`conf/本机.yaml` 的 `paths.excel_generator`）。

    为什么不自带实现：那份脚本的格式（汇总行、纵向合并、红/黑配色、边框）
    是用户验证过的稳定版本，重写一遍只会引入差异。
    """
    import importlib.util

    if not path.is_file():
        raise FileNotFoundError(
            f"片单生成脚本不存在：{path}\n"
            f"请在 conf/本机.yaml 的 paths.excel_generator 里填对路径"
        )
    name = "vedio_excel_generator"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)      # type: ignore[union-attr]
    return module


def _collections_payload(rows: list[LedgerRow], project: Project) -> list[dict[str, Any]]:
    """把台账行整理成生成脚本要的 JSON。

    它需要 `第X集 标题` 这种形态的 `filename`，所以这里用和 `rename`
    同一套命名（避免文件名和台账两处不一致）。
    """
    from . import rename as rename_stage

    by_collection: dict[str, list[LedgerRow]] = {}
    for row in rows:
        by_collection.setdefault(row.collection, []).append(row)

    payload: list[dict[str, Any]] = []
    for name, items in by_collection.items():
        items.sort(key=lambda r: r.episode)
        full = project.titles.full_collection_name(name) or name
        payload.append({
            "series_title": full,
            "video_count": len(items),
            # **必须整数**：生成脚本里有 f'{minutes:02d}:{seconds:02d}'，
            # 传 float 会直接 ValueError（实测踩过）
            "total_duration": int(round(sum(r.seconds for r in items))),
            "videos": [
                {
                    "filename": f"{rename_stage.episode_label(r.episode)} {r.title}",
                    "episode_num": r.episode,
                    "duration": int(round(r.seconds)),
                }
                for r in items
            ],
        })
    return payload


def ledger_target(project: Project, month: int | None = None) -> Path:
    """交付用的台账路径：`{ledger_root}/{year}/26年{host}{month}月第一批片单.xlsx`。

    台账是**交付物**，不属于某个批次 —— 同一个月几批共用一份命名规则。

    **不做自动改名**（`_1`、`_2` 那种）：那样每跑一次夜里任务就多一份表，
    人还得自己去分辨哪份是最终版。存在就跳过，要重写就 `--force`。
    """
    local = getattr(project, "local", None)
    root = getattr(local, "ledger_root", None) or (project.batch_dir / "台账")
    year = int(project.rule("meta.year", 2026) or 2026)
    host = project.host or ""
    month = month or int(time.strftime("%m"))
    return Path(root) / str(year) / f"{year % 100}年{host}{month}月第一批片单.xlsx"


def write_workbook(path: Path, rows: list[LedgerRow], project: Project) -> None:
    """写 xlsx —— 交给外部稳定脚本，不在本仓库里重实现格式。"""
    import json
    import tempfile

    local = getattr(project, "local", None)
    generator = getattr(local, "excel_generator", None)
    if generator is None:
        raise FileNotFoundError(
            "没有配置片单生成脚本（conf/本机.yaml 的 paths.excel_generator）")

    module = _load_excel_generator(Path(generator))
    payload = _collections_payload(rows, project)

    intro = 0.0
    if rows:
        intro = rows[0].intro_seconds
    tmp = Path(tempfile.mkdtemp()) / "ledger.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        module.generate_excel_from_json(
            str(tmp), str(path),
            host=project.host or "",
            category=str(project.rule("meta.category", "") or ""),
            year=project.rule("meta.year", 2026),
            intro_duration=int(round(intro)),
        )
    finally:
        try:
            tmp.unlink()
            tmp.parent.rmdir()
        except OSError:
            pass


def build_ledger(project: Project, collections: Optional[list[str]] = None, *,
                 log: Optional[EventLog] = None,
                 force: bool = False) -> LedgerResult:
    """生成 `{批次}/台账.xlsx`"""
    if log is None:
        log = EventLog(project.log_dir)

    out = ledger_target(project)
    if out.is_file() and not force:
        log.emit("ledger", "skip", reason="already_done", file=out.name)
        return LedgerResult("skip", path=out, message=f"{out.name} 已存在（--force 可重写）")

    # ── 硬约束：没有篇名不许写台账 ──
    # 台账是交付凭证，篇名那一列空了，甲方拿到的就是一张半成品表。
    # 而且台账一旦生成，后面再补篇名就得整份重写 —— 不如现在拦住。
    try:
        targets = [c.name for c in project.resolve_collections(collections)]
    except Exception:
        targets = []
    missing = [n for n in targets if not (project.subtitle_for(n) or "").strip()]
    if missing:
        message = (f"这些合集还没有篇名：{'、'.join(missing)}。"
                   f"台账必须有篇名，先跑 vedio series 定下来。")
        log.emit("ledger", FAIL, error="title_missing", message=message,
                 collections=missing)
        return LedgerResult("fail", error="title_missing", message=message)

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
    except PermissionError:
        message = (f"写不进去：{out.name} 正被其他程序占用（大概是 Excel 开着）。"
                   f"关掉它再跑。")
        log.emit("ledger", FAIL, error="file_locked", message=message, file=str(out))
        return LedgerResult("fail", error="file_locked", message=message)
    except Exception as exc:                 # noqa: BLE001
        log.emit("ledger", FAIL, error=type(exc).__name__, message=str(exc))
        return LedgerResult("fail", error=type(exc).__name__, message=str(exc))

    involved = sorted({r.collection for r in rows})
    log.emit("ledger", DONE, rows=len(rows), collections=involved, file=out.name,
             warnings=problems)
    # 台账那一列写文件名 —— 这是唯一"文件里推不出来"的事实，必须记下来
    for name in involved:
        progress.record(project, name, "台账", out.name)
    return LedgerResult("done", path=out, collections=involved, rows=len(rows),
                        message=f"{len(rows)} 行 / {len(involved)} 个合集"
                                + ("（有警告）" if problems else ""))
