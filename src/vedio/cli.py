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
import contextlib
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


#: 结果的出口。在 `main()` 一开头固定住。
#:
#: 为什么需要它：`--quiet` 会把 `sys.stdout` / `sys.stderr` 换成"只写日志文件"的流。
#: 如果结果也走 `sys.stdout`，它会被一起吞掉 —— 那就成了"静音把结论也静没了"。
#: 所以结果永远写这里，而不是当时的 `sys.stdout`。
_RESULT_STREAMS: dict[str, Any] = {"out": None, "err": None, "quiet": False}


def _result_out() -> Any:
    return _RESULT_STREAMS["out"] or sys.stdout


def _result_err() -> Any:
    return _RESULT_STREAMS["err"] or sys.stderr


def _emit_stream() -> Any:
    """结果该写哪个流。

    - 正常模式：写当时的 `sys.stdout` —— 它被 capture 换成了 tee，
      于是结果**既上控制台也进 run-*.log**（"一次调用的全部输出"要完整）。
    - 安静模式：写真实 stdout（`_result_out()`），否则会被只写文件的流吞掉。
    """
    return _result_out() if _RESULT_STREAMS["quiet"] else sys.stdout


def _err_stream() -> Any:
    return _result_err() if _RESULT_STREAMS["quiet"] else sys.stderr


def _quiet_stdout(as_json: bool):
    """把阶段内部的 print 从 stdout 赶走，保证 `--json` 的 stdout 是纯 JSON。

    注意这只是**保 stdout 干净**，不是静音：内容去了 stderr，调用方照样收得到。
    真正的静音是 `--quiet`，见 `EventLog.capture(echo=False)`。
    """
    return contextlib.redirect_stdout(sys.stderr) if as_json else contextlib.nullcontext()


def _log_hint(project: context.Project) -> str:
    """跑完之后告诉人日志在哪。

    用户原来会去翻 `deal_vedio/logs`（旧 logger 在仓库里留的空目录），
    那里永远是空的 —— 真正的日志在批次的 `log/`。不主动说一句就会一直找错地方。
    """
    import re as _re
    from .events import list_logs

    # 通用日志（事件流水）不是"这次运行的过程"，不该抢占"最新"这个名字
    generic = _re.compile(r"^(events\.jsonl|\d{4}-\d{2}-\d{2}\.log)$")
    interesting = [f for f in list_logs(project.log_dir) if not generic.match(f.path.name)]

    detail = f"，最新 {interesting[0].path.name}" if interesting else ""
    return f"\n  日志：{project.log_dir}{detail}\n        （vedio logs 随时回看）"


# ─────────────────────────── 输出 ───────────────────────────

def _emit(payload: dict[str, Any], as_json: bool, renderer: Optional[Callable[[dict], str]] = None) -> None:
    if as_json:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    elif renderer is not None:
        text = renderer(payload)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)

    print(text, file=_emit_stream())
    if _RESULT_STREAMS["quiet"]:
        # 安静模式下这条路径绕过了 capture 的 tee，手动把结果补进日志
        from .events import write_to_captures
        write_to_captures(text + "\n")


def _fail(code: str, message: str, as_json: bool, hint: str = "", **extra: Any) -> int:
    payload = {"error": code, "message": message, **extra}
    if hint:
        payload["hint"] = hint
    stream = _err_stream()
    if as_json:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        print(text, file=stream)
    else:
        text = f"错误：{message}" + (f"\n  {hint}" if hint else "")
        print(text, file=stream)
    if _RESULT_STREAMS["quiet"]:
        from .events import write_to_captures
        write_to_captures(text + "\n")
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

def _add_collections(args: argparse.Namespace, init_stage) -> int:
    """`init --add 合集四,合集五`：给已有批次补建目录 + 进度表追加行"""
    from .events import EventLog

    try:
        project = context.Project.open(args.game, args.batch)
    except context.ContextError as exc:
        return _fail(exc.code, exc.message, args.json, **exc.detail)

    log = EventLog(project.log_dir)
    try:
        with _quiet_stdout(args.json):
            payload = init_stage.add_collections(project, _split_list(args.add) or [], log=log)
    except init_stage.InitError as exc:
        if args.json:
            print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2), file=_result_err())
        else:
            print(f"错误：{exc.message}", file=_result_err())
            if exc.hint:
                print(f"  {exc.hint}", file=_result_err())
        return EXIT_FAIL

    def render(p: dict) -> str:
        lines = [f"批次 {p['name']}：请求加 {len(p['requested'])} 个合集"]
        dirs_note = "" if p["created_dirs"] else "（都已存在）"
        lines.append(f"  目录：新建 {p['created_dirs']} 个{dirs_note}")
        if p["added"]:
            lines.append(f"  进度表：新增 {len(p['added'])} 行 —— {'、'.join(p['added'])}")
        if p["already_present"]:
            lines.append(f"  进度表：这些行本来就在，没动 —— {'、'.join(p['already_present'])}")
        if p["progress_rebuilt"]:
            lines.append("  ⚠ 原进度表解析不了，已备份为 .bak 并重建")
        if p["collections_field"]:
            lines.append(f"  game.yaml 的 collections 已更新为 {p['collections_field']}")
        lines.append(f"  进度表文件：{p['progress_file']}")
        lines.append("")
        lines.append("下一步：把录屏放进新合集的 素材/，然后照常往下走。")
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK


