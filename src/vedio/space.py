# -*- coding: utf-8 -*-
"""vedio.space —— 整轮空间预估

**为什么要单独一层**：各环节自己预检是"各管各的"——

    export 预检：我要 1.6 GB，剩 6.2 GB ✅  → 开跑
    export 成功：磁盘剩 3.4 GB
    splice 预检：我要 3.5 GB，剩 3.4 GB ❌  → 卡住

导出花了 5 分钟、写满 2.8 GB，最后发现后面根本跑不下去。
这不是"空间不足"，是**没有提前算总账**。

所以这里做一件事：给定「哪些合集 × 哪些环节」，算出整轮要多少、
还剩多少、够不够，并给出每一步的明细。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

from . import context, media

#: 默认要算的环节顺序
PIPELINE = ("export", "splice", "rename", "ledger")

#: 台账/命名的写盘量可忽略，但仍记一笔，免得明细里缺项显得没算
_SMALL_STAGE_BYTES = 2 * 1024 ** 2


def _free_bytes(path: Path) -> int:
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return -1                     # 查不到用 -1 表示"未知"


def _material_seconds(project: context.Project, collection: context.Collection) -> float:
    seconds = 0.0
    try:
        for video in media.list_videos(collection.material):
            seconds += media.probe_duration(project.ffprobe, video)
    except OSError:
        pass
    if seconds <= 0:
        seconds = float(project.rule("duration.material_per_collection", 0) or 0)
    return seconds


def _long_video_bytes(project: context.Project,
                      collection: context.Collection) -> int:
    """剪辑/ 里那条长片的字节数；还没导出就按导出估算"""
    videos = media.list_videos(collection.editing)
    if videos:
        return max(v.stat().st_size for v in videos)
    from .stages import export as export_stage
    return export_stage.estimate_export_bytes(project, _material_seconds(project, collection))


def estimate_stage(project: context.Project, collection: context.Collection,
                   stage: str) -> int:
    """某个环节在某个合集上要写多少字节（0 = 不占空间或已存在）"""
    if stage == "export":
        # 已经导过就不再占空间
        if media.list_videos(collection.editing):
            return 0
        from .stages import export as export_stage
        return export_stage.estimate_export_bytes(project, _material_seconds(project, collection))

    if stage == "splice":
        existing = media.list_videos(collection.final)
        count = int(project.episode_count)
        if len(existing) >= count:
            return 0
        source = _long_video_bytes(project, collection)
        try:
            tpl = (project.intro_for(collection.name) or Path()).stat().st_size
            tpl += (project.outro_for() or Path()).stat().st_size
        except (OSError, AttributeError):
            tpl = 0
        one_segment = source // max(count, 1)
        return int((source + tpl * count + one_segment) * 1.15)

    if stage in ("rename", "ledger"):
        return _SMALL_STAGE_BYTES

    return 0


def project_batch(project: context.Project,
                  collections: Optional[list[str]] = None,
                  steps: Optional[list[str]] = None) -> dict[str, Any]:
    """算整轮的空间账。

    Returns:
        {
          "steps": [...],
          "collections": [{"name": ..., "stages": {stage: bytes}, "total": bytes}],
          "total": bytes,          # 全部环节合计
          "free": bytes,           # 目标盘剩余（-1 = 未知）
          "enough": bool,
          "short": bytes,          # 还差多少（0 = 够）
        }
    """
    steps = list(steps or PIPELINE)
    targets = project.resolve_collections(collections)

    rows: list[dict[str, Any]] = []
    total = 0
    for c in targets:
        per_stage = {s: estimate_stage(project, c, s) for s in steps}
        subtotal = sum(per_stage.values())
        total += subtotal
        rows.append({"name": c.name, "stages": per_stage, "total": subtotal})

    free = _free_bytes(project.batch_dir)
    enough = free < 0 or free >= total
    short = 0 if enough else total - free
    return {
        "steps": steps,
        "collections": rows,
        "total": total,
        "free": free,
        "enough": enough,
        "short": short,
        "drive": f"{Path(project.batch_dir).drive}",
    }


def gb(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB"


#: 环节的中文名（给人看的账目表）
STAGE_LABELS = {
    "export": "导出",
    "splice": "分割拼接",
    "rename": "重命名",
    "ledger": "台账",
}


def render(report: dict[str, Any]) -> str:
    """人话账目：每步占多少、剩多少、够不够、不够差多少。

    刻意按**环节**汇总而不是按合集 —— 用户要判断的是"这一轮还能不能跑"，
    不是"合集二比合集一多占 0.1 GB"。

    用「标签：值」而不是对齐的表格：中文是双宽字符，靠空格对齐换个字体就会歪。
    账目要一眼看懂，不能赌终端排版。
    """
    names = [row["name"] for row in report["collections"]]
    lines = [f"空间预估（{'、'.join(names) or '无合集'}）"]

    by_stage: dict[str, int] = {}
    for row in report["collections"]:
        for stage, size in row["stages"].items():
            by_stage[stage] = by_stage.get(stage, 0) + size
    for stage in report["steps"]:
        label = STAGE_LABELS.get(stage, stage)
        lines.append(f"  {label}：{gb(by_stage.get(stage, 0))}")

    lines.append("  " + "─" * 22)
    lines.append(f"  合计：{gb(report['total'])}")
    if report["free"] < 0:
        lines.append("  当前剩余：查不到（跳过判断）")
        return "\n".join(lines)
    lines.append(f"  当前剩余：{gb(report['free'])}")

    if report["enough"]:
        lines.append(f"  ✅ 够，可以开始（还余 {gb(report['free'] - report['total'])}）")
    else:
        lines.append(f"  ❌ 不够，还差 {gb(report['short'])}")
        lines.append(f"     请清理 {report.get('drive', '目标盘')} 的空间后重试")
    return "\n".join(lines)
