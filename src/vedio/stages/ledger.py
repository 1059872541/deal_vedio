# -*- coding: utf-8 -*-
"""vedio.stages.ledger —— 生成台账 Excel

列序是**冻结规则**（和甲方约定），改了对接方就不认：

    A 合集名 / B 精彩看点 / C 时长(秒) / D 合集时长 / E 片头时长
    F 减片头 / G 主播 / H 类别 / I 集数 / J 年份 / K 内容介绍 / L 关键字

数据从三处来：
    `标题.md`        合集全名 + 每集标题
    `成片/` + ffprobe 每集实际时长
    `合集清单.yaml`   片头时长（登记的那个文件 probe 出来）
    `game.yaml`      主播 / 类别 / 年份

**B / K / L 三列目前留空** —— 内容来源还没定（是人工写、还是让模型从字幕生成），
`TODO.md` 里记着这条。留空比编一个假值好：错的数据下游更难查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
import time
from typing import Any, Optional

from .. import media
from .. import progress
from ..context import Collection, Project
from ..events import DONE, FAIL, EventLog
from . import rename as rename_stage

#: 冻结列序
COLUMNS = [
    "合集名", "精彩看点", "时长(秒)", "合集时长", "片头时长",
    "减片头", "主播", "类别", "集数", "年份", "内容介绍", "关键字",
]


class LedgerError(Exception):
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
class LedgerRow:
    collection: str
    episode: int
    title: str
    seconds: float
    collection_seconds: float
    intro_seconds: float

    @property
    def without_intro(self) -> float:
        return round(max(0.0, self.seconds - self.intro_seconds), 1)

    def as_list(self, *, collection_name: str, host: str, category: str,
                year: Any) -> list[Any]:
        return [
            collection_name,      # A 合集名（篇名-上篇/下篇）
            self.title,           # B 精彩看点 = 该集标题
            round(self.seconds, 1),
            self.collection_seconds,
            round(self.intro_seconds, 1),
            self.without_intro,
            host,
            category,
            self.episode,
            year,
            "",                   # K 内容介绍（来源待定）
            "",                   # L 关键字（来源待定）
        ]


@dataclass
class LedgerResult:
    status: str                       # done / skip / fail
    path: Optional[Path] = None
    collections: list[str] = field(default_factory=list)
    rows: int = 0
    error: Optional[str] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skip")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": str(self.path) if self.path else None,
            "collections": self.collections,
            "rows": self.rows,
            "error": self.error,
            "message": self.message,
        }


# ─────────────────────────── 取数 ───────────────────────────

def intro_seconds(project: Project, collection: Collection) -> float:
    """台账里的「片头时长」——**合同值**，不是片头文件的实际长度。

    甲方按「集数 × 每集 30 秒」算片头额度（20 集 → 600 秒），
    和实际拼进去的片头文件（本批 57.5 秒）无关。
    实际交付只能多不能少，所以台账照合同值减。

    配置：`duration.intro_per_episode`（默认 30 秒）。
    """
    per_episode = float(project.rule("duration.intro_per_episode", 30) or 30)
    episodes = float(project.episode_count or 0)
    return round(per_episode * episodes, 1)


def collect_rows(project: Project, collections: Optional[list[str]] = None
                 ) -> tuple[list[LedgerRow], list[str]]:
    """把一个合集的每集信息摊成行。

    Returns:
        (rows, problems)
    """
    rows: list[LedgerRow] = []
    problems: list[str] = []

    for collection in project.resolve_collections(collections):
        name = collection.name
        titles = project.titles_of(name)
        if not titles:
            problems.append(f"{name}: 标题.md 里没有这一节")
            continue

        intro = intro_seconds(project, collection)

        # 成片按编号对齐标题（和 rename 用同一套规则，避免两边理解不一致）
        files = media.list_videos(collection.final)
        by_index: dict[int, Path] = {}
        for p in files:
            idx = rename_stage.episode_index(p)
            if idx is not None:
                by_index.setdefault(idx, p)
        unindexed = [p for p in files if rename_stage.episode_index(p) is None]

        if not files:
            problems.append(f"{name}: 成片/ 里没有视频")
            continue

        # **以标题为准**：一个标题一行。
        #
        # 为什么不按成片遍历：素材比目标长一点时，剪出来会多一到两个片段
        # （那是废篇，匀素材环节该处理掉的）。按成片遍历会把废篇也写进台账，
        # 甲方看到的是"多出来的集"，实际根本没这集内容。
        # 标题是人定的交付清单，台账就照它写。
        durations = {idx: media.probe_duration(project.ffprobe, p)
                     for idx, p in by_index.items()}
        total = round(sum(durations.values()), 1)

        missing: list[int] = []
        for i, title in enumerate(titles, 1):
            path = by_index.get(i)
            if path is None:
                missing.append(i)
                continue
            rows.append(LedgerRow(
                collection=name, episode=i, title=title,
                seconds=durations[i], collection_seconds=total,
                intro_seconds=intro,
            ))

        # 有标题却找不到成片 —— 这是缺集，必须报
        if missing:
            problems.append(f"{name}: 第 {'、'.join(str(i) for i in missing)} "
                            f"集找不到成片（标题有 {len(titles)} 条）")

        # 有额外成片却没有标题 —— 废篇，不进台账，但要如实说
        extras = sorted(idx for idx in by_index if idx > len(titles))
        if extras or unindexed:
            names = [by_index[i].name for i in extras] + [p.name for p in unindexed]
            problems.append(f"{name}: {len(names)} 个成片没有对应标题，"
                            f"未计入台账（废篇，可用 balance 匀素材消掉）："
                            f"{'、'.join(names[:5])}"
                            + ("…" if len(names) > 5 else ""))
    return rows, problems


# ─────────────────────────── 写 Excel ───────────────────────────

def _group_rows(rows: list[LedgerRow]) -> dict[str, list[LedgerRow]]:
    """按合集分组并保持顺序（集号升序）。写 K/L 时要按块定位行号。"""
    grouped: dict[str, list[LedgerRow]] = {}
    for row in rows:
        grouped.setdefault(row.collection, []).append(row)
    for items in grouped.values():
        items.sort(key=lambda r: r.episode)
    return grouped


def _load_excel_generator(path: Path):
    """加载外部片单生成脚本（`conf/本机.yaml` 的 `paths.excel_generator`）。

    为什么不自带实现：那份脚本的格式（汇总行、纵向合并、红/黑配色、边框）
    是用户验证过的稳定版本，重写一遍只会引入差异。
    """
    import importlib.util

    if not path.is_file():
        raise FileNotFoundError(
            f"片单生成脚本不存在：{path}\n"
            f"请在 conf/本机.yaml 的 paths.excel_generator 里填对路径"
        )
    name = "vedio_excel_generator"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)      # type: ignore[union-attr]
    return module


def _collections_payload(rows: list[LedgerRow], project: Project) -> list[dict[str, Any]]:
    """把台账行整理成生成脚本要的 JSON。

    它需要 `第X集 标题` 这种形态的 `filename`，所以这里用和 `rename`
    同一套命名（避免文件名和台账两处不一致）。
    """
    from . import rename as rename_stage

    by_collection: dict[str, list[LedgerRow]] = {}
    for row in rows:
        by_collection.setdefault(row.collection, []).append(row)

    payload: list[dict[str, Any]] = []
    for name, items in by_collection.items():
        items.sort(key=lambda r: r.episode)
        full = project.titles.full_collection_name(name) or name
        payload.append({
            "series_title": full,
            "video_count": len(items),
            # **必须整数**：生成脚本里有 f'{minutes:02d}:{seconds:02d}'，
            # 传 float 会直接 ValueError（实测踩过）
            "total_duration": int(round(sum(r.seconds for r in items))),
            "videos": [
                {
                    "filename": f"{rename_stage.episode_label(r.episode)} {r.title}",
                    "episode_num": r.episode,
                    "duration": int(round(r.seconds)),
                }
                for r in items
            ],
        })
    return payload


# ─────────────────────────── AI 生成 K/L 两列 ───────────────────────────

DESC_SYSTEM_DEFAULT = """\
你是游戏实况视频的运营编辑，正在填写交付给甲方的片单表格。
会给你一个合集的每集标题，请为这个合集写两句交付用文案。

