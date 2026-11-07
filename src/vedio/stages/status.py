# -*- coding: utf-8 -*-
"""vedio.stages.status —— 批次进度表（只读）

**这个阶段不写任何文件。** 它只做一件事：从文件系统和 `events.jsonl`
推导出每个合集走到哪一步，然后画一张表。

判定规则来自 `docs/目标架构.md` §4，全部"看文件"，不看数据库：

    素材   素材/ 下视频总时长 ≥ duration.material_per_collection
    剪辑   素材达标 → 剪辑中（主体是人，系统只看）
    字幕   剪辑/*_corrected.srt 存在
    导出   剪辑/ 下有 ≥目标时长的单文件
    拼接   先校验片头片尾，再判 成片/ 下视频数 ≈ episode_count
    命名   成片/ 文件名能对上 标题.md 里的每条标题
    台账   events.jsonl 里有该合集的 ledger done（不看 Excel 文件数）

为什么要分成"采集"和"渲染"两步：采集结果要能 `--json` 输出给 agent 读，
渲染只是给人看的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .. import context, media
from ..context import Collection, Project
from ..events import EventLog

#: 探测函数签名：给路径，返回秒数
Probe = Callable[[Path], float]


# ─────────────────────────── 数据结构 ───────────────────────────

@dataclass
class CollectionStatus:
    """一个合集的体检结果"""

    collection: str
    # 素材
    material_files: int = 0
    material_seconds: float = 0.0
    material_target: float = 0.0
    # 剪辑 / 字幕
    subtitle_file: Optional[Path] = None
    # 导出
    export_file: Optional[Path] = None
    export_seconds: float = 0.0
    # 拼接
    templates_ok: bool = False
    template_problems: list = field(default_factory=list)
    final_count: int = 0
    episode_count: int = 0
    # 命名
    named_ok: Optional[bool] = None       # None = 标题.md 里没有这个合集
    named_missing: list = field(default_factory=list)
    # 台账
    ledger_ok: bool = False
    # 分支事实
    draft: Optional[str] = None
    # 最近一次运行
    last_action: Optional[str] = None
    last_seconds: Optional[float] = None

    # ── 派生判定 ──

    @property
    def material_ok(self) -> bool:
        return self.material_target <= 0 or self.material_seconds >= self.material_target

    @property
    def subtitle_ok(self) -> bool:
        return self.subtitle_file is not None

    @property
    def export_ok(self) -> bool:
        return self.export_file is not None

    @property
    def splice_ok(self) -> bool:
        return self.templates_ok and self.final_count >= self.episode_count > 0

    @property
    def stage(self) -> str:
        """当前所在的阶段名（人话）"""
        if not self.material_ok:
            return "素材"
        if not self.subtitle_ok:
            return "剪辑"
        if not self.export_ok:
            return "字幕"
        if not self.splice_ok:
            return "导出"
        if self.named_ok is False:
            return "拼接"
        if not self.ledger_ok:
            return "命名"
        return "完成"

    @property
    def done(self) -> bool:
        return self.stage == "完成"

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "stage": self.stage,
            "done": self.done,
            "material": {
                "files": self.material_files,
                "seconds": round(self.material_seconds, 1),
                "target": self.material_target,
                "ok": self.material_ok,
            },
            "subtitle": {"file": str(self.subtitle_file) if self.subtitle_file else None,
                         "ok": self.subtitle_ok},
            "export": {"file": str(self.export_file) if self.export_file else None,
                       "seconds": round(self.export_seconds, 1), "ok": self.export_ok},
            "splice": {"templates_ok": self.templates_ok,
                       "problems": self.template_problems,
                       "final_count": self.final_count,
                       "episode_count": self.episode_count,
                       "ok": self.splice_ok},
            "named": {"ok": self.named_ok, "missing": self.named_missing},
            "ledger": {"ok": self.ledger_ok},
            "draft": self.draft,
            "last": {"action": self.last_action, "seconds": self.last_seconds},
        }


@dataclass
class BatchStatus:
    """整批"""

    game: str
    batch: str
    name: str
    collections: list[CollectionStatus] = field(default_factory=list)

    @property
    def episode_total(self) -> int:
        return sum(c.episode_count for c in self.collections)

    @property
    def done_count(self) -> int:
        return sum(1 for c in self.collections if c.done)

    def as_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "batch": self.batch,
            "name": self.name,
            "collection_count": len(self.collections),
            "episode_total": self.episode_total,
            "done": self.done_count,
            "collections": [c.as_dict() for c in self.collections],
        }


# ─────────────────────────── 采集 ───────────────────────────

def _default_probe(project: Project) -> Probe:
    def probe(path: Path) -> float:
        return media.probe_duration(project.ffprobe, path)
    return probe


def collect_collection(project: Project, collection: Collection,
                       probe: Probe, log: Optional[EventLog] = None) -> CollectionStatus:
    """把一个合集的体检做出来（纯读）"""
    st = CollectionStatus(
        collection=collection.name,
        material_target=float(project.material_target),
        episode_count=int(project.episode_count),
        draft=project.draft_for(collection.name),
    )

    # ── 素材 ──
    videos = media.list_videos(collection.material)
    st.material_files = len(videos)
    st.material_seconds = sum(probe(p) for p in videos)

    # ── 字幕 ──
    corrected = sorted(collection.editing.glob("*_corrected.srt")) if collection.editing.is_dir() else []
    if corrected:
        st.subtitle_file = corrected[0]

    # ── 导出：剪辑/ 里最长的那条片子 ──
    # 注意用注入的 probe，不要直接调 media.probe_duration —— 否则测试注入失效
    if collection.editing.is_dir():
        for p in media.list_videos(collection.editing):
            seconds = probe(p)
            if seconds > st.export_seconds:
                st.export_file, st.export_seconds = p, seconds

    # ── 拼接前置：片头片尾 ──
    tpl = project.validate_templates(collection.name)
    st.templates_ok = bool(tpl["ok"])
    st.template_problems = list(tpl["problems"])

    # ── 拼接结果 ──
    finals = media.list_videos(collection.final) if collection.final.is_dir() else []
    st.final_count = len(finals)

    # ── 命名 ──
    titles = project.titles_of(collection.name)
    if titles:
        names = [f.stem for f in finals]
        missing = [t for t in titles if not any(t in n for n in names)]
        st.named_missing = missing
        st.named_ok = not missing
    else:
        st.named_ok = None

    # ── 台账：看登记，不看 Excel 文件数 ──
    if log is not None:
        st.ledger_ok = log.last(verb="ledger", collection=collection.name, event="done") is not None
        last = log.last(collection=collection.name, event="done")
        if last is not None:
            st.last_action = last.verb
            st.last_seconds = last.fields.get("seconds")

    return st


def collect(project: Project, probe: Optional[Probe] = None,
            log: Optional[EventLog] = None,
            collections: Optional[list[str]] = None) -> BatchStatus:
    """整批体检

    Args:
        project: 已打开的批次
        probe: 时长探测函数；默认用 project.ffprobe 真跑 ffprobe（测试可注入）
        log: 事件日志；给了才能判台账状态
        collections: 只查这些合集；None = 全部
    """
    if log is None:
        try:
            log = EventLog(project.log_dir)
        except OSError:
            log = None
    probe = probe or _default_probe(project)

    targets = project.resolve_collections(collections)
    status = BatchStatus(game=project.game, batch=project.batch, name=project.name)
    for c in targets:
        status.collections.append(collect_collection(project, c, probe, log))
    return status


# ─────────────────────────── 渲染 ───────────────────────────

def _mark(ok: Optional[bool]) -> str:
    if ok is None:
        return "·"
    return "✓" if ok else "✗"


def render(status: BatchStatus) -> str:
    """画进度表。

    ```
    📊 我的世界-2026-12   2 合集 / 40 集   完成 1
    合集    素材      剪辑  字幕  导出  拼接  命名  台账
    合集一  ✓         ✓     ✓     ✓     ✓     ✓     ✓
    合集二  12:00/20:00  ·     ·     ·     ·     ·     ·
    ```
    """
    head = (f"📊 {status.name}   {len(status.collections)} 合集 / "
            f"{status.episode_total} 集   完成 {status.done_count}")
    cols = ["素材", "剪辑", "字幕", "导出", "拼接", "命名", "台账"]

    rows: list[tuple[str, list[str]]] = []
    for c in status.collections:
        if not c.material_ok:
            mat = f"{media.hhmmss(c.material_seconds)}/{media.hhmmss(c.material_target)}"
        else:
            mat = "✓"
        rows.append((c.collection, [
            mat,
            _mark(c.material_ok),
            _mark(c.subtitle_ok),
            _mark(c.export_ok),
            _mark(c.splice_ok),
            _mark(c.named_ok),
            _mark(c.ledger_ok),
        ]))

    # 列宽：中文按 2 个字符宽算，避免表格歪掉
    def width(s: str) -> int:
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)

    def pad(s: str, w: int) -> str:
        return s + " " * max(0, w - width(s))

    name_w = max([width("合集")] + [width(r[0]) for r in rows]) + 2
    col_ws = []
    for i, col in enumerate(cols):
        w = max([width(col)] + [width(r[1][i]) for r in rows]) + 2
        col_ws.append(w)

    lines = [head, pad("合集", name_w) + "".join(pad(col, col_ws[i]) for i, col in enumerate(cols))]
    for name, cells in rows:
        lines.append(pad(name, name_w) + "".join(pad(cell, col_ws[i]) for i, cell in enumerate(cells)))
    return "\n".join(lines)


def render_next(status: BatchStatus) -> str:
    """每个合集下一步该干什么（一句话）"""
    hints = {
        "素材": "继续录制，把素材放进 素材/",
        "剪辑": "在剪映里剪，剪完导出 .txt + .srt 到 剪辑/",
        "字幕": "跑 subtitle；改完导入剪映审查，审完跑 export",
        "导出": "跑 splice（片头片尾要先齐）",
        "拼接": "跑 rename（按 标题.md 改名）",
        "命名": "跑 ledger（生成台账）",
    }
    lines = []
    for c in status.collections:
        if c.done:
            continue
        lines.append(f"  {c.collection}: {hints.get(c.stage, '')}")
    return "\n".join(lines) or "  全部完成"