def cmd_export(args: argparse.Namespace, project: context.Project) -> int:
    """批量导出草稿（会点剪映，耗时最长）"""
    from . import space
    from .events import EventLog
    from .stages import export as export_stage

    log = EventLog(project.log_dir)

    # ── 导出前把「导出 + 拼接」一起算 ──
    # 只算导出是不够的：实测导出顺利、花 5 分钟写满 2.8 GB，然后卡在拼接上。
    # 拼接才是吃空间的大头，所以必须一起算 —— 不够就别开始导。
    if not getattr(args, "ignore_space", False):
        try:
            report = space.project_batch(project, _split_list(args.collections),
                                         ["export", "splice"])
        except Exception:
            report = None
        if report is not None and not report["enough"]:
            text = space.render(report)
            if args.json:
                payload = {"ok": False, "error": "disk_full", "space": report,
                           "message": f"导出+拼接共需 {space.gb(report['total'])}，"
                                      f"只剩 {space.gb(report['free'])}"}
                print(json.dumps(payload, ensure_ascii=False, indent=2), file=_result_err())
            else:
                print("磁盘空间不够，先不导出（否则导完也拼不了）：\n" + text, file=_result_err())
                print("  打算先导出、之后再腾空间 → 加 --ignore-space", file=_result_err())
            return EXIT_FAIL
        if report is not None and not args.json:
            # 够也要说出来 —— 否则"预检到底跑没跑"只能靠猜
            print(space.render(report))

    with _quiet_stdout(args.json):
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
        lines.append(_log_hint(project))
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK if batch.ok else EXIT_FAIL


# ─────────────────────────── 动词：init ───────────────────────────

def cmd_init(args: argparse.Namespace, project: Optional[context.Project]) -> int:
    """建批次（不需要先有批次，所以不打开 project）；`--add` 给已有批次加合集"""
    from .stages import init as init_stage

    # 用 `is not None` 而不是真值判断：`--add ""` 是"给了但为空"，
    # 该报"没有指定合集"，而不是掉进正常的建批次分支。
    if args.add is not None:
        return _add_collections(args, init_stage)

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
            # 和其它动词一样：一次调用留一个 run-*.log
            with log.capture("run-init"):
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
            with _quiet_stdout(args.json):
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
        lines.append(_log_hint(project))
        return "\n".join(lines) or "  （没有要做的）"

    _emit(payload, args.json, render)
    return EXIT_OK if payload["ok"] else EXIT_FAIL


# ─────────────────────────── 动词：splice ───────────────────────────

def cmd_splice(args: argparse.Namespace, project: context.Project) -> int:
    """切分长片并拼片头片尾"""
    from .events import EventLog
    from .stages import splice as splice_stage

    log = EventLog(project.log_dir)
    with _quiet_stdout(args.json):
        results = splice_stage.splice_batch(project, _split_list(args.collections),
                                            log=log, force=args.force)
    payload = {
        "ok": all(r.ok for r in results),
        "results": [r.as_dict() for r in results],
    }

    def render(p: dict) -> str:
        lines = []
        for r in p["results"]:
            mark = {"done": "✓", "skip": "·", "fail": "✗"}.get(r["status"], "?")
            lines.append(f"  {mark} {r['collection']}  {r['message']}")
        lines.append(_log_hint(project))
        return "\n".join(lines) or "  （没有要做的）"

    _emit(payload, args.json, render)
    return EXIT_OK if payload["ok"] else EXIT_FAIL


# ─────────────────────────── 动词：rename / ledger / run ───────────────────────────