只输出一个 JSON 对象，不要解释、不要代码块：
{"intro": "...", "keywords": "..."}

要求：
- intro：以「{主播}」开头作为主语，20~40 个汉字，概括这一合集的内容走向。
  用中文标点，以句号结尾
- 同一系列可能有上篇/下篇：下篇的开头要体现「接着上篇往下」的递进，
  不要重复上篇已经讲过的内容
- keywords：4~6 个关键词，用顿号「、」分隔，不加书名号、不加空格。
  **不能和已用关键词重复**（下面会给出清单），换个角度描述同一个意思
"""


def build_desc_prompt(project: Project, collection: str, titles: list[str],
                      used_keywords: Optional[list[str]] = None,
                      prev_collection: str = "",
                      prev_intro: str = "") -> str:
    """拼给模型的输入：标题 + 主播 + 已用关键词 + 上篇简介。"""
    full = project.titles.full_collection_name(collection) or collection
    lines = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
    parts = [f"合集：{full}", f"集数：{len(titles)}", f"主播：{project.host or ''}", ""]
    if prev_intro:
        parts.append(f"上一篇（{prev_collection}）的内容介绍：\n{prev_intro}")
        parts.append("这一篇要接着它往下写，体现递进，别重复它的内容。\n")
    if used_keywords:
        parts.append("已用关键词（这些不能再用）：" + "、".join(used_keywords) + "\n")
    parts.append("每集标题：\n" + lines)
    return "\n".join(parts)


def normalize_intro(text: str) -> str:
    """规整内容介绍：去引号、去空白，句末补句号。"""
    value = (text or "").strip().strip("\"'“”「」")
    value = "".join(value.split())
    if value and value[-1] not in "。！？":
        value += "。"
    return value


def normalize_keywords(text: str) -> str:
    """规整关键字：统一用顿号分隔，去逗号/空格/书名号。"""
    raw = (text or "").strip().strip("\"'“”「」")
    for sep in (",", "，", ";", "；", "|", " "):
        raw = raw.replace(sep, "、")
    parts = [p.strip("《》<>　 ") for p in raw.split("、")]
    return "、".join(p for p in parts if p)


def dedupe_keywords(keywords: str, used: set[str]) -> tuple[str, list[str]]:
    """去掉与已用关键词重复的。返回 (新的串, 被丢掉的词)。"""
    kept: list[str] = []
    dropped: list[str] = []
    for word in keywords.split("、"):
        word = word.strip()
        if not word:
            continue
        if word in used:
            dropped.append(word)
            continue
        used.add(word)
        kept.append(word)
    return "、".join(kept), dropped


def generate_copy(project: Project, collection: str, titles: list[str],
                  client: Optional[object] = None,
                  used_keywords: Optional[list[str]] = None,
                  prev_collection: str = "",
                  prev_intro: str = "",
                  feedback: str = "") -> tuple[str, str]:
    """让模型生成 (内容介绍, 关键字)。失败返回 ("", "")，不让它拖垮台账。"""
    if not titles:
        return "", ""
    if client is None:
        try:
            from deal_video_agent.agent.tools.deepseek_api import DeepSeekClient
            client = DeepSeekClient()
        except Exception:
            return "", ""

    from .. import context as _ctx
    system_prompt = _ctx.load_prompt("ledger_copy", DESC_SYSTEM_DEFAULT,
                                     game=project.game)
    # 占位符用「{字符串}」而不是 str.format：提示词里的 JSON 例子自带花括号
    system_prompt = system_prompt.replace("{主播}", project.host or "主播")

    prompt = build_desc_prompt(project, collection, titles,
                               used_keywords=used_keywords,
                               prev_collection=prev_collection,
                               prev_intro=prev_intro)
    if feedback:
        prompt += "\n\n上一次生成不合格，必须修正：\n" + feedback
    try:
        text, _usage = client.chat(system_prompt, prompt)   # type: ignore[attr-defined]
    except Exception:
        return "", ""

    import json as _json
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return "", ""
    try:
        data = _json.loads(raw[start:end + 1])
    except Exception:
        return "", ""
    return (normalize_intro(str(data.get("intro") or "")),
            normalize_keywords(str(data.get("keywords") or "")))


def cjk_length(text: str) -> int:
    """数字数（只数汉字，不含标点）。

    甲方说「20~40 字」和模型自己数的都是**汉字**，不是字符数。
    按 len() 算会把 6 个标点也算进去，导致 38 个字的合格文案被判成 44 字、
    白白重试一轮还降不下来（实测踩过）。
    """
    return sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")


def check_copy(intro: str, keywords: str, used: set[str]) -> list[str]:
    """校验内容介绍/关键字是否达标。返回问题清单（空 = 合格）。"""
    problems: list[str] = []
    n = cjk_length(intro)
    if not (20 <= n <= 40):
        problems.append(f"内容介绍 {n} 字，必须 20~40 字")
    fresh = [k for k in keywords.split("、") if k and k not in used]
    if len(fresh) < 4:
        problems.append(f"可用的新关键词只有 {len(fresh)} 个，必须 4~6 个")
    if len(fresh) > 6:
        problems.append(f"关键词 {len(fresh)} 个，最多 6 个")
    return problems


def generate_copy_checked(project: Project, collection: str, titles: list[str],
                          client: Optional[object] = None,
                          used_keywords: Optional[list[str]] = None,
                          prev_collection: str = "",
                          prev_intro: str = "",
                          attempts: int = 2) -> tuple[str, str, list[str]]:
    """生成 → 校验 → 不合格就带着具体问题重试。

    **为什么必须有这一步**：提示词里写了"20~40 字"，实测模型照样给 76 字。
    光靠提示词约束字数不可靠，必须生成后量一遍，不合格就明确告诉它差在哪、
    再要一次。两次都不合格才如实报出来，不静默接受。

    Returns:
        (intro, keywords, problems) —— problems 为空表示达标
    """
    used = set(used_keywords or [])
    intro = keywords = ""
    problems: list[str] = []
    for i in range(max(1, attempts)):
        intro, keywords = generate_copy(
            project, collection, titles, client=client,
            used_keywords=sorted(used),
            prev_collection=prev_collection, prev_intro=prev_intro,
            feedback="；".join(problems) if problems else "",
        )
        if not intro and not keywords:
            problems = ["模型没有返回可解析的 JSON"]
            continue
        problems = check_copy(intro, keywords, used)
        if not problems:
            return intro, keywords, []
        if i + 1 < attempts:
            print(f"  {collection} 文案不达标（{'；'.join(problems)}），重试一次")
    return intro, keywords, problems


def fill_ai_columns(path: Path, blocks: list[tuple[int, int, str, list[str]]],
                    project: Project, client: Optional[object] = None) -> list[str]:
    """写 K/L 两列。返回逐条问题说明。

    顺序很重要：**按合集顺序生成**，因为下篇要接着上篇写、关键词要全局去重。
    """
    from openpyxl import load_workbook

    problems: list[str] = []
    record = load_entries_record(project)
    used: set[str] = set()
    for entry in record.values():
        for word in str(entry.get("keywords") or "").split("、"):
            if word.strip():
                used.add(word.strip())

    wb = load_workbook(str(path))
    ws = wb.active
    prev_collection = ""
    prev_intro = ""

    for start_row, count, name, titles in blocks:
        intro, keywords, bad = generate_copy_checked(
            project, name, titles, client=client,
            used_keywords=sorted(used),
            prev_collection=prev_collection, prev_intro=prev_intro,
        )
        if not intro and not keywords:
            problems.append(f"{name}: 内容介绍/关键字没生成出来")
            continue
        for item in bad:
            problems.append(f"{name}: {item}（重试后仍不达标）")

        keywords, dropped = dedupe_keywords(keywords, used)
        if dropped:
            problems.append(f"{name}: 去掉了重复关键词（{'、'.join(dropped)}）")

        ws.cell(row=start_row, column=11, value=intro)      # K
        ws.cell(row=start_row, column=12, value=keywords)   # L

        record[name] = {"intro": intro, "keywords": keywords}
        prev_collection, prev_intro = name, intro

    wb.save(str(path))
    save_entries_record(project, record)
    return problems


def _batch_month(project: Project, fallback: Optional[int] = None) -> int:
    """从批次名取月份：`2026-12` → 12。取不到用当前月。"""
    import re as _re

    m = _re.search(r"(\d{4})-(\d{2})$", str(getattr(project, "batch", "") or ""))
    if m:
        return int(m.group(2))
    return fallback or int(time.strftime("%m"))


def entries_record_path(project: Project) -> Path:
    """同批次已出过的「内容介绍 / 关键字」记录。

    为什么需要：一个批次里几个合集是同一系列（上篇/下篇），关键词不能撞车。
    每次生成前读它、生成后写回，下一批才知道哪些词已经用过了。
    """
    return Path(project.batch_dir) / "台账记录.json"


def load_entries_record(project: Project) -> dict[str, dict[str, str]]:
    """读已有记录：{合集名: {"intro": ..., "keywords": ...}}"""
    import json

    path = entries_record_path(project)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_entries_record(project: Project, entries: dict[str, dict[str, str]]) -> None:
    import json

    path = entries_record_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass


def ledger_target(project: Project, month: Optional[int] = None) -> Path:
    """台账就放在**批次目录**里：`{批次}/26年{主播}{月}月第一批片单.xlsx`。

    用户明确要求放批次目录 —— 台账和这个批次的成片、标题、进度是一套东西，
    散到交付目录反而对不上号。

    月份取**批次月份**（`我的世界-2026-12` → 12），不是当前月份：
    12 月的批次在 11 月做，台账也该叫 12 月。
    """
    year = int(project.rule("meta.year", 2026) or 2026)
    host = project.host or ""
    month = month or _batch_month(project)
    return Path(project.batch_dir) / f"{year % 100}年{host}{month}月第一批片单.xlsx"


def entries_record_path(project: Project) -> Path:
    """同批次已出过的「内容介绍 / 关键字」记录。

    为什么需要：一个批次里几个合集是同一系列（上篇/下篇），关键词不能撞车。
    每次生成前读它、生成后写回，下一批才知道哪些词已经用过了。
    """
    return Path(project.batch_dir) / "台账记录.json"


def load_entries_record(project: Project) -> dict[str, dict[str, str]]:
    """读已有记录：{合集名: {"intro": ..., "keywords": ...}}"""
    import json

    path = entries_record_path(project)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_entries_record(project: Project, entries: dict[str, dict[str, str]]) -> None:
    import json

    path = entries_record_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass


def write_workbook(path: Path, rows: list[LedgerRow], project: Project) -> None:
    """写 xlsx —— 交给外部稳定脚本，不在本仓库里重实现格式。"""
    import json
    import tempfile

    local = getattr(project, "local", None)
    generator = getattr(local, "excel_generator", None)
    if generator is None:
        raise FileNotFoundError(
            "没有配置片单生成脚本（conf/本机.yaml 的 paths.excel_generator）")

    module = _load_excel_generator(Path(generator))
    payload = _collections_payload(rows, project)

    intro = 0.0
    if rows:
        intro = rows[0].intro_seconds
    tmp = Path(tempfile.mkdtemp()) / "ledger.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        module.generate_excel_from_json(
            str(tmp), str(path),
            host=project.host or "",
            category=str(project.rule("meta.category", "") or ""),
            year=project.rule("meta.year", 2026),
            intro_duration=int(round(intro)),
        )
    finally:
        try:
            tmp.unlink()
            tmp.parent.rmdir()
        except OSError:
            pass


def build_ledger(project: Project, collections: Optional[list[str]] = None, *,
                 log: Optional[EventLog] = None,
                 force: bool = False, with_ai: bool = True) -> LedgerResult:
    """生成交付用的片单 xlsx（`ledger_target()` 算路径）"""
    if log is None:
        log = EventLog(project.log_dir)

    out = ledger_target(project)
    if out.is_file() and not force:
        log.emit("ledger", "skip", reason="already_done", file=out.name)
        return LedgerResult("skip", path=out, message=f"{out.name} 已存在（--force 可重写）")

    # ── 硬约束：没有篇名不许写台账 ──
    # 台账是交付凭证，篇名那一列空了，甲方拿到的就是一张半成品表。
    # 而且台账一旦生成，后面再补篇名就得整份重写 —— 不如现在拦住。
    try:
        targets = [c.name for c in project.resolve_collections(collections)]
    except Exception:
        targets = []
    missing = [n for n in targets if not (project.subtitle_for(n) or "").strip()]
    if missing:
        message = (f"这些合集还没有篇名：{'、'.join(missing)}。"
                   f"台账必须有篇名，先跑 vedio series 定下来。")
        log.emit("ledger", FAIL, error="title_missing", message=message,
                 collections=missing)
        return LedgerResult("fail", error="title_missing", message=message)

    try:
        rows, problems = collect_rows(project, collections)
    except Exception as exc:                 # noqa: BLE001
        log.emit("ledger", FAIL, error=type(exc).__name__, message=str(exc))
        return LedgerResult("fail", error=type(exc).__name__, message=str(exc))

    if not rows:
        message = "没有可写的数据" + (("：" + "；".join(problems)) if problems else "")
        log.emit("ledger", FAIL, error="no_data", message=message)
        return LedgerResult("fail", error="no_data", message=message)

    try:
        write_workbook(out, rows, project)
    except PermissionError:
        message = (f"写不进去：{out.name} 正被其他程序占用（大概是 Excel 开着）。"
                   f"关掉它再跑。")
        log.emit("ledger", FAIL, error="file_locked", message=message, file=str(out))
        return LedgerResult("fail", error="file_locked", message=message)
    except Exception as exc:                 # noqa: BLE001
        log.emit("ledger", FAIL, error=type(exc).__name__, message=str(exc))
        return LedgerResult("fail", error=type(exc).__name__, message=str(exc))

    # K/L 两列：生成脚本固定写空，由模型补（内容介绍 / 关键字）
    if with_ai:
        blocks: list[tuple[int, int, str, list[str]]] = []
        start_row = 5
        for name, items in _group_rows(rows).items():
            blocks.append((start_row, len(items), name, [r.title for r in items]))
            start_row += len(items)
        try:
            ai_problems = fill_ai_columns(out, blocks, project)
            problems.extend(ai_problems)
        except Exception as exc:                 # noqa: BLE001
            problems.append(f"内容介绍/关键字没写进去：{exc}")

    involved = sorted({r.collection for r in rows})
    # 每个合集单独记一条 done —— status 判「台账」看的是**该合集的** ledger done
    # （`log.last(verb="ledger", collection=…, event="done")`）。
    # 只记下面那条汇总事件（collections=[…]）它认不出来，会一直提示"跑 ledger"。
    for name in involved:
        log.emit("ledger", DONE, name, file=out.name)
    log.emit("ledger", DONE, rows=len(rows), collections=involved, file=out.name,
             warnings=problems)
    # 台账那一列写文件名 —— 这是唯一"文件里推不出来"的事实，必须记下来
    for name in involved:
        progress.record(project, name, "台账", out.name)
    return LedgerResult("done", path=out, collections=involved, rows=len(rows),
                        message=f"{len(rows)} 行 / {len(involved)} 个合集"
                                + ("（有警告）" if problems else ""))
