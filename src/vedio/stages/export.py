# -*- coding: utf-8 -*-
"""vedio.stages.export —— 批量导出剪映草稿

流程（沿用 `export_draft.py` 那套已跑通的做法，只补三件事）：

    1. 从 `合集清单.yaml` 查这个合集对应哪个草稿（**人工命名，程序不解析**）
    2. 点开草稿 → 设分辨率/帧率 → 点导出 → 等完成
    3. 剪映默认导出到 `%USERPROFILE%\\Videos`，之后 move 到 `剪辑/`

补的三件事：
- 路径从 `context` 来，不再改 config 字典
- 每步写 `events.jsonl`（含实测秒数，将来能反推超时该设多少）
- 已导出过的跳过（可 `--force` 重导），避免夜间重跑时白导一遍

不做的：
- **不设导出路径** —— 6.0.1 上那个控件是 QQuickText，没有 ValuePattern，
  SetValue 无效。只能默认路径 + move。
- **不改导出参数以外的设置** —— 也读不到当前值，只能"点开下拉选指定项"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Callable, Optional

from .. import context, media
from .. import progress
from ..context import Collection, Project
from ..events import DONE, FAIL, SKIP, EventLog

#: 默认导出超时（秒）。会被 `game.yaml` 的 `export.timeout_seconds` 覆盖。
DEFAULT_TIMEOUT = 10800.0


@dataclass
class ExportResult:
    """一个合集的导出结果"""

    collection: str
    status: str                       # done / skip / fail
    draft: Optional[str] = None
    target: Optional[Path] = None
    seconds: float = 0.0
    error: Optional[str] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skip")

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "status": self.status,
            "draft": self.draft,
            "target": str(self.target) if self.target else None,
            "seconds": round(self.seconds, 1),
            "error": self.error,
            "message": self.message,
        }


@dataclass
class ExportBatch:
    results: list[ExportResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total": len(self.results),
            "done": sum(1 for r in self.results if r.status == "done"),
            "skipped": sum(1 for r in self.results if r.status == "skip"),
            "failed": sum(1 for r in self.results if r.status == "fail"),
            "results": [r.as_dict() for r in self.results],
        }


# ─────────────────────────── 参数映射 ───────────────────────────

def _enum_by_value(enum_cls, value: str):
    """`"1080P"` → `ExportResolution.RES_1080P`；对不上返回 None（不改变剪映设置）"""
    if not value:
        return None
    target = value.strip().lower()
    for member in enum_cls:
        if str(member.value).lower() == target:
            return member
    return None


def export_params(project: Project, enums: dict) -> dict[str, Any]:
    """从 `game.yaml` 的 `export` 段取要"点开下拉选"的两项。

    只有这两项能通过界面控制；码率/编码/格式是剪映自己的下拉项，
    读过不到当前值也点不准，靠人第一次配好。

    `export.apply_params: false` 时两项都返回 None —— 一个都不设。
    为什么需要它：实测 6.0.1 的分辨率/帧率下拉**选项项在 UIA 里不可见**
    （主窗口整棵树只有 18 个控件），程序点不到。硬试的话每个合集白等 60 秒
    还折腾界面。关掉之后靠 `check_video_params()` 事后用 ffprobe 核对产物。
    """
    if project.rule("export.apply_params", True) is False:
        return {"resolution": None, "framerate": None}
    return {
        "resolution": _enum_by_value(enums["resolution"],
                                     str(project.rule("export.resolution", "") or "")),
        "framerate": _enum_by_value(enums["framerate"],
                                    str(project.rule("export.framerate", "") or "")),
    }


def export_timeout(project: Project) -> float:
    try:
        value = float(project.rule("export.timeout_seconds", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


# ─────────────────────────── 已导出检测 ───────────────────────────

def existing_export(project: Project, collection: Collection) -> tuple[Optional[Path], float]:
    """`剪辑/` 里最长的那条片子。返回 `(路径, 秒数)`。

    只要目录里有视频文件就返回路径（时长可能是 0，比如探测失败）；
    调用方自己决定"0 秒算不算可用"。
    """
    files = media.list_videos(collection.editing)
    if not files:
        return None, 0.0
    best = files[0]
    best_len = media.probe_duration(project.ffprobe, best)
    for p in files[1:]:
        d = media.probe_duration(project.ffprobe, p)
        if d > best_len:
            best, best_len = p, d
    return best, best_len


#: 配置里的分辨率 → 视频"短边"像素
_RESOLUTION_SHORT_SIDE = {
    "8K": 4320, "4K": 2160, "2K": 1440, "1080P": 1080, "720P": 720, "480P": 480,
}


def check_video_params(project: Project, info: dict) -> list[str]:
    """核对导出的产物是否符合 `game.yaml` 的 `export` 配置。

    为什么要有这一步：剪映 6.0.1 的分辨率/帧率下拉**没法用程序选**
    （选项项在 UIA 里不可见，实测点开 30 秒也搜不到）。所以配置里写的
    `1080P` 只能"尽力而为"。真正的把关放在这里 —— 读产物的实际值来比。

    Returns:
        不符合项的人话描述；全部符合或读不到信息时返回空列表。
    """
    if not info:
        return ["读不到产物的分辨率/帧率，没法核对（可用 ffprobe 手动查）"]

    problems: list[str] = []
    want = str(project.rule("export.resolution", "") or "").strip().upper()
    expected_side = _RESOLUTION_SHORT_SIDE.get(want)
    if expected_side:
        actual_side = min(info["width"], info["height"])
        if actual_side != expected_side:
            problems.append(f"分辨率要求 {want}（短边 {expected_side}），实际 {actual_side}")

    want_fps = str(project.rule("export.framerate", "") or "").strip().lower()
    if want_fps.endswith("fps"):
        try:
            expected_fps = float(want_fps[:-3])
        except ValueError:
            expected_fps = 0.0
        if expected_fps and abs(info["fps"] - expected_fps) > 0.5:
            problems.append(f"帧率要求 {want_fps}，实际 {info['fps']:g}fps")

    return problems


# ─────────────────────────── 单个合集 ───────────────────────────

def export_collection(project: Project, collection: Collection, controller=None,
                      *, log: Optional[EventLog] = None,
                      force: bool = False,
                      enums: Optional[dict] = None,
                      controller_factory: Optional[Callable[[], Any]] = None
                      ) -> ExportResult:
    """导出一个合集。

    Args:
        controller: 已构造好的控制器（测试注入用）
        controller_factory: 延迟构造；**只有真要导出时才调用** ——
            草稿没登记或已经导出过时不该去碰剪映
        force: True 则即使已经导出过也重导
    """
    name = collection.name
    draft = project.draft_for(name)
    target_dir = collection.editing

    # ── 1. 草稿登记 ──
    if not draft:
        available = project.available_drafts()
        hint = ("剪映里当前有：" + "、".join(available)) if available else "剪映里没读到任何草稿"
        return ExportResult(
            collection=name, status="fail", error="draft_not_found",
            message=f"合集清单.yaml 里没有为「{name}」登记草稿名。{hint}",
        )

    # ── 2. 已导出则跳过 ──
    if not force:
        path, seconds = existing_export(project, collection)
        if path is not None and seconds > 0:
            if log is not None:
                log.emit("export", SKIP, name, reason="already_exported",
                         file=path.name, seconds=round(seconds, 1))
            progress.record(project, name, "导出")
            return ExportResult(collection=name, status="skip", draft=draft,
                                target=path, seconds=seconds,
                                message=f"剪辑/ 里已有 {path.name}（{media.hhmmss(seconds)}）")

    # ── 3. 调控制器 ──
    if controller is None:
        if controller_factory is None:
            from jianying_export import JianyingController
            controller = JianyingController()
        else:
            controller = controller_factory()

    if enums is None:
        from jianying_export import ExportFramerate, ExportResolution
        enums = {"resolution": ExportResolution, "framerate": ExportFramerate}
    params = export_params(project, enums)
    timeout = export_timeout(project)

    log_file: Optional[Path] = None
    try:
        if log is not None:
            log.emit("export", "start", name, draft=draft, target=str(target_dir),
                     resolution=getattr(params["resolution"], "value", None),
                     framerate=getattr(params["framerate"], "value", None),
                     timeout=timeout)
        import time
        started = time.time()
        # 控制器一路 print 找控件、等面板、等文件稳定的过程 —— 导出失败时唯一能看的线索
        if log is not None:
            with log.capture("export", name) as log_file:
                controller.export_draft(
                    draft, str(target_dir),
                    resolution=params["resolution"],
                    framerate=params["framerate"],
                    timeout=timeout,
                )
        else:
            controller.export_draft(
                draft, str(target_dir),
                resolution=params["resolution"],
                framerate=params["framerate"],
                timeout=timeout,
            )
        elapsed = time.time() - started
    except Exception as exc:                 # noqa: BLE001 - 任何失败都要落成结果，不中断整批
        if log is not None:
            log.emit("export", FAIL, name, error=type(exc).__name__, message=str(exc),
                     log_file=log_file.name if log_file else None)
        return ExportResult(collection=name, status="fail", draft=draft,
                            error=type(exc).__name__, message=str(exc))

    path, seconds = existing_export(project, collection)
    if path is None:
        # 控制器没抛异常，但目标目录里没有片子 —— 可能是 move 失败或被别的东西删了。
        # 这种情况必须报失败，不能记成功：正是"整段搬运静默失效"那类 bug。
        if log is not None:
            log.emit("export", FAIL, name, error="export_file_missing",
                     message=f"控制器返回成功，但 {target_dir} 里没有新片",
                     log_file=log_file.name if log_file else None)
        return ExportResult(collection=name, status="fail", draft=draft,
                            target=target_dir, error="export_file_missing",
                            message=f"控制器返回成功，但 {target_dir} 里没有片子")

    # 核对参数：剪映的分辨率下拉没法程序选，只能事后验产物
    info = media.probe_video_info(project.ffprobe, path)
    warnings = check_video_params(project, info)

    if log is not None:
        log.emit("export", DONE, name, seconds=round(elapsed, 1),
                 file=path.name, video_seconds=round(seconds, 1),
                 actual=media.describe_video_info(info) or None,
                 param_warnings=warnings or None,
                 log_file=log_file.name if log_file else None)
    message = f"导出完成（{media.hhmmss(elapsed)}"
    actual = media.describe_video_info(info)
    if actual:
        message += f"，{actual}"
    message += "）"
    if warnings:
        # 不判失败：片子确实导出来了，只是参数存疑。但要大声说，
        # 别让人以为"成功"就一定对。
        message += "；⚠ 参数与配置不符：" + "；".join(warnings)
    progress.record(project, name, "导出")
    return ExportResult(collection=name, status="done", draft=draft,
                        target=path, seconds=elapsed, message=message)


# ─────────────────────────── 批量 ───────────────────────────

def export_drafts(project: Project, collections: Optional[list[str]] = None,
                  *, log: Optional[EventLog] = None,
                  force: bool = False,
                  controller: Any = None,
                  controller_factory: Optional[Callable[[], Any]] = None,
                  enums: Optional[dict] = None) -> ExportBatch:
    """批量导出。

    一个合集失败**不中断整批** —— 记事件后继续下一个，这正是夜间无人值守
    该有的行为（旧实现在第一个异常上就整体退出）。

    Args:
        controller: 已构造好的控制器（测试注入用）
        controller_factory: 延迟构造控制器；默认 `JianyingController()`
    """
    if log is None:
        log = EventLog(project.log_dir)

    if controller is None and controller_factory is None:
        def controller_factory():
            from jianying_export import JianyingController
            return JianyingController()

    targets = project.resolve_collections(collections)
    batch = ExportBatch()
    pause = _pause_between(project)
    for index, c in enumerate(targets):
        if index and pause > 0:
            # 旧实现（export_draft.py）里有 PAUSE_BETWEEN = 10 秒，移植时丢了。
            # 丢了之后实测：合集一刚写完 1.33 GB（21:40:02），合集二 8 秒后
            # 就接着点「导出」，剪映还在收尾 → 点击被吞、面板不弹。
            print(f"  等 {pause:g} 秒再导下一个（让剪映收拾干净）…")
            time.sleep(pause)
        batch.results.append(
            export_collection(project, c, controller, log=log, force=force,
                              enums=enums, controller_factory=controller_factory)
        )
    return batch


def _pause_between(project: Project) -> float:
    """两个合集之间的间隔（秒），来自 `export.pause_between`，默认 10。"""
    raw = project.rule("export.pause_between", 10)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 10.0