def cmd_rename(args: argparse.Namespace, project: context.Project) -> int:
    """按 标题.md 给成片改名"""
    from .events import EventLog
    from .stages import rename as rename_stage

    log = EventLog(project.log_dir)
    with _quiet_stdout(args.json):
        results = rename_stage.rename_batch(project, _split_list(args.collections),
                                            log=log, dry_run=args.dry_run)
    payload = {"ok": all(r.ok for r in results), "results": [r.as_dict() for r in results]}

    def render(p: dict) -> str:
        lines = []
        for r in p["results"]:
            mark = {"done": "✓", "skip": "·", "fail": "✗"}.get(r["status"], "?")
            lines.append(f"  {mark} {r['collection']}  {r['message']}")
            if args.dry_run:
                for item in r["renamed"][:3]:
                    lines.append(f"      {item['from']} → {item['to']}")
        return "\n".join(lines) or "  （没有要做的）"

    _emit(payload, args.json, render)
    return EXIT_OK if payload["ok"] else EXIT_FAIL


def cmd_ledger(args: argparse.Namespace, project: context.Project) -> int:
    """生成台账 Excel"""
    from .events import EventLog
    from .stages import ledger as ledger_stage

    log = EventLog(project.log_dir)
    with _quiet_stdout(args.json):
        result = ledger_stage.build_ledger(project, _split_list(args.collections),
                                           log=log, force=args.force)
    payload = result.as_dict()

    def render(p: dict) -> str:
        mark = {"done": "✓", "skip": "·", "fail": "✗"}.get(p["status"], "?")
        return f"  {mark} {p['message']}\n    台账：{p['path']}"

    _emit(payload, args.json, render)
    return EXIT_OK if result.ok else EXIT_FAIL


def cmd_run(args: argparse.Namespace, project: context.Project) -> int:
    """按步骤推进（可夜里跑）"""
    from .events import EventLog
    from . import space
    from .stages import run as run_stage

    steps = _split_list(args.steps)
    log = EventLog(project.log_dir)

    # ── 整轮空间预检 ──
    # 各环节自己预检是"各管各的"：导出够、拼接不够 → 先花 5 分钟导出、
    # 写满 2.8 GB，然后卡在拼接上。这里一次算总账，不够就根本不开跑。
    try:
        report = space.project_batch(project, _split_list(args.collections), steps)
    except Exception:
        report = None
    if report is not None and not report["enough"]:
        text = space.render(report)
        if args.json:
            payload = {"ok": False, "error": "disk_full", "space": report,
                       "message": f"整轮需要 {space.gb(report['total'])}，"
                                  f"只剩 {space.gb(report['free'])}"}
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=_result_err())
        else:
            print("磁盘空间不够，这一轮不开跑：\n" + text, file=_result_err())
        return EXIT_FAIL

    try:
        with _quiet_stdout(args.json):
            report = run_stage.run(project, steps, _split_list(args.collections), log=log)
    except ValueError as exc:
        return _fail("bad_step", str(exc), args.json)

    payload = report.as_dict()

    def render(p: dict) -> str:
        lines = [f"跑 {len(p['steps'])} 步 × {len(p['collections'])} 合集："
                 f"{'全部成功' if p['ok'] else '有失败'}"]
        for r in p["results"]:
            mark = "✓" if r["ok"] else "✗"
            lines.append(f"  {mark} {r['collection']:<8}{r['step']:<9}{r['message']}")
        lines.append(_log_hint(project))
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK if report.ok else EXIT_FAIL


# ─────────────────────────── 动词：series ───────────────────────────

def cmd_series(args: argparse.Namespace, project: context.Project) -> int:
    """给一组合集定「篇名 + 上下篇」（rename 的前置）"""
    from .events import EventLog
    from .stages import series as series_stage

    log = EventLog(project.log_dir)
    with _quiet_stdout(args.json):
        result = series_stage.apply(project, args.groups, log=log, force=args.force)
    payload = result.as_dict()

    def render(p: dict) -> str:
        mark = {"done": "✓", "skip": "·", "fail": "✗"}.get(p["status"], "?")
        lines = [f"  {mark} {p['message']}"]
        for name, subtitle in p["assignments"].items():
            lines.append(f"      {name} → {subtitle}")
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK if result.ok else EXIT_FAIL


# ─────────────────────────── 动词：logs ───────────────────────────

