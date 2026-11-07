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


# ─────────────────────────── 动词：init ───────────────────────────

def cmd_init(args: argparse.Namespace, project: Optional[context.Project]) -> int:
    """建批次（不需要先有批次，所以不打开 project）"""
    from .stages import init as init_stage

    overrides: dict[str, Any] = {}
    for item in (args.set or []):
        if "=" not in item:
            return _fail("bad_override", f"--set 要写成 键=值，收到 {item!r}", args.json)
        key, _, raw = item.partition("=")
        overrides[key.strip()] = _parse_scalar(raw.strip())

    try:
        plan = init_stage.build_plan(
            args.game, args.batch,
            collections=args.collections,
            host=args.host or "",
            overrides=overrides,
        )
        if args.dry_run:
            payload = {"ok": True, "dry_run": True, **plan.as_dict()}
        else:
            from .events import EventLog
            log = EventLog(plan.batch_dir / "log")
            payload = init_stage.apply(plan, log=log)
    except init_stage.InitError as exc:
        if args.json:
            print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"错误：{exc.message}", file=sys.stderr)
            if exc.hint:
                print(f"  {exc.hint}", file=sys.stderr)
        return EXIT_FAIL

    def render(p: dict) -> str:
        verb = "将要创建" if p.get("dry_run") else "已创建"
        lines = [f"{verb}批次 {p['name']}（{p['collections']} 合集）",
                 f"  目录  {p['batch_dir']}"]
        if p.get("dry_run"):
            for d in p["dirs"]:
                lines.append(f"    + {d}")
            for f in p["files"]:
                lines.append(f"    + {f}")
        else:
            lines.append(f"  新建目录 {p.get('created_dirs', 0)} 个")
        lines.append("")
        lines.append("下一步：把录屏放进 合集/合集X/素材/，录完跟我说一声。")
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK


def _parse_scalar(raw: str) -> Any:
    """把 `--set duration.episode_body=450` 的值转成合适的类型"""
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", ""):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


# ─────────────────────────── 动词：subtitle ───────────────────────────

def cmd_subtitle(args: argparse.Namespace, project: context.Project) -> int:
    """字幕三步：加行号 / 纠错 / 回写 srt"""
    from .events import EventLog
    from .stages import subtitle as sub_stage

    steps = _split_list(args.steps) or ["number", "correct", "patch"]
    log = EventLog(project.log_dir)

    results = []
    try:
        targets = project.resolve_collections(_split_list(args.collections))
    except context.ContextError as exc:
        return _fail(exc.code, exc.message, args.json, **exc.detail)

    for collection in targets:
        try:
            results.extend(sub_stage.run(project, collection, steps=steps, log=log,
                                         prompt=args.prompt, force=args.force))
        except ValueError as exc:
            return _fail("bad_step", str(exc), args.json)

    payload = {
        "ok": all(r.ok for r in results),
        "results": [r.as_dict() for r in results],
    }

    def render(p: dict) -> str:
        lines = []
        for r in p["results"]:
            mark = {"done": "✓", "skip": "·", "fail": "✗"}.get(r["status"], "?")
            lines.append(f"  {mark} {r['collection']}  {r['step']:<8}{r['message']}")
        return "\n".join(lines) or "  （没有要做的）"

    _emit(payload, args.json, render)
    return EXIT_OK if payload["ok"] else EXIT_FAIL


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

    p_init = sub.add_parser("init", help="建批次（不需要批次已存在）")
    add_common(p_init)
    p_init.add_argument("--collections", type=int, default=1, help="建几个合集，默认 1")
    p_init.add_argument("--host", help="主播名，进 meta.host（命名模板与台账都要用）")
    p_init.add_argument("--set", action="append", metavar="键=值",
                        help="覆盖规则里的一项，如 --set duration.episode_body=450；可重复")
    p_init.add_argument("--dry-run", action="store_true", help="只算不建")
    p_init.set_defaults(handler=cmd_init, needs_project=False)

    p_sub = sub.add_parser("subtitle", help="字幕三步：加行号 / 纠错 / 回写 srt")
    add_common(p_sub)
    p_sub.add_argument("--collections", help="只做这些合集，逗号分隔；不传=全部")
    p_sub.add_argument("--steps", default="number,correct,patch",
                       help="要跑哪几步，逗号分隔（默认全部）")
    p_sub.add_argument("--prompt", help="纠错提示词（带【主题】可触发知识库）")
    p_sub.add_argument("--force", action="store_true", help="已有产出也重跑")
    p_sub.set_defaults(handler=cmd_subtitle)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    as_json = getattr(args, "json", False)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    # init 是"建批次"，此时批次还不存在 —— 不能先 Project.open
    project: Optional[context.Project] = None
    if getattr(args, "needs_project", True):
        try:
            project = context.Project.open(args.game, args.batch)
        except context.ContextError as exc:
            return _fail(exc.code, exc.message, as_json, **exc.detail)

    try:
        return handler(args, project)
    except context.ContextError as exc:
        return _fail(exc.code, exc.message, as_json, **exc.detail)


if __name__ == "__main__":
    raise SystemExit(main())
