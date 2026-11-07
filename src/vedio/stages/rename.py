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
from ..context import Collection, Project
from ..events import DONE, FAIL, SKIP, EventLog

#: 从 `合集一-03.mp4` 里取集号
_INDEX_RE = re.compile(r"-(\d+)$")


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
            "error": self.error,
            "message": self.message,
        }


# ─────────────────────────── 命名模板 ───────────────────────────

def episode_index(path: Path) -> Optional[int]:
    """从 `合集一-03.mp4` 取 3；取不到返回 None"""
    m = _INDEX_RE.search(Path(path).stem)
    return int(m.group(1)) if m else None


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

    for path in indexed:
        target_name = by_index.get(episode_index(path))
        if target_name is None or target_name in taken:
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
            log.emit("rename", SKIP, name, reason="already_named", checked=len(finals))
        return RenameResult(name, "skip",
                            message=f"{len(finals)} 个成片名字已经对了")

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

    if log is not None:
        log.emit("rename", DONE, name, count=len(plan), names=[b for _, b in renamed])
    return RenameResult(name, "done", renamed=renamed,
                        message=f"改名 {len(plan)} 个")


# ─────────────────────────── 批量 ───────────────────────────

def rename_batch(project: Project, collections: Optional[list[str]] = None, *,
                 log: Optional[EventLog] = None,
                 dry_run: bool = False) -> list[RenameResult]:
    if log is None:
        log = EventLog(project.log_dir)
    return [rename_collection(project, c, log=log, dry_run=dry_run)
            for c in project.resolve_collections(collections)]
