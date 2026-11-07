# -*- coding: utf-8 -*-
"""vedio.stages.series —— 给一组合集定「篇名 + 上下篇」

为什么要单独一步：`rename` 的文件名模板里要 `{subtitle}`，也就是
「收集强力变身-上篇」这种字符串。它**不可能从单集标题推出来** ——
得知道哪几个合集属于同一篇、这一篇叫什么。

真实数据里的分组（2026-06 那批 10 个合集）：
    收集强力变身   合集一/二/三   上中下
    下界合金升级   合集四/五      上下
    击败末影龙     合集六/七/八   上中下
    初探巨龙       合集九/十      上下

**篇名由人给**。让模型起名看着能省事，但篇名是门面：一旦定错，
文件名、台账、网盘目录三处全错，改起来要重跑 rename 和 ledger。
所以 V1 只做人给篇名、程序分组命名；`--auto` 留给以后。

写法：往 `标题.md` 的 `#### 合集X:副标题` 那一行填副标题，
**不动标题正文**（那是 subtitle 阶段的产出）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import progress
from ..context import Project
from ..events import DONE, FAIL, EventLog

#: 篇内顺序词。1 个合集不加后缀，2 个用上下，3 个用上中下
_ORDINALS = {
    1: [""],
    2: ["-上篇", "-下篇"],
    3: ["-上篇", "-中篇", "-下篇"],
}

#: 匹配 `#### 合集X:副标题` 或 `#### 合集X`
_SECTION_RE = re.compile(r"^(####\s*)(合集[\u4e00-\u9fff]+)\s*(?:[:：]\s*(.*))?$")


class SeriesError(Exception):
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
class SeriesResult:
    status: str                        # done / skip / fail
    assignments: dict[str, str] = field(default_factory=dict)   # 合集 → 副标题
    error: Optional[str] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skip")

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "assignments": self.assignments,
                "error": self.error, "message": self.message}


# ─────────────────────────── 解析 ───────────────────────────

def parse_groups(spec: str) -> list[tuple[str, list[str]]]:
    """解析分组写法。

    `合集一,合集二=收集强力变身;合集三=下界合金升级`
    → [("收集强力变身", ["合集一", "合集二"]), ("下界合金升级", ["合集三"])]

    分隔符：组之间用 `;`（全角 `；` 也认），组内合集用 `,`（全角 `，` 也认），
    篇名前用 `=`（全角 `＝` 也认 —— 中文输入法很容易打出来）。
    """
    groups: list[tuple[str, list[str]]] = []
    if not spec or not spec.strip():
        return groups
    normalized = spec.replace("＝", "=")
    for chunk in re.split(r"[;；]", normalized):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise SeriesError(
                "bad_spec", f"分组写法不对：{chunk!r}",
                hint="格式是「合集一,合集二=篇名」，多组之间用分号隔开")
        names, _, title = chunk.partition("=")
        members = [x.strip() for x in re.split(r"[,，]", names) if x.strip()]
        title = title.strip()
        if not members or not title:
            raise SeriesError("bad_spec", f"分组写法不对：{chunk!r}",
                              hint="左边要有合集名，右边要有篇名")
        groups.append((title, members))
    return groups


def build_assignments(groups: list[tuple[str, list[str]]]) -> dict[str, str]:
    """篇名 + 组内顺序 → 每合集的副标题。

    Raises:
        SeriesError: 同一个合集出现在多组里，或一组超过 3 个合集
    """
    seen: dict[str, str] = {}
    out: dict[str, str] = {}
    for title, members in groups:
        if len(members) > 3:
            raise SeriesError(
                "group_too_large",
                f"「{title}」这一组有 {len(members)} 个合集，最多 3 个（上/中/下）",
                hint="拆成多组，或把这几个合集分别命名",
            )
        suffixes = _ORDINALS[len(members)]
        for name, suffix in zip(members, suffixes):
            if name in seen:
                raise SeriesError("duplicate_collection",
                                  f"「{name}」同时出现在「{seen[name]}」和「{title}」两组里")
            seen[name] = title
            out[name] = f"{title}{suffix}"
    return out


# ─────────────────────────── 写标题.md ───────────────────────────

def set_subtitles(text: str, assignments: dict[str, str]) -> tuple[str, list[str]]:
    """把副标题写进 `标题.md` 的合集小节头，**不动标题正文**。

    Returns:
        (新文本, 没找到对应小节的合集名列表)
    """
    lines = text.splitlines()
    remaining = dict(assignments)
    out: list[str] = []
    for line in lines:
        m = _SECTION_RE.match(line.strip())
        if m:
            name = m.group(2)
            if name in remaining:
                out.append(f"#### {name}:{remaining.pop(name)}")
                continue
        out.append(line)

    # 没写进去的合集：追加空小节（格式要求）
    missing = sorted(remaining)
    if missing:
        if out and out[-1].strip():
            out.append("")
        for name in missing:
            out.append("---")
            out.append(f"#### {name}:{remaining[name]}")
            out.append("")
    return "\n".join(out) + "\n", missing


def apply(project: Project, spec: str, *, log: Optional[EventLog] = None,
          force: bool = False) -> SeriesResult:
    """把分组写进 `标题.md`"""
    if log is None:
        log = EventLog(project.log_dir)

    try:
        groups = parse_groups(spec)
        if not groups:
            raise SeriesError("empty_spec", "没有给任何分组",
                              hint="格式是「合集一,合集二=篇名」")
        assignments = build_assignments(groups)
    except SeriesError as exc:
        log.emit("series", FAIL, error=exc.code, message=exc.message)
        return SeriesResult("fail", error=exc.code, message=exc.message)

    # 校验合集名都存在
    existing = set(project.collection_names())
    unknown = [n for n in assignments if n not in existing]
    if unknown:
        message = f"批次里没有这些合集：{'、'.join(unknown)}"
        log.emit("series", FAIL, error="collection_not_found", message=message)
        return SeriesResult("fail", error="collection_not_found", message=message,
                            assignments=assignments)

    titles_file = project.titles_file
    if not titles_file.is_file():
        log.emit("series", FAIL, error="titles_missing",
                 message=f"{titles_file} 不存在")
        return SeriesResult("fail", error="titles_missing",
                            message=f"{titles_file} 不存在，先跑 subtitle")

    text = titles_file.read_text(encoding="utf-8-sig")
    new_text, appended = set_subtitles(text, assignments)

    already = text == new_text
    if already and not force:
        log.emit("series", "skip", reason="already_set", assignments=assignments)
        _mark_titled(project, assignments)
        return SeriesResult("skip", assignments=assignments,
                            message="副标题已经一样，跳过")

    titles_file.write_text(new_text, encoding="utf-8", newline="\n")
    log.emit("series", DONE, assignments=assignments, appended_sections=appended)
    _mark_titled(project, assignments)
    return SeriesResult("done", assignments=assignments,
                        message=f"{len(assignments)} 个合集的副标题已写入")


def _mark_titled(project: Project, assignments: dict[str, str]) -> None:
    """篇名定好后，在进度表里给这些合集打勾。

    篇名是**导出之前**的硬门槛（见 `progress.STAGES` 的注释）：
    台账必须有篇名，而台账是交付凭证。所以这一步成功就要留痕。
    """
    for name in assignments:
        progress.record(project, name, "篇名")


# ─────────────────────────── 让模型提一个篇名 ───────────────────────────

SUGGEST_SYSTEM_DEFAULT = """\
你是游戏实况视频的运营编辑。用户会给你几个合集的每集标题。
请概括这一组内容，给整个系列起一个**篇名**。

