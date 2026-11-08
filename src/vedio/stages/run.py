# -*- coding: utf-8 -*-
"""vedio.stages.run —— 编排：按步骤推进，一个合集失败不拖累其它

两个维度是正交的：

    流程位置：从 `init` 走到底，或从任意环节切入（`--steps`）
    合集范围：一个合集，或本批次任意多个（`--collections`）

所以这里不做"总控脚本"，只把已有能力串起来。前提不是"上一步刚跑过"，
而是"文件状态满足" —— 这正是从中间切入也能成立的原因。

失败策略：
- **单个合集**：某步失败就停这个合集，记事件，继续下一个合集
- **批次级步骤**（`ledger`）：放在最后统一跑，不参与逐合集的循环
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..context import Project
from ..events import DONE, FAIL, SKIP, EventLog

#: 合集级步骤（会逐合集跑）
COLLECTION_STEPS = ("number", "correct", "patch", "export", "splice", "rename")
#: 批次级步骤（整批一次）
BATCH_STEPS = ("ledger",)

ALL_STEPS = COLLECTION_STEPS + BATCH_STEPS


@dataclass
class StepResult:
    collection: str
    step: str
    ok: bool
    status: str = ""
    message: str = ""
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {"collection": self.collection, "step": self.step, "ok": self.ok,
                "status": self.status, "message": self.message, "error": self.error}


@dataclass
class RunReport:
    steps: list[str]
    collections: list[str]
    results: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "steps": self.steps,
            "collections": self.collections,
            "results": [r.as_dict() for r in self.results],
            "failed": [r.as_dict() for r in self.results if not r.ok],
        }


def _call_collection_step(project: Project, collection, step: str, *,
                          log: EventLog, state: dict) -> Any:
    """执行一个合集级步骤，返回该阶段自己的结果对象"""
    if step in ("number", "correct", "patch"):
        from . import subtitle as S
        if step == "number":
            return S.number(project, collection, log=log)
        if step == "correct":
            return S.correct(project, collection, log=log)
        return S.patch(project, collection, log=log)

    if step == "export":
        from . import export as X
        controller = state.get("controller")
        if controller is None:
            from jianying_export import JianyingController
            controller = JianyingController()
            state["controller"] = controller
        return X.export_collection(project, collection, controller, log=log)

    if step == "splice":
        from . import splice as SP
        return SP.splice_collection(project, collection, log=log,
                                    runner=state.get("ffmpeg_runner"))

    if step == "rename":
        from . import rename as R
        return R.rename_collection(project, collection, log=log)

    raise ValueError(f"未知步骤：{step}")


def run(project: Project, steps: Optional[list[str]] = None,
        collections: Optional[list[str]] = None, *,
        log: Optional[EventLog] = None,
        ffmpeg_runner: Optional[Callable] = None) -> RunReport:
    """按步骤推进。

    Args:
        steps: 要跑的步骤；默认全部合用（含 ledger）。未知步骤直接报错。
        collections: 只跑这些合集；None = 全部
        ffmpeg_runner: 仅测试用，透传给 splice
    """
    steps = list(steps) if steps else list(ALL_STEPS)
    unknown = [s for s in steps if s not in ALL_STEPS]
    if unknown:
        raise ValueError(f"未知步骤：{'、'.join(unknown)}（可选：{'、'.join(ALL_STEPS)}）")

    if log is None:
        log = EventLog(project.log_dir)

    targets = project.resolve_collections(collections)
    report = RunReport(steps=steps, collections=[c.name for c in targets])
    state: dict[str, Any] = {"ffmpeg_runner": ffmpeg_runner}

    collection_steps = [s for s in steps if s in COLLECTION_STEPS]
    for collection in targets:
        for step in collection_steps:
            try:
                result = _call_collection_step(project, collection, step,
                                               log=log, state=state)
            except Exception as exc:            # noqa: BLE001 - 任何异常都要落成结果
                log.emit("run", FAIL, collection.name, step=step,
                         error=type(exc).__name__, message=str(exc))
                report.results.append(StepResult(
                    collection.name, step, False, status="fail",
                    error=type(exc).__name__, message=str(exc)))
                break                            # 这个合集停在这里，下一个照跑
            ok = bool(getattr(result, "ok", True))
            report.results.append(StepResult(
                collection.name, step, ok,
                status=str(getattr(result, "status", "")),
                message=str(getattr(result, "message", "")),
                error=getattr(result, "error", None)))
            if not ok:
                break

    # 批次级步骤：整批一次
    for step in (s for s in steps if s in BATCH_STEPS):
        if step == "ledger":
            from . import ledger as L
            try:
                result = L.build_ledger(project, collections, log=log)
            except Exception as exc:            # noqa: BLE001
                log.emit("run", FAIL, step=step, error=type(exc).__name__,
                         message=str(exc))
                report.results.append(StepResult("(批次)", step, False, status="fail",
                                                 error=type(exc).__name__, message=str(exc)))
                continue
            report.results.append(StepResult(
                "(批次)", step, bool(result.ok), status=result.status,
                message=result.message, error=result.error))

    log.emit("run", DONE if report.ok else FAIL,
             steps=steps, collections=report.collections,
             failed=len([r for r in report.results if not r.ok]))
    return report