def cmd_logs(args: argparse.Namespace, project: context.Project) -> int:
    """看批次日志（只读）"""
    from .events import list_logs, tail_log

    # 排除本次调用自己的 run 日志：它正在写，而且内容就是你眼前这份列表
    own = f"run-{args.verb}"
    files = [f for f in list_logs(project.log_dir, args.collection)
             if not f.path.name.startswith(own + "-")]
    payload = {
        "log_dir": str(project.log_dir),
        "count": len(files),
        "files": [f.as_dict() for f in files],
    }
    if args.tail and files:
        payload["tail"] = {"file": files[0].path.name,
                           "content": tail_log(files[0].path, args.tail)}

    def render(p: dict) -> str:
        if not p["count"]:
            return f"  {p['log_dir']} 里还没有日志"
        lines = [f"  {p['log_dir']}（{p['count']} 个文件，最新在前）"]
        for f in p["files"][:20]:
            lines.append(f"    {f['size']:>9,} B  {f['modified']}  {f['name']}")
        if p["count"] > 20:
            lines.append(f"    …还有 {p['count'] - 20} 个")
        if "tail" in p:
            lines.append("")
            lines.append(f"  ── {p['tail']['file']} 最后几行 ──")
            lines.append(p["tail"]["content"])
        return "\n".join(lines)

    _emit(payload, args.json, render)
    return EXIT_OK


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
        p.add_argument("--json", action="store_true", help="输出结构化 JSON（并自动 --quiet）")
        p.add_argument("--quiet", action="store_true",
                       help="过程只写日志文件，控制台只留结论（agent 调用时用）")

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
    p_export.add_argument("--ignore-space", action="store_true",
                          help="跳过「导出+拼接」空间预检（打算先导、之后再腾空间时用）")
    p_export.set_defaults(handler=cmd_export)

    p_init = sub.add_parser("init", help="建批次（不需要批次已存在）")
    add_common(p_init)
    p_init.add_argument("--collections", type=int, default=1, help="建几个合集，默认 1")
    p_init.add_argument("--host", help="主播名，进 meta.host（命名模板与台账都要用）")
    p_init.add_argument("--set", action="append", metavar="键=值",
                        help="覆盖规则里的一项，如 --set duration.episode_body=450；可重复")
    p_init.add_argument("--dry-run", action="store_true", help="只算不建")
    p_init.add_argument("--add", metavar="合集四,合集五",
                        help="给已有批次补建这些合集（不动已有的）")
    p_init.set_defaults(handler=cmd_init, needs_project=False)

    p_sub = sub.add_parser("subtitle", help="字幕三步：加行号 / 纠错 / 回写 srt")
    add_common(p_sub)
    p_sub.add_argument("--collections", help="只做这些合集，逗号分隔；不传=全部")
    p_sub.add_argument("--steps", default="number,correct,patch",
                       help="要跑哪几步，逗号分隔（默认全部）")
    p_sub.add_argument("--prompt", help="纠错提示词（带【主题】可触发知识库）")
    p_sub.add_argument("--force", action="store_true", help="已有产出也重跑")
    p_sub.set_defaults(handler=cmd_subtitle)

    p_splice = sub.add_parser("splice", help="切分长片并拼片头片尾（会跑 ffmpeg）")
    add_common(p_splice)
    p_splice.add_argument("--collections", help="只做这些合集，逗号分隔；不传=全部")
    p_splice.add_argument("--force", action="store_true", help="已有成片也重做")
    p_splice.set_defaults(handler=cmd_splice)

    p_rename = sub.add_parser("rename", help="按 标题.md 给成片改名")
    add_common(p_rename)
    p_rename.add_argument("--collections", help="只做这些合集，逗号分隔；不传=全部")
    p_rename.add_argument("--dry-run", action="store_true", help="只列出要改什么，不动文件")
    p_rename.set_defaults(handler=cmd_rename)

    p_ledger = sub.add_parser("ledger", help="生成台账 Excel")
    add_common(p_ledger)
    p_ledger.add_argument("--collections", help="只写这些合集，逗号分隔；不传=全部")
    p_ledger.add_argument("--force", action="store_true", help="已有台账也重写")
    p_ledger.set_defaults(handler=cmd_ledger)

    p_run = sub.add_parser("run", help="按步骤推进（可夜里跑）")
    add_common(p_run)
    p_run.add_argument("--collections", help="只跑这些合集，逗号分隔；不传=全部")
    p_run.add_argument("--steps", default=",".join(run_step_names()),
                       help="要跑的步骤，逗号分隔")
    p_run.set_defaults(handler=cmd_run)

    p_series = sub.add_parser("series", help="给一组合集定「篇名 + 上下篇」（rename 前置）")
    add_common(p_series)
    p_series.add_argument("--groups", required=True,
                          help="分组写法：合集一,合集二=篇名;合集三=另一篇名")
    p_series.add_argument("--force", action="store_true", help="副标题一样也重写")
    p_series.set_defaults(handler=cmd_series)

    p_logs = sub.add_parser("logs", help="看批次日志（只读）")
    add_common(p_logs)
    p_logs.add_argument("--collection", help="只看文件名里含这个合集名的日志")
    p_logs.add_argument("--tail", type=int, nargs="?", const=40, metavar="行数",
                        help="顺带打印最新那个日志的末尾（默认 40 行）")
    p_logs.set_defaults(handler=cmd_logs)

    return parser