要求：
- 中文，4~10 个字，像一个栏目标题，不是句子
- 不要包含游戏名、主播名（那是文件名里另外的部分）
- 不要带「上篇」「下篇」「合集」这类字眼
- 只输出篇名本身，不要解释、不要引号、不要标点
"""


def build_suggest_prompt(project: Project, collections: list[str]) -> str:
    """把各合集的标题拼成给模型的输入。"""
    blocks = []
    for name in collections:
        titles = project.titles_of(name) or []
        if not titles:
            continue
        lines = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
        blocks.append(f"【{name}】\n{lines}")
    return "\n\n".join(blocks)


def suggest(project: Project, collections: list[str],
            client: Optional[object] = None) -> dict[str, Any]:
    """根据标题让模型提一个篇名，**不写入任何文件**，只给人看。

    为什么要模型提：篇名要概括 20 条标题的共同主题，人翻一遍也费劲。
    但最终由人拍板 —— 篇名是门面，定错了文件名、台账、网盘目录三处全错。
    """
    prompt = build_suggest_prompt(project, collections)
    if not prompt:
        return {"ok": False, "name": "", "collections": collections,
                "error": "titles_missing"}

    from .. import context as _ctx
    system_prompt = _ctx.AgentConfig.load().prompt("series_suggest", SUGGEST_SYSTEM_DEFAULT)
    if client is None:
        try:
            from deal_video_agent.agent.tools.deepseek_api import DeepSeekClient
            client = DeepSeekClient()
        except Exception as exc:                      # noqa: BLE001
            return {"ok": False, "name": "", "collections": collections,
                    "error": f"model_unavailable: {exc}"}

    try:
        text, _usage = client.chat(system_prompt, prompt)   # type: ignore[attr-defined]
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "name": "", "collections": collections,
                "error": f"model_failed: {exc}"}

    raw = (text or "").strip()
    name = raw.splitlines()[0].strip() if raw else ""
    name = name.strip("\"'“”「」《》 　.,，。")
    if not name:
        return {"ok": False, "name": "", "collections": collections,
                "error": "empty_response"}
    return {"ok": True, "name": name, "collections": collections, "error": None}
