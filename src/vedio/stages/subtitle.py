# -*- coding: utf-8 -*-
"""vedio.stages.subtitle —— 字幕三步：加行号 / 纠错 / 回写 srt

三步各自独立、可单独重跑，因为它们的输入输出都是**文件**而不是内存状态：

    剪辑/xx.txt          ──number──>  剪辑/xx_ordered.txt
    剪辑/xx_ordered.txt  ──correct──> 剪辑/corrected.txt  +  标题.md 新增一节
    剪辑/corrected.txt
    剪辑/xx.srt          ──patch───>  剪辑/xx_corrected.srt

为什么拆三步而不是一个大函数：中间产物要能看见、能手改。人发现模型某句改错，
直接改 `corrected.txt` 一行再跑 `patch` 就行，不用重跑 API。

`correct` 复用旧的 LangGraph agent（`deal_video_agent`）—— 它已经跑通过。
本阶段只做两件旧代码没做的事：
    1. 输入输出都锚定在批次的 `剪辑/` 目录（不再吃 `input()` 和写死路径）
    2. 把生成的标题**搬进批次的 `标题.md`**，而不是留在代码仓库的 `titles/`
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .. import subtitles
from ..context import Collection, Project
from ..events import DONE, FAIL, SKIP, EventLog

#: 默认提示词（agent 要求带【】用来抽知识库主题；不带也能跑）
DEFAULT_PROMPT = "本次视频是游戏实况，请按合集主题纠正字幕。"

#: 跑纠错的可注入函数签名： (target_dir, prompt) -> dict
Runner = Callable[[str, str], dict]


# ─────────────────────────── 结果 ───────────────────────────

@dataclass
class SubtitleResult:
    collection: str
    step: str                      # number / correct / patch
    status: str                    # done / skip / fail
    outputs: list[str] = None      # 产出文件（相对路径或名字）
    detail: dict = None
    error: Optional[str] = None
    message: str = ""

    def __post_init__(self) -> None:
        self.outputs = self.outputs or []
        self.detail = self.detail or {}

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skip")

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "step": self.step,
            "status": self.status,
            "outputs": self.outputs,
            "detail": self.detail,
            "error": self.error,
            "message": self.message,
        }


# ─────────────────────────── ① 加行号 ───────────────────────────

def number(project: Project, collection: Collection, *, log: Optional[EventLog] = None,
           force: bool = False) -> SubtitleResult:
    """`剪辑/xx.txt` → `剪辑/xx_ordered.txt`"""
    name = collection.name
    src = subtitles.find_source_txt(collection.editing)
    if src is None:
        return SubtitleResult(name, "number", "fail", error="source_txt_missing",
                              message=f"{collection.editing} 里没有剪映导出的 .txt")
    out = src.with_name(f"{src.stem}_ordered.txt")
    if out.is_file() and not force:
        if log is not None:
            log.emit("subtitle:number", SKIP, name, reason="already_done", file=out.name)
        return SubtitleResult(name, "number", "skip", outputs=[out.name],
                              message=f"已有 {out.name}")

    stats = subtitles.number_file(src, out)
    if log is not None:
        log.emit("subtitle:number", DONE, name, source=src.name, file=out.name,
                 lines=stats["lines"])
    return SubtitleResult(name, "number", "done", outputs=[out.name], detail=stats,
                          message=f"{out.name}（{stats['lines']} 行）")


# ─────────────────────────── ② 纠错 ───────────────────────────

def _default_runner() -> Runner:
    """默认跑旧的 LangGraph agent"""
    def runner(target_dir: str, prompt: str) -> dict:
        from deal_video_agent.agent.subtitle_agent import run_subtitle_agent
        return run_subtitle_agent(target_dir, prompt)
    return runner


def read_agent_titles(project: Project, collection: Collection) -> Optional[list[str]]:
    """从旧 agent 的标题文件里取这个合集的标题。

    旧 agent 把它写在 `src/deal_video_agent/titles/{游戏}-{批次}_titles.md`，
    我们用修好的 `TitlesManager` 读出来（它能正确处理副标题）。
    读不到就返回 None —— 标题是副产品，缺了不该让纠错失败。
    """
    try:
        from deal_video_agent.agent.tools.titles_manager import TitlesManager
    except ImportError:
        return None

    repo = Path(__file__).resolve().parent.parent.parent.parent
    legacy_dir = repo / "src" / "deal_video_agent"
    title_file = legacy_dir / "titles" / f"{project.name}_titles.md"
    if not title_file.is_file():
        return None
    manager = TitlesManager(str(legacy_dir), title_file=f"titles/{project.name}_titles.md",
                            game_name=project.game)
    titles = manager.read_all_titles_list()
    sections = manager._parse_all_collections(manager.title_file.read_text(encoding="utf-8"))
    return sections.get(collection.name) or (titles if collection.name in sections else None)


def correct(project: Project, collection: Collection, *, log: Optional[EventLog] = None,
            runner: Optional[Runner] = None, prompt: Optional[str] = None,
            force: bool = False, titles_writer: Optional[Callable[[list[str]], None]] = None
            ) -> SubtitleResult:
    """跑字幕纠错，产出 `corrected.txt`，并把标题搬进批次的 `标题.md`"""
    name = collection.name

    ordered = subtitles.find_source_txt(collection.editing)
    if ordered is None:
        return SubtitleResult(name, "correct", "fail", error="source_txt_missing",
                              message=f"{collection.editing} 里没有 .txt")

    existing = subtitles.find_corrected(collection.editing)
    if existing is not None and not force:
        if log is not None:
            log.emit("subtitle:correct", SKIP, name, reason="already_done", file=existing.name)
        return SubtitleResult(name, "correct", "skip", outputs=[existing.name],
                              message=f"已有 {existing.name}")

    runner = runner or _default_runner()
    text = prompt or DEFAULT_PROMPT
    log_file: Optional[Path] = None
    try:
        if log is not None:
            log.emit("subtitle:correct", "start", name, prompt=text[:60])
            # agent 会 print 一大堆（解析结果、主题、流式模型回复、性能报告、token 成本），
            # 这些不落盘就找不回来了 —— 旧 logger.py 只配了 PrintLoggerFactory，
            # 连它自己的 save_to_json() 都没人调用过
            with log.capture("agent-subtitle", name) as log_file:
                agent_result = runner(str(collection.editing), text)
        else:
            agent_result = runner(str(collection.editing), text)
    except Exception as exc:                 # noqa: BLE001 - 任何异常都要落成结果
        if log is not None:
            log.emit("subtitle:correct", FAIL, name, error=type(exc).__name__, message=str(exc),
                     log_file=log_file.name if log_file else None)
        return SubtitleResult(name, "correct", "fail", error=type(exc).__name__,
                              message=str(exc))

    # agent 自己会把失败写进 status；不读它就会把"0 字节 corrected.txt"当成功
    if isinstance(agent_result, dict) and agent_result.get("status") == "error":
        message = agent_result.get("message") or "字幕 agent 报错"
        if log is not None:
            log.emit("subtitle:correct", FAIL, name, error="agent_error", message=message,
                     log_file=log_file.name if log_file else None)
        return SubtitleResult(name, "correct", "fail", error="agent_error",
                              message=message)

    produced = subtitles.find_corrected(collection.editing)
    if produced is None:
        if log is not None:
            log.emit("subtitle:correct", FAIL, name, error="corrected_missing",
                     message="agent 跑完了但没生成 corrected.txt",
                     log_file=log_file.name if log_file else None)
        return SubtitleResult(name, "correct", "fail", error="corrected_missing",
                              message=f"agent 跑完了但 {collection.editing} 里没有 corrected.txt")

    if produced.stat().st_size == 0:
        # 空文件 = 模型认为没有需要纠正的行。不报错，但也别让人以为"改过了"。
        if log is not None:
            log.emit("subtitle:correct", SKIP, name, reason="no_corrections",
                     file=produced.name, log_file=log_file.name if log_file else None)
        return SubtitleResult(name, "correct", "skip", outputs=[produced.name],
                              message="模型未发现需要纠正的字幕（corrected.txt 为空）")

    # 标题：旧 agent 写在代码仓库里，我们搬进批次目录
    titles = read_agent_titles(project, collection)
    wrote_titles = False
    if titles:
        writer = titles_writer or _make_titles_writer(project, name)
        try:
            writer(titles)
            wrote_titles = True
        except Exception as exc:             # noqa: BLE001
            if log is not None:
                log.emit("subtitle:titles", FAIL, name, error=type(exc).__name__,
                         message=str(exc))

    if log is not None:
        log.emit("subtitle:correct", DONE, name, file=produced.name,
                 titles=len(titles) if titles else 0, titles_written=wrote_titles,
                 log_file=log_file.name if log_file else None)
    return SubtitleResult(name, "correct", "done", outputs=[produced.name],
                          detail={"titles": len(titles) if titles else 0,
                                  "titles_written": wrote_titles,
                                  "log_file": log_file.name if log_file else None},
                          message=f"{produced.name}（标题 {len(titles) if titles else 0} 条）")


def _make_titles_writer(project: Project, collection_name: str) -> Callable[[list[str]], None]:
    """把标题写到批次的 `标题.md`（一节一个合集）"""
    def writer(titles: list[str]) -> None:
        from deal_video_agent.agent.tools.titles_manager import TitlesManager
        manager = TitlesManager(str(project.batch_dir), title_file=project.titles_file.name,
                                game_name=project.game)
        # 副标题此刻可能还没有（由 series 阶段补），先写空
        manager.append_titles(collection_name, titles, overwrite=True)
    return writer


# ─────────────────────────── ③ 回写 srt ───────────────────────────

def patch(project: Project, collection: Collection, *, log: Optional[EventLog] = None,
          force: bool = False) -> SubtitleResult:
    """`corrected.txt` + `xx.srt` → `xx_corrected.srt`"""
    name = collection.name
    corrected = subtitles.find_corrected(collection.editing)
    if corrected is None:
        return SubtitleResult(name, "patch", "fail", error="corrected_missing",
                              message=f"{collection.editing} 里没有 corrected.txt")
    srt = subtitles.find_source_srt(collection.editing)
    if srt is None:
        return SubtitleResult(name, "patch", "fail", error="source_srt_missing",
                              message=f"{collection.editing} 里没有剪映导出的 .srt")

    out = srt.with_name(f"{srt.stem}_corrected.srt")
    if out.is_file() and not force:
        if log is not None:
            log.emit("subtitle:patch", SKIP, name, reason="already_done", file=out.name)
        return SubtitleResult(name, "patch", "skip", outputs=[out.name],
                              message=f"已有 {out.name}")

    try:
        stats = subtitles.patch_file(srt, corrected, out)
    except Exception as exc:                 # noqa: BLE001
        if log is not None:
            log.emit("subtitle:patch", FAIL, name, error=type(exc).__name__, message=str(exc))
        return SubtitleResult(name, "patch", "fail", error=type(exc).__name__,
                              message=str(exc))

    if log is not None:
        log.emit("subtitle:patch", DONE, name, file=out.name,
                 total=stats["total"], applied=stats["applied"],
                 missing=stats["missing"])
    return SubtitleResult(name, "patch", "done", outputs=[out.name],
                          detail=stats,
                          message=f"{out.name}（改 {stats['applied']}/{stats['total']} 块）")


# ─────────────────────────── 串起来 ───────────────────────────

def run(project: Project, collection: Collection, steps: Optional[list[str]] = None,
        *, log: Optional[EventLog] = None, runner: Optional[Runner] = None,
        prompt: Optional[str] = None, force: bool = False) -> list[SubtitleResult]:
    """按顺序跑 number → correct → patch。

    前一步失败就停 —— 后面两步的输入不存在，硬跑只会报更难懂的错。
    """
    steps = steps or ["number", "correct", "patch"]
    results: list[SubtitleResult] = []
    for step in steps:
        if step == "number":
            r = number(project, collection, log=log, force=force)
        elif step == "correct":
            r = correct(project, collection, log=log, runner=runner, prompt=prompt, force=force)
        elif step == "patch":
            r = patch(project, collection, log=log, force=force)
        else:
            raise ValueError(f"未知字幕步骤：{step}")
        results.append(r)
        if not r.ok:
            break
    return results