def run_step_names() -> list[str]:
    """给 --steps 的默认值和 help 用（避免和 run 模块的常量各写一份）"""
    from .stages.run import ALL_STEPS
    return list(ALL_STEPS)


def _ensure_utf8_stdio() -> None:
    """控制台是 GBK 时，表格里的 emoji 会让 print 直接抛 UnicodeEncodeError。

    `vedio.bat` 靠 `chcp 65001` 规避，但直接 `python vedio.py ...` 没有这一步。
    这里统一把 stdio 钉成 UTF-8，转义不了的字符降级成替换字符而不是崩。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _run_with_log(args: argparse.Namespace, project: context.Project,
                  handler: Callable) -> int:
    """把**一次命令调用的全部输出**存成一个文件。

    用户要的是"跑一次命令，就有一个文件能看"，而不是去猜日志散在哪。
    所以每次调用生成一个：

        {批次}/log/run-{动词}-{时间}.log

    里面包含这次调用印到控制台的**全部**内容 —— 包括 stage 内部那些
    旧代码的 print、剪映控制器的过程、模型流式回复、最终结果表。

    实现方式是最外层的 `EventLog.capture()`：它把 stdout/stderr 换成 tee，
    内层 stage 自己的 capture 会再套一层，于是同一份内容既进
    `run-*.log`（整次调用），也进 `agent-subtitle-*.log`（单个合集）。
    多写几 KB，换"永远找得到"。

    **`--quiet` / `--json` 时改为 `echo=False`**：过程只进文件，控制台只留结论。
    这是给 agent 用的 —— agent 的"工具结果"就是 stdout/stderr 文本，
    过程打多少它就收多少，单次 2 小时字幕能到两千多行。
    """
    from .events import EventLog

    try:
        elog = EventLog(project.log_dir)
    except OSError:
        return handler(args, project)          # 日志目录建不了也不能让命令跑不了

    # --json 是机器模式，默认就该安静；--quiet 是显式要求。
    quiet = bool(getattr(args, "quiet", False) or getattr(args, "json", False))
    _RESULT_STREAMS["quiet"] = quiet

    with elog.capture(f"run-{args.verb}", echo=not quiet):
        try:
            return handler(args, project)
        except context.ContextError:
            # 业务错（批次不存在、合集名不对…）由 main 统一转成带 error 码的输出。
            # 不能在这里打 traceback —— 那会把 --json 的 stderr 弄成"栈 + JSON"，解析不了。
            raise
        except Exception:
            # 意外崩溃的 traceback 是最该留下的东西 —— 在 tee 还生效时打一遍
            import traceback
            traceback.print_exc()
            raise


def main(argv: Optional[list[str]] = None) -> int:
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    # 结果出口在这里固定住。--quiet 之后 sys.stdout/stderr 会被换成"只写文件"的流，
    # 结果若跟着走就会被一起吞掉 —— 那就成了"静音把结论也静没了"。
    _RESULT_STREAMS["out"] = sys.stdout
    _RESULT_STREAMS["err"] = sys.stderr
    _RESULT_STREAMS["quiet"] = False
    try:
        return _main(args, parser)
    finally:
        _RESULT_STREAMS["out"] = _RESULT_STREAMS["err"] = None
        _RESULT_STREAMS["quiet"] = False


def _main(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    as_json = getattr(args, "json", False)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(_result_err())
        return EXIT_USAGE

    # init 是"建批次"，此时批次还不存在 —— 不能先 Project.open
    project: Optional[context.Project] = None
    if getattr(args, "needs_project", True):
        try:
            project = context.Project.open(args.game, args.batch)
        except context.ContextError as exc:
            return _fail(exc.code, exc.message, as_json, **exc.detail)

    try:
        if project is not None:
            return _run_with_log(args, project, handler)
        return handler(args, project)
    except context.ContextError as exc:
        return _fail(exc.code, exc.message, as_json, **exc.detail)


if __name__ == "__main__":
    raise SystemExit(main())
