# -*- coding: utf-8 -*-
"""vedio.cli —— 命令行入口

设计约束（照着 `docs/目标架构.md`）：

1. **所有动词只收 `--game` / `--batch` / `--collection`，绝不收路径。**
   路径一律由 `vedio.context` 推导。这条一破，"脚本不认路"的老毛病就回来了。
2. **`--json` 输出结构化结果**，字段名稳定；不解析中文表格。
3. **退出码**：0 = 成功，1 = 业务失败，2 = 用法错误。
   业务失败时 `--json` 会输出 `{"error": code, ...}`，agent 可以分支。
4. 给人看的输出走 stdout；错误走 stderr。

用法::

    vedio paths  --game 我的世界 --batch 2026-12 [--collection 合集一] [--json]
    vedio status --game 我的世界 --batch 2026-12 [--collections 合集一,合集二] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import context
from .stages import status as status_stage

PROG = "vedio"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


# ─────────────────────────── 输出 ───────────────────────────

def _emit(payload: dict[str, Any], as_json: bool, renderer: Optional[Callable[[dict], str]] = None) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif renderer is not None:
        print(renderer(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(code: str, message: str, as_json: bool, hint: str = "", **extra: Any) -> int:
    payload = {"error": code, "message": message, **extra}
    if hint:
        payload["hint"] = hint
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    else:
        print(f"错误：{message}", file=sys.stderr)
        if hint:
            print(f"  {hint}", file=sys.stderr)
    return EXIT_FAIL


def _split_list(value: Optional[str]) -> Optional[list[str]]:
    """`合集一,合集二` → ['合集一', '合集二']；不传 → None（表示全部）"""
    if not value:
        return None
    return [x.strip() for x in value.split(",") if x.strip()]


# ─────────────────────────── 动词：paths ───────────────────────────

def cmd_paths(args: argparse.Namespace, project: context.Project) -> int:
    """输出目录位置（只读）"""
    if args.collection:
        try:
            payload = project.collection(args.collection).as_dict()
        except context.ContextError as exc:
            return _fail(exc.code, exc.message, args.json, **exc.detail)
    else:
        payload = project.as_dict()
        payload["collections_detail"] = [c.as_dict() for c in project.collections()]

    def render(p: dict) -> str:
        if "collection" in p:
            lines = [f"合集 {p['collection']}（第 {p['index']} 个）"]
            for key in ("root", "material", "editing", "final"):
                lines.append(f"  {key:<9}{p[key]}")
            lines.append(f"  draft    {p['draft'] or '（未登记）'}")
            lines.append(f"  subtitle {p['subtitle'] or '（标题.md 里还没有）'}")
            lines.append(f"  fullname {p['full_name'] or '—'}")
            return "\n".join(lines)

        lines = [f"批次 {p['name']}（{len(p['collections'])} 合集：{'、'.join(p['collections']) or '无'}）"]
        for key in ("batch_dir", "rules_file", "manifest_file", "titles_file", "ledger_file",
                    "collections_dir", "intro_dir", "outro_dir", "assets_dir", "glossary_dir",
                    "log_dir"):
            lines.append(f"  {key:<16}{p[key]}")
        lines.append(f"  draft_dir       {p['draft_dir'] or '（未配置，也未自动发现）'}")
        if p["missing_dirs"]:
            lines.append(f"  ⚠ 缺目录        {'、'.join(p['missing_dirs'])}")
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK


# ─────────────────────────── 动词：status ───────────────────────────

def cmd_status(args: argparse.Namespace, project: context.Project) -> int:
    """批次进度表（只读）"""
    from .events import EventLog

    log = EventLog(project.log_dir)
    bs = status_stage.collect(project, log=log, collections=_split_list(args.collections))
    payload = bs.as_dict()

    def render(p: dict) -> str:
        table = status_stage.render(bs)
        return table + "\n\n下一步：\n" + status_stage.render_next(bs)

    _emit(payload, args.json, render)
    return EXIT_OK


# ─────────────────────────── 动词：export ───────────────────────────

def cmd_export(args: argparse.Namespace, project: context.Project) -> int:
    """批量导出草稿（会点剪映，耗时最长）"""
    from .events import EventLog
    from .stages import export as export_stage

    log = EventLog(project.log_dir)
    batch = export_stage.export_drafts(
        project,
        _split_list(args.collections),
        log=log,
        force=args.force,
    )
    payload = batch.as_dict()

    def render(p: dict) -> str:
        lines = [f"导出 {p['total']} 个合集：成功 {p['done']}，跳过 {p['skipped']}，失败 {p['failed']}"]
        for r in p["results"]:
            mark = {"done": "✓", "skip": "·", "fail": "✗"}.get(r["status"], "?")
            detail = r["message"] or ""
            lines.append(f"  {mark} {r['collection']}  {detail}")
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK if batch.ok else EXIT_FAIL


# ─────────────────────────── 参数解析 ───────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="游戏短视频批量生产线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "所有动词只收 --game / --batch / --collection，不收路径 ——\n"
            "路径由 vedio.context 按目录约定推导，不要自己拼。"
        ),
    )
    sub = parser.add_subparsers(dest="verb", required=True, metavar="<动词>")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--game", required=True, help="游戏名，如 我的世界")
        p.add_argument("--batch", required=True, help="批次，如 2026-12")
        p.add_argument("--json", action="store_true", help="输出结构化 JSON")

    p_paths = sub.add_parser("paths", help="看目录在哪（只读）")
    add_common(p_paths)
    p_paths.add_argument("--collection", help="只看某个合集")
    p_paths.set_defaults(handler=cmd_paths)

    p_status = sub.add_parser("status", help="批次进度表（只读）")
    add_common(p_status)
    p_status.add_argument("--collections", help="只看这些合集，逗号分隔；不传=全部")
    p_status.set_defaults(handler=cmd_status)

    p_export = sub.add_parser("export", help="批量导出剪映草稿（会点剪映，耗时长）")
    add_common(p_export)
    p_export.add_argument("--collections", help="只导这些合集，逗号分隔；不传=全部")
    p_export.add_argument("--force", action="store_true",
                          help="即使 剪辑/ 里已有片子也重导")
    p_export.set_defaults(handler=cmd_export)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    as_json = getattr(args, "json", False)
    try:
        project = context.Project.open(args.game, args.batch)
    except context.ContextError as exc:
        return _fail(exc.code, exc.message, as_json, **exc.detail)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        return handler(args, project)
    except context.ContextError as exc:
        return _fail(exc.code, exc.message, as_json, **exc.detail)


if __name__ == "__main__":
    raise SystemExit(main())
