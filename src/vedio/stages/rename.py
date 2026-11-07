# -*- coding: utf-8 -*-
"""vedio.stages.rename —— 按 `标题.md` 给成片重命名

期望的文件名由 `game.yaml` 的三层命名模板套出来（三层是**冻结规则**）：

    collection: "{host}之{game} {subtitle}"
    episode:    "第{cn_ep}集 {title}"
    file:       "{collection} {episode}.mp4"

    例：波波之我的世界 收集强力变身-上篇 第一集 林中小屋初探.mp4

前提是 `标题.md` 里这个合集**已经有副标题**（由 `series` 阶段补）。
没有副标题就停 —— 硬编一个名字比不改更糟：台账、网盘目录全跟着错。

成片与标题的对应关系按 splice 产出的编号来：`合集一-01.mp4` 就是第 1 集。
所以命名之前不能手工打乱成片目录。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .. import media
from .. import progress
from ..context import Collection, Project
from ..events import DONE, FAIL, SKIP, EventLog
from util.file_utils import TextUtils

class RenameError(Exception):
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
class RenameResult:
    collection: str
    status: str                       # done / skip / fail
    renamed: list[tuple[str, str]] = field(default_factory=list)
    #: 集数超出标题条数、改不了名的文件
    unmatched: list[str] = field(default_factory=list)
    error: Optional[str] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skip")

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "status": self.status,
            "renamed": [{"from": a, "to": b} for a, b in self.renamed],
            "unmatched": self.unmatched,
            "error": self.error,
            "message": self.message,
        }


# ─────────────────────────── 命名模板 ───────────────────────────

#: 改名**之前**的编号：`合集一-03.mp4` → 3
_INDEX_RE = re.compile(r"-(\d+)$")
#: 改名**之后**的编号：`… 第十集 xxx.mp4` → 10
_CN_EPISODE_RE = re.compile(r"第([一二三四五六七八九十百]+)集")


def episode_label(index: int) -> str:
    """`3` → `第三集`。台账的「精彩看点」写成「第三集 标题」用。"""
    return f"第{TextUtils.number_to_chinese(index)}集"


def episode_index(path: Path) -> Optional[int]:
    """从文件名取集号。

    两种形态都要认：
    - 未改名：`合集一-03.mp4` → 3
    - 已改名：`波波之我的世界 副标题 第十集 标题.mp4` → 10

    **必须都认**：`ledger` 是按集号把成片和标题对齐的。只认旧格式时，
    改过名的成片会被当成"没编号"排到队尾，台账的集号和标题整个错位 ——
    实测踩过（第 21 行挂着「第十集 装备下界遗物」）。
    """
    stem = Path(path).stem
    m = _INDEX_RE.search(stem)
    if m:
        return int(m.group(1))
    m = _CN_EPISODE_RE.search(stem)
    if m:
        num = TextUtils.chinese_to_number(m.group(1))
        return num if num > 0 else None
    return None


def build_names(project: Project, collection: Collection,
                titles: list[str]) -> list[tuple[int, str]]:
    """按三层模板算出每一集应该叫什么。

    三层模板来自 `game.yaml`（冻结规则）：
        {host}之{game} {subtitle}      → 合集全名
        第{cn_ep}集 {title}            → 分集名
        {collection} {episode}.mp4    → 文件名

    `标题.md` 里的「公共前缀」和模板算出的前缀是同一个值（都是 `{host}之{game}`），
    所以以模板为准即可。

    Returns:
        [(集号, 文件名), ...]，集号从 1 开始
    """
    from util.file_utils import TextUtils

    subtitle = project.subtitle_for(collection.name)
    if not subtitle:
        raise RenameError(
            "subtitle_missing",
            f"标题.md 里「{collection.name}」还没有副标题",
            hint="先跑 series 补上篇名与上下篇，否则文件名拼不出来",
        )

    tpl_collection = str(project.rule("naming.collection", "{host}之{game} {subtitle}"))
    tpl_episode = str(project.rule("naming.episode", "第{cn_ep}集 {title}"))
    tpl_file = str(project.rule("naming.file", "{collection} {episode}.mp4"))

    collection_name = tpl_collection.format(
        host=project.host, game=project.game, subtitle=subtitle,
    ).strip()

    out: list[tuple[int, str]] = []
    for i, title in enumerate(titles, 1):
        episode = tpl_episode.format(cn_ep=TextUtils.number_to_chinese(i), ep=i, title=title)
        name = tpl_file.format(collection=collection_name, episode=episode, title=title, ep=i)
        out.append((i, name))
    return out


# ─────────────────────────── 单个合集 ───────────────────────────

def rename_collection(project: Project, collection: Collection, *,
                      log: Optional[EventLog] = None,
                      dry_run: bool = False) -> RenameResult:
    """把 `成片/` 里的文件改成正式文件名"""
    name = collection.name

    titles = project.titles_of(name)
    if not titles:
        if log is not None:
            log.emit("rename", FAIL, name, error="titles_missing",
                     message="标题.md 里没有这个合集")
        return RenameResult(name, "fail", error="titles_missing",
                            message=f"标题.md 里没有「{name}」这一节")

    try:
        expected = build_names(project, collection, titles)
    except RenameError as exc:
        if log is not None:
            log.emit("rename", FAIL, name, error=exc.code, message=exc.message)
        return RenameResult(name, "fail", error=exc.code, message=exc.message)

    finals = media.list_videos(collection.final)
    if not finals:
        if log is not None:
            log.emit("rename", FAIL, name, error="no_final_video",
                     message="成片/ 里没有视频")
        return RenameResult(name, "fail", error="no_final_video",
                            message=f"{collection.final} 里没有视频")

    expected_names = [nm for _i, nm in expected]
    by_index = {i: nm for i, nm in expected}
    already = {p.name for p in finals if p.name in expected_names}

    # 需要改名的文件：当前名字不在期望集合里的那些
    to_rename = [p for p in finals if p.name not in expected_names]
    # 还没被占用的期望名
    free = [nm for nm in expected_names if nm not in already]

    # 有编号的按编号对齐 —— **不能按文件名排序**：
    # 中文数字的 Unicode 顺序是 一(4E00) < 三(4E09) < 二(4E8C)，排出来是乱的。
    indexed = sorted((p for p in to_rename if episode_index(p) is not None),
                     key=lambda p: episode_index(p))
    unindexed = sorted(p for p in to_rename if episode_index(p) is None)

    plan: list[tuple[Path, Path]] = []
    renamed: list[tuple[str, str]] = []
    taken: set[str] = set()
    conflicts: list[str] = []
    #: 集数超出标题条数的文件 —— 标题不够，这些注定改不了名
    untitled: list[str] = []

    for path in indexed:
        target_name = by_index.get(episode_index(path))
        if target_name is None:
            # 集数超过标题条数（素材切出的段比标题多）——**不能静默跳过**，
            # 否则 22 个成片里 2 个永远没名字，人还以为全改完了
            untitled.append(path.name)
            continue
        if target_name in taken:
            continue
        if target_name in already:
            # 已经有文件叫这个名字了，而编号文件还想改成它 → 重复内容，报冲突
            conflicts.append(target_name)
            continue
        taken.add(target_name)
        plan.append((path, path.with_name(target_name)))
        renamed.append((path.name, target_name))

    # 剩下的（取不到编号，或编号对不上）按顺序填剩下的空位
    leftovers = [nm for nm in free if nm not in taken]
    for path, target_name in zip(unindexed, leftovers):
        plan.append((path, path.with_name(target_name)))
        renamed.append((path.name, target_name))

    if not plan:
        if log is not None:
            log.emit("rename", SKIP, name, reason="already_named", checked=len(finals),
                     unmatched=untitled or None, finals=len(finals),
                     titles=len(expected_names))
        progress.record(project, name, "命名")
        message = f"{len(finals) - len(untitled)} 个成片名字已经对了"
        if untitled:
            # 别把"2 个根本没名字"也算进"已经对了"
            message += (f"；⚠ 另有 {len(untitled)} 个没有对应标题（标题只有 "
                        f"{len(expected_names)} 条，成片有 {len(finals)} 个）："
                        f"{'、'.join(untitled)}")
        return RenameResult(name, "skip", unmatched=untitled, message=message)

    if dry_run:
        return RenameResult(name, "skip", renamed=renamed,
                            message=f"将要改名 {len(plan)} 个（dry-run 未执行）")

    if conflicts:
        return RenameResult(name, "fail", error="name_conflict",
                            message="成片/ 里有重复内容，目标名已被占用：" + "、".join(sorted(set(conflicts))),
                            renamed=renamed)

    # 先检查冲突，避免改到一半发现撞名
    for _src, dest in plan:
        if dest.exists():
            return RenameResult(name, "fail", error="name_conflict",
                                message=f"目标文件已存在：{dest.name}",
                                renamed=renamed)

    for src, dest in plan:
        src.rename(dest)

    message = f"改名 {len(plan)} 个"
    if untitled:
        message += (f"；⚠ 另有 {len(untitled)} 个没有对应标题（标题只有 "
                    f"{len(expected_names)} 条，成片有 {len(finals)} 个）："
                    f"{'、'.join(untitled)}")
    if log is not None:
        log.emit("rename", DONE, name, count=len(plan), names=[b for _, b in renamed],
                 unmatched=untitled or None, finals=len(finals),
                 titles=len(expected_names))
    progress.record(project, name, "命名")
    return RenameResult(name, "done", renamed=renamed, unmatched=untitled,
                        message=message)


# ─────────────────────────── 批量 ───────────────────────────

def rename_batch(project: Project, collections: Optional[list[str]] = None, *,
                 log: Optional[EventLog] = None,
                 dry_run: bool = False) -> list[RenameResult]:
    if log is None:
        log = EventLog(project.log_dir)
    return [rename_collection(project, c, log=log, dry_run=dry_run)
            for c in project.resolve_collections(collections)]
