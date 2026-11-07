# -*- coding: utf-8 -*-
"""vedio.stages.balance —— 匀素材（录制之后、剪辑之前）

为什么它是一个**环节**而不是一个独立小工具：素材比目标多出几分钟时，
剪辑时就会多切出一两段"废篇"。这些废篇会一路污染到台账（多出几行、
甲方看到不存在的集）。在录制之后把它匀掉，是唯一不返工的位置。

**但决策不在这里**：脚本只给两个原子能力 ——

- `check`：每个合集实际多少、目标多少、超出多少。**不含任何建议**
- `move`：把 A 多出来的部分切给 B（关键帧处切、`-c copy`、不重编码）

"该不该匀、匀给谁"由人（或 agent 问过用户之后）决定。见 AGENTS.md §5.1。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from .. import context, media


def _load_balance_module():
    """延迟导入：`src/util/balance.py` 是旧脚本，导入路径不在包内。"""
    import importlib.util
    import sys

    repo_src = Path(__file__).resolve().parent.parent.parent
    path = repo_src / "util" / "balance.py"
    if not path.is_file():
        raise ImportError(f"找不到 {path}")
    name = "vedio_util_balance"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)      # type: ignore[union-attr]
    return module


def check(project: context.Project,
          collections: Optional[Sequence[str]] = None) -> dict[str, Any]:
    """查每个合集的素材是否超出目标。**只报事实，不给建议。**

    Returns:
        {
          "target": 秒, "tolerance": 秒,
          "rows": [{"collection", "seconds", "target", "over"}],
          "ok": bool,          # 全部没超（或刚好在容差内）
        }
    """
    target = float(project.rule("duration.material_per_collection", 0) or 0)
    tol = float(project.rule("duration.segment_tolerance", 3) or 0)
    rows: list[dict[str, Any]] = []
    ok = True

    for c in project.resolve_collections(list(collections) if collections else None):
        seconds = 0.0
        try:
            for video in media.list_videos(c.material):
                seconds += media.probe_duration(project.ffprobe, video)
        except OSError:
            seconds = 0.0
        over = round(seconds - target, 1)
        if over > tol:
            ok = False
        rows.append({
            "collection": c.name,
            "seconds": round(seconds, 1),
            "target": target,
            "over": max(0.0, over),
        })

    return {"target": target, "tolerance": tol, "rows": rows, "ok": ok}


def move(project: context.Project, source: str, target_collection: str,
         apply: bool = False) -> dict[str, Any]:
    """把 `source` 多出来的部分切给 `target_collection`。

    `apply=False` 只报告"打算切多少"，不动文件。
    """
    module = _load_balance_module()
    local = {"workspace": {"root": str(project.batch_dir.parent)},
             "tool": {"ffmpeg": project.ffmpeg, "ffprobe": project.ffprobe}}
    env = module.Env(project.game, project.batch, local,
                     workspace_override=str(project.batch_dir.parent))
    return {"ok": True, "result": module.cmd_move(env, source, target_collection, apply)}


def render(report: dict[str, Any]) -> str:
    """人话版：谁超了多少。"""
    lines = [f"素材核对（目标 {media.hhmmss(report['target'])}"
             f"，容差 ±{report['tolerance']:g} 秒）"]
    for row in report["rows"]:
        gap = row["over"]
        mark = "✓" if gap <= 0 else "⚠"
        tail = "" if gap <= 0 else f"，超出 {media.hhmmss(gap)}"
        lines.append(f"  {mark} {row['collection']}：{media.hhmmss(row['seconds'])}{tail}")
    if not report["ok"]:
        lines.append("  超出的部分会在剪辑时多切出废篇 —— 先匀掉，再往下走。")
    return "\n".join(lines)
