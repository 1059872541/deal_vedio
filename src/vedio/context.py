# -*- coding: utf-8 -*-
r"""vedio.context —— 目录约定与配置的**唯一实现**。

三条不变量
==========
1. **目录树只在这里定义一次。**
   `BATCH_TREE` / `COLLECTION_TREE` 是唯一真相：`init` 照着它建目录，其余所有能力
   通过 `Project` 查目录。两边共用一份定义，从机制上避免"建的和用的不是一回事"。

2. **没有任何能力接受路径参数。**
   所有能力只收 `(game, batch, collection?)`，路径一律由本模块推导。
   谁要是在别处拼 ``D:/VedioRecords/...``，就是这个约定的破口。

3. **规则与事实分开。**
   ==================  ==========================================  ==========
   文件                装什么                                      谁写
   ==================  ==========================================  ==========
   ``game.yaml``       **规则**：时长/命名/导出参数/主播/类别       ``init`` 一次，人可手改
   ``合集清单.yaml``    **迟绑定事实**：草稿名、片头片尾映射        程序追加
   ``标题.md``         **内容**：公共前缀 + 副标题 + 每集标题       ``correct`` / ``plan``
   ==================  ==========================================  ==========

   为什么分开：PyYAML 往返读写会抹掉注释，而 ``game.yaml`` 的注释是给人手改时看的。
   所以规则文件永不程序化重写。

用法
====
    from vedio import context

    p = context.Project.open("我的世界", "2026-12")
    c = p.collection("合集一")
    c.material              # .../我的世界-2026-12/合集/合集一/素材
    c.final                 # .../合集/合集一/成片
    p.intro_for("合集一")    # .../我的世界-2026-12/片头/xxx.mp4
    p.subtitle_for("合集一")  # "收集强力变身-上篇"
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from util.file_utils import TextUtils

# ─────────────────────────── 目录树（唯一真相） ───────────────────────────

#: 批次根下必然存在的目录。`init` 按这个列表建，其余环节按名字取。
BATCH_TREE: tuple[str, ...] = ("素材库", "片头", "片尾", "术语库", "log", "合集")

#: 每个合集目录下必然存在的子目录。
COLLECTION_TREE: tuple[str, ...] = ("素材", "剪辑", "成片")

#: 批次根下的三个关键文件。
RULES_FILE = "game.yaml"
MANIFEST_FILE = "合集清单.yaml"
TITLES_FILE = "标题.md"
LEDGER_FILE = "台账.xlsx"

#: 合集目录名的前缀
COLLECTION_PREFIX = "合集"

_COLLECTION_RE = re.compile(rf"^{COLLECTION_PREFIX}([\u4e00-\u9fff]+)$")


# ─────────────────────────── 错误 ───────────────────────────

class ContextError(Exception):
    """所有 context 错误的基类。``code`` 给 CLI / agent 用来分支，不要靠解析中文。"""

    code = "context_error"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.detail}


class LocalConfigError(ContextError):
    """`conf/本机.yaml` 缺失或缺关键字段。"""

    code = "local_config_error"


class BatchNotFound(ContextError):
    """工作区里没有这个批次目录。"""

    code = "batch_not_found"


class NotInitialized(ContextError):
    """批次目录在，但不是用 `init` 建的（缺 `game.yaml`）。"""

    code = "not_initialized"


class CollectionNotFound(ContextError):
    """批次里没有这个合集目录。"""

    code = "collection_not_found"


class TemplateMissing(ContextError):
    """片头/片尾在 `合集清单.yaml` 里没登记，或登记的文件不存在。"""

    code = "template_missing"


# ─────────────────────────── 本机配置 ───────────────────────────

@dataclass(frozen=True)
class LocalConfig:
    """机器相关配置，来自 ``conf/本机.yaml``（gitignored）。"""

    workspace_root: Path
    draft_dir: Path | None = None
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    window_title: str = "剪映专业版"
    #: 台账（片单）输出根目录。台账是交付物，不属于某个批次，单独放
    ledger_root: Path | None = None
    #: 片单 Excel 生成脚本（稳定的外部实现，见 conf/本机.yaml 注释）
    excel_generator: Path | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LocalConfig":
        p = Path(path) if path else _repo_root() / "conf" / "本机.yaml"
        if not p.is_file():
            raise LocalConfigError(
                f"找不到本机配置：{p}",
                hint="首次使用先看 docs/安装与配置.md，把工作区目录写进 conf/本机.yaml",
            )
        data = _read_yaml(p) or {}
        return cls.from_dict(data, source=str(p))

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "<dict>") -> "LocalConfig":
        ws = (data.get("workspace") or {}).get("root")
        if not ws:
            raise LocalConfigError(
                f"{source} 缺少 workspace.root",
                hint="填上工作区目录，例如 D:/VedioRecords/工作区",
            )
        jy = data.get("jianying") or {}
        tool = data.get("tool") or {}
        paths = data.get("paths") or {}
        draft = (jy.get("draft_dir") or "").strip()
        ledger_root = (paths.get("ledger_root") or "").strip()
        excel_gen = (paths.get("excel_generator") or "").strip()
        return cls(
            workspace_root=Path(ws),
            draft_dir=Path(draft) if draft else None,
            ffmpeg=str(tool.get("ffmpeg") or "ffmpeg"),
            ffprobe=str(tool.get("ffprobe") or "ffprobe"),
            window_title=str(jy.get("window_title") or "剪映专业版"),
            ledger_root=Path(ledger_root) if ledger_root else None,
            excel_generator=Path(excel_gen) if excel_gen else None,
        )


# ─────────────────────────── agent 配置 ───────────────────────────

#: agent 配置文件名（在 conf/ 下）
AGENT_CONFIG_FILE = "agent.yaml"

#: 模型名兜底值。正常以 `conf/agent.yaml` 为准 —— 写在这里只是为了让
#: "配置文件不存在"也能跑起来，不是给业务用的常量。
DEFAULT_MODEL = "deepseek-flash"


#: 提示词目录（进 git，和字幕 agent 共用一套机制）
PROMPTS_DIR = (Path(__file__).resolve().parent.parent
                / "deal_video_agent" / "prompts")


def load_prompt(name: str, default: str = "", game: str = "") -> str:
    """读提示词：`prompts/editorial.yaml` → 游戏覆写 → 代码兜底。

    为什么要和字幕 agent 用同一个目录：提示词是**领域知识**，不是机器配置。
    进 git 才不会丢；支持 `prompts/games/{游戏}.yaml` 覆写，不同游戏才能
    有不同的口径。`agent.yaml` 只留账号/模型/额度。

    Args:
        name: 键名（`series_suggest` / `ledger_copy`）
        default: 配置里没有时的兜底值
        game: 游戏名（`我的世界`）。有 `prompts/games/{game}.yaml` 且写了同名键
              时用它整条替换
    """
    base = _read_yaml(PROMPTS_DIR / "editorial.yaml") or {}
    value = base.get(name)

    if game:
        override = _read_yaml(PROMPTS_DIR / "games" / f"{game}.yaml") or {}
        if name in override:
            value = override[name]

    if isinstance(value, str) and value.strip():
        return value.strip()
    return default



@dataclass(frozen=True)
class AgentConfig:
    """字幕 agent 的模型与密钥，来自 ``conf/agent.yaml``（gitignored）。

    为什么单独一个文件，不并进 `本机.yaml`：

        `本机.yaml`  = 这台机器有什么（工作区路径、ffmpeg 在哪）
        `agent.yaml` = 用哪个账号、哪个模型

    后者会随厂商更新而变（模型名一年能换三次），而且换账号时只改这一处。
    混在一起的话，每次换模型都要动路径配置，容易改错。
    """

    api_key: str = ""
    model: str = DEFAULT_MODEL
    base_url: str = "https://api.deepseek.com"
    max_tokens: int = 8192
    #: 提示词。键名稳定，内容可在 agent.yaml 里改，不改代码
    #: （`series_suggest` = 起篇名，`ledger_copy` = 写内容介绍/关键字）
    prompts: dict[str, str] = field(default_factory=dict)

    def prompt(self, name: str, default: str = "") -> str:
        """取提示词。配置里没有就用代码里的兜底默认值。"""
        value = (self.prompts or {}).get(name)
        return value.strip() if isinstance(value, str) and value.strip() else default

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AgentConfig":
        """读配置。

        文件不存在**不报错** —— 只靠环境变量也能跑，这时用默认值。
        文件存在但内容坏了才报错，免得以为是"没配置"。
        """
        p = Path(path) if path else _repo_root() / "conf" / AGENT_CONFIG_FILE
        if not p.is_file():
            return cls()
        data = _read_yaml(p) or {}
        return cls.from_dict(data, source=str(p))

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "<dict>") -> "AgentConfig":
        section = data.get("deepseek") or {}
        if not isinstance(section, dict):
            raise LocalConfigError(f"{source} 的 deepseek 段不是一个字典")

        max_tokens = section.get("max_tokens", 8192)
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            raise LocalConfigError(f"{source} 的 deepseek.max_tokens 不是整数：{max_tokens!r}")
        if max_tokens <= 0:
            max_tokens = 8192

        prompts = data.get("prompts")
        if not isinstance(prompts, dict):
            prompts = {}

        return cls(
            api_key=str(section.get("api_key") or "").strip(),
            model=str(section.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            base_url=str(section.get("base_url") or "https://api.deepseek.com").strip()
                     or "https://api.deepseek.com",
            max_tokens=max_tokens,
            prompts={str(k): str(v) for k, v in prompts.items() if isinstance(v, str)},
        )


# ─────────────────────────── 剪映草稿索引 ───────────────────────────

@dataclass(frozen=True)
class Draft:
    """剪映里的一个草稿。"""

    name: str                                # 界面显示名（人工命名）
    folder: Path                             # 实际目录
    seconds: float = 0.0                     # 时长；0 = 未知
    modified: str | None = None              # "YYYY-MM-DD HH:MM"
    root: Path | None = None                 # 所属草稿根

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft": self.name,
            "folder": str(self.folder),
            "seconds": round(self.seconds, 1),
            "modified": self.modified,
        }


def jianying_index_paths() -> list[Path]:
    """剪映草稿索引 ``root_meta_info.json`` 的所有候选位置。

    索引在剪映的用户数据目录里，**不在草稿目录里**：:

        %LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\<项目id>\\root_meta_info.json

    ``<项目id>`` 通常是 ``com.lveditor.draft``；用通配是为了跳过没有索引的
    兄弟目录（实测 ``com.lveditor.textTemplate.draft`` 就没有）。
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    projects = Path(base) / "JianyingPro" / "User Data" / "Projects"
    if not projects.is_dir():
        return []
    return sorted(projects.glob("*/root_meta_info.json"))


def _read_json_tolerant(path: Path) -> Any:
    """读 JSON：容忍 BOM；剪映运行时可能短暂占用文件，失败就当没有。"""
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        except OSError:
            return None
    return None


def _us_to_seconds(value: Any) -> float:
    """剪映的时间量与时间戳都是微秒。"""
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError):
        return 0.0


def _us_to_stamp(value: Any) -> str | None:
    seconds = _us_to_seconds(value)
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return None


def _norm_path(p: Path) -> str:
    return str(p).replace("\\", "/").rstrip("/").lower()


def load_jianying_index(
    root_hint: Path | None = None,
    index_paths: Iterable[str | Path] | None = None,
) -> list[Draft]:
    """从剪映索引读出草稿列表（按最近修改倒序）。

    Args:
        root_hint: 给了就只保留该草稿根下的草稿（``本机.yaml`` 手填时用）。
        index_paths: 显式指定索引文件（测试用）；默认自动找。

    Returns:
        草稿列表。索引不存在或损坏 → 空列表（**不是错误**，调用方自己决定要不要问人）。
    """
    paths = list(index_paths) if index_paths is not None else jianying_index_paths()
    candidates: list[Draft] = []
    for p in paths:
        data = _read_json_tolerant(Path(p))
        if not isinstance(data, dict):
            continue
        for entry in data.get("all_draft_store") or []:
            name = str(entry.get("draft_name") or "").strip()
            fold = str(entry.get("draft_fold_path") or "")
            if not name or not fold:
                continue
            folder = Path(fold)
            root = Path(entry["draft_root_path"]) if entry.get("draft_root_path") else folder.parent
            if root_hint is not None and _norm_path(root) != _norm_path(root_hint):
                continue
            candidates.append(Draft(
                name=name,
                folder=folder,
                seconds=_us_to_seconds(entry.get("tm_duration")),
                modified=_us_to_stamp(entry.get("tm_draft_modified")),
                root=root,
            ))
    # 同一草稿可能出现在多份索引里；按 (名字, 目录) 去重，留最新的那条
    best: dict[tuple[str, str], Draft] = {}
    for d in candidates:
        key = (d.name, _norm_path(d.folder))
        if key not in best or (d.modified or "") > (best[key].modified or ""):
            best[key] = d
    return sorted(best.values(), key=lambda d: (d.modified or ""), reverse=True)


def drafts_from_listdir(root: Path) -> list[Draft]:
    """兜底：直接扫目录。**名字不一定准**（文件夹名可能不等于显示名）。"""
    if not root.is_dir():
        return []
    out = [
        Draft(name=p.name, folder=p, root=root)
        for p in root.iterdir()
        if p.is_dir() and (p / "draft_content.json").is_file()
    ]
    return sorted(out, key=lambda d: d.name)


def discover_jianying_root(index_paths: Iterable[str | Path] | None = None) -> Path | None:
    """自动找出剪映草稿根目录，找不到返回 ``None``。

    比"全盘搜 draft_content.json"可靠：索引是剪映自己维护的当前列表，而全盘搜
    会搜到用户以前用过的**旧草稿根**（实测搜到过一份三个月前的，6 个草稿全是废弃的）。

    兜底策略：返回 None 时应当**问用户**，不要瞎猜一个。
    """
    counts: dict[str, tuple[int, float, Path]] = {}
    for d in load_jianying_index(index_paths=index_paths):
        if d.root is None:
            continue
        key = _norm_path(d.root)
        n, total, path = counts.get(key, (0, 0.0, d.root))
        counts[key] = (n + 1, total + d.seconds, path)
    if not counts:
        return None
    # 草稿最多的根胜出；平手时取时长合计更长的
    return max(counts.values(), key=lambda v: (v[0], v[1]))[2]


# ─────────────────────────── 标题文件 ───────────────────────────

@dataclass
class TitleSection:
    """`标题.md` 里一个合集的小节。"""

    collection: str
    subtitle: str | None
    titles: list[str] = field(default_factory=list)


@dataclass
class Titles:
    """`标题.md` 的解析结果。只读结构，写回是 `correct` / `plan` 的事。"""

    prefix: str = ""
    sections: dict[str, TitleSection] = field(default_factory=dict)

    def subtitle(self, collection: str) -> str | None:
        s = self.sections.get(collection)
        return s.subtitle if s else None

    def titles_of(self, collection: str) -> list[str]:
        s = self.sections.get(collection)
        return list(s.titles) if s else []

    def prefix_of(self, collection: str) -> str:
        return self.prefix

    def full_collection_name(self, collection: str) -> str | None:
        """重命名与台账用的「发布合集名」：``{公共前缀} {副标题}``。"""
        sub = self.subtitle(collection)
        if not sub:
            return None
        return f"{self.prefix} {sub}".strip()


_SECTION_RE = re.compile(rf"^#+\s*({COLLECTION_PREFIX}[\u4e00-\u9fff]+)\s*(?:[:：]\s*(.*))?$")
_PREFIX_RE = re.compile(r"^公共前缀\s*[:：]\s*(.*)$")
_SEP_RE = re.compile(r"^-{3,}$")


def parse_titles(text: str) -> Titles:
    """解析 `标题.md` 的文本。

    实测格式（``我的世界-2026-06_titles.md``）：:

        # 我的世界系列视频标题列表
        公共前缀:波波之我的世界
        ---
        #### 合集一:收集强力变身-上篇
        林中小屋初探
        骷髅头颅之谜
        ...

    容错点：全角冒号可用；副标题可省略（``#### 合集一``）；空行忽略；
    ``---`` 与任何非合集标题都会截断上一节，避免标题串到隔壁合集。
    """
    out = Titles()
    current: TitleSection | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _PREFIX_RE.match(line)
        if m:
            out.prefix = m.group(1).strip()
            current = None
            continue
        if _SEP_RE.match(line):
            current = None
            continue
        if line.startswith("#"):
            h = _SECTION_RE.match(line)
            if h:
                current = TitleSection(collection=h.group(1), subtitle=(h.group(2) or "").strip() or None)
                out.sections[h.group(1)] = current
            else:
                current = None  # 一级标题之类，不算合集小节
            continue
        if current is not None:
            current.titles.append(line)
    return out


# ─────────────────────────── 合集 ───────────────────────────

@dataclass(frozen=True)
class Collection:
    """一个合集目录。所有路径都是算出来的，不校验存在性。"""

    project: "Project"
    name: str
    index: int

    @property
    def root(self) -> Path:
        return self.project.batch_dir / COLLECTION_PREFIX / self.name

    @property
    def material(self) -> Path:
        """OBS 原始录屏。"""
        return self.root / "素材"

    @property
    def editing(self) -> Path:
        """草稿相关产物：长片导出、`.txt`、`.srt`、`corrected.txt`。"""
        return self.root / "剪辑"

    @property
    def final(self) -> Path:
        """切分出的成片。"""
        return self.root / "成片"

    def path(self, key: str) -> Path:
        """按 ``COLLECTION_TREE`` 的键取路径（key 是中文目录名）。"""
        if key not in COLLECTION_TREE:
            raise KeyError(f"未知合集子目录：{key}（可选 {COLLECTION_TREE}）")
        return self.root / key

    def missing_dirs(self) -> list[str]:
        return [n for n in COLLECTION_TREE if not (self.root / n).is_dir()]

    def draft(self) -> str | None:
        """剪映草稿名（人工命名，只在 `合集清单.yaml` 里登记）。"""
        return self.project.draft_for(self.name)

    def subtitle(self) -> str | None:
        return self.project.subtitle_for(self.name)

    def full_name(self) -> str | None:
        return self.project.titles.full_collection_name(self.name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.name,
            "index": self.index,
            "root": str(self.root),
            "material": str(self.material),
            "editing": str(self.editing),
            "final": str(self.final),
            "draft": self.draft(),
            "subtitle": self.subtitle(),
            "full_name": self.full_name(),
        }


# ─────────────────────────── 项目（批次） ───────────────────────────

class Project:
    """一个批次。构造请用 :meth:`open`。"""

    def __init__(
        self,
        game: str,
        batch: str,
        batch_dir: Path,
        rules: dict[str, Any],
        manifest: dict[str, Any],
        local: LocalConfig,
    ) -> None:
        self.game = game
        self.batch = batch
        self.batch_dir = batch_dir
        self._rules = rules
        self._manifest = manifest
        self._local = local
        self._titles: Titles | None = None
        self._drafts: list[Draft] | None = None

    # ── 构造 ──

    @classmethod
    def open(
        cls,
        game: str,
        batch: str,
        *,
        local: LocalConfig | dict[str, Any] | None = None,
        local_path: str | Path | None = None,
    ) -> "Project":
        if isinstance(local, LocalConfig):
            cfg = local
        elif isinstance(local, dict):
            cfg = LocalConfig.from_dict(local)
        else:
            cfg = LocalConfig.load(local_path)

        batch_dir = cfg.workspace_root / cls.batch_name(game, batch)
        if not batch_dir.is_dir():
            raise BatchNotFound(
                f"工作区里没有批次目录：{batch_dir}",
                game=game,
                batch=batch,
                hint="先建批次（vedio init），或检查 game / batch 是否写错",
            )
        rules_path = batch_dir / RULES_FILE
        if not rules_path.is_file():
            raise NotInitialized(
                f"批次目录存在但缺少 {RULES_FILE}：{rules_path}",
                game=game,
                batch=batch,
                hint="这个批次不是用 init 建的，目录结构不符合约定",
            )
        rules = _read_yaml(rules_path) or {}
        manifest = _read_yaml(batch_dir / MANIFEST_FILE) or {}
        return cls(game, batch, batch_dir, rules, manifest, cfg)

    @staticmethod
    def batch_name(game: str, batch: str) -> str:
        """批次目录名：``{游戏}-{批次}``。"""
        return f"{game}-{batch}"

    # ── 批次级路径 ──

    @property
    def name(self) -> str:
        return self.batch_dir.name

    @property
    def rules_file(self) -> Path:
        return self.batch_dir / RULES_FILE

    @property
    def manifest_file(self) -> Path:
        return self.batch_dir / MANIFEST_FILE

    @property
    def titles_file(self) -> Path:
        return self.batch_dir / TITLES_FILE

    @property
    def ledger_file(self) -> Path:
        return self.batch_dir / LEDGER_FILE

    @property
    def collections_dir(self) -> Path:
        return self.batch_dir / f"{COLLECTION_PREFIX}"

    @property
    def intro_dir(self) -> Path:
        """成品片头。批次级（合集组共用一套），不在合集目录里。"""
        return self.batch_dir / "片头"

    @property
    def outro_dir(self) -> Path:
        return self.batch_dir / "片尾"

    @property
    def assets_dir(self) -> Path:
        """剪辑原料（打招呼语音、混剪片段）。程序只读不写。"""
        return self.batch_dir / "素材库"

    @property
    def glossary_dir(self) -> Path:
        return self.batch_dir / "术语库"

    @property
    def log_dir(self) -> Path:
        return self.batch_dir / "log"

    # draft_dir 的定义见下面「剪映草稿」一节（会回落到自动发现）

    # ── 规则（game.yaml，只读） ──

    @property
    def rules(self) -> dict[str, Any]:
        return self._rules

    def rule(self, dotted: str, default: Any = None) -> Any:
        """按 ``"duration.episode_body"`` 这种点号路径读规则。"""
        node: Any = self._rules
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def episode_count(self) -> int:
        return int(self.rule("duration.episode_count", 20) or 20)

    @property
    def episode_body(self) -> int:
        return int(self.rule("duration.episode_body", 0) or 0)

    @property
    def material_target(self) -> int:
        """每合集素材目标（秒）。"""
        return int(self.rule("duration.material_per_collection", 0) or 0)

    @property
    def tolerance(self) -> float:
        return float(self.rule("duration.segment_tolerance", 3) or 0)

    @property
    def host(self) -> str:
        return str(self.rule("meta.host", "") or "")

    # ── 迟绑定事实（合集清单.yaml，程序写） ──

    @property
    def manifest(self) -> dict[str, Any]:
        return self._manifest

    def draft_for(self, collection: str) -> str | None:
        value = (self._manifest.get("drafts") or {}).get(collection)
        return str(value) if value else None

    def outro_for(self) -> Path | None:
        return self._template_path(self.rule_of_manifest("templates.outro"))

    def intro_for(self, collection: str) -> Path | None:
        """按合集查片头，查不到用 ``default``。"""
        mapping = self._manifest.get("templates", {}).get("intro_mapping") or {}
        rel = mapping.get(collection) or mapping.get("default")
        return self._template_path(rel)

    def rule_of_manifest(self, dotted: str) -> Any:
        node: Any = self._manifest
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def _template_path(self, rel: Any) -> Path | None:
        if not rel:
            return None
        p = Path(str(rel))
        return p if p.is_absolute() else (self.batch_dir / p)

    def validate_templates(self, collection: str) -> dict[str, Any]:
        """拼接前置校验（docs/状态与校验.md）。返回 ``{"ok": bool, "problems": [...]}``。"""
        problems: list[dict[str, Any]] = []
        intro = self.intro_for(collection)
        outro = self.outro_for()
        if intro is None:
            problems.append({"error": "intro_not_registered",
                             "message": f"合集清单.yaml 里没有为「{collection}」登记片头（也没有 default）"})
        elif not intro.is_file():
            problems.append({"error": "intro_file_missing",
                             "message": f"片头登记了但文件不存在：{intro}", "path": str(intro)})
        if outro is None:
            problems.append({"error": "outro_not_registered",
                             "message": "合集清单.yaml 里没有登记片尾"})
        elif not outro.is_file():
            problems.append({"error": "outro_file_missing",
                             "message": f"片尾登记了但文件不存在：{outro}", "path": str(outro)})
        missing = [p for p in (intro, outro) if p is not None and not p.is_file()]
        return {
            "ok": not problems,
            "intro": str(intro) if intro else None,
            "outro": str(outro) if outro else None,
            "problems": problems,
        }

    # ── 标题与副标题（标题.md） ──

    @property
    def titles(self) -> Titles:
        if self._titles is None:
            if self.titles_file.is_file():
                self._titles = parse_titles(self.titles_file.read_text(encoding="utf-8-sig"))
            else:
                self._titles = Titles()
        return self._titles

    def reload_titles(self) -> Titles:
        self._titles = None
        return self.titles

    def subtitle_for(self, collection: str) -> str | None:
        return self.titles.subtitle(collection)

    def titles_of(self, collection: str) -> list[str]:
        return self.titles.titles_of(collection)

    # ── 合集 ──

    def ignored_collections(self) -> list[str]:
        """`game.yaml` 的 `ignore_collections`：目录里放着、但不参与流水线的合集。

        为什么需要：合集列表是**扫目录**得来的，`collections: N` 只在 `init`
        建目录时用。所以随便往 `合集/` 里放一个 `合集三/`（比如放测试素材），
        它立刻会被当成正式合集 —— `status` 算它一集没录，批量跑 `subtitle` /
        `run` 不加 `--collections` 也会动到它。

        `ignore_collections` 让"不登记"变成显式声明，而不是靠目录不存在。
        """
        raw = self.rule("ignore_collections", []) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(x).strip() for x in raw if str(x).strip()]

    def collections(self) -> list[Collection]:
        """批次里的所有合集，按中文数字升序。目录不存在时返回空列表。

        `ignore_collections` 里列出的会被跳过（测试素材等）。
        """
        d = self.collections_dir
        if not d.is_dir():
            return []
        ignored = set(self.ignored_collections())
        found: list[tuple[int, str]] = []
        for child in d.iterdir():
            if not child.is_dir():
                continue
            if child.name in ignored:
                continue
            idx = collection_index(child.name)
            if idx is None:
                continue
            found.append((idx, child.name))
        found.sort()
        return [Collection(self, name, idx) for idx, name in found]

    def collection_names(self) -> list[str]:
        return [c.name for c in self.collections()]

    def unknown_collection_dirs(self) -> list[str]:
        """``合集/`` 下名字不合规的目录（不是「合集+中文数字」）。

        `init` 只建合规目录；出现了说明有人手动改动过。`status` 应把它报出来，
        而不是默默忽略 —— 默默忽略会让一个合集的素材"凭空消失"。
        """
        d = self.collections_dir
        if not d.is_dir():
            return []
        return sorted(
            p.name for p in d.iterdir()
            if p.is_dir() and collection_index(p.name) is None
        )

    def collection(self, name: str) -> Collection:
        idx = collection_index(name)
        if idx is None:
            raise CollectionNotFound(
                f"合集名不合法：{name!r}（应形如「合集一」「合集十二」）",
                game=self.game, batch=self.batch, collection=name,
            )
        c = Collection(self, name, idx)
        if not c.root.is_dir():
            existing = self.collection_names()
            raise CollectionNotFound(
                f"批次 {self.name} 里没有「{name}」",
                game=self.game, batch=self.batch, collection=name,
                available=existing,
                hint=("这批只有 " + "、".join(existing)) if existing else "这批还没有任何合集",
            )
        return c

    def resolve_collections(self, names: Iterable[str] | None) -> list[Collection]:
        """把 ``--collections`` 解析成 Collection 列表。

        ``None`` / 空 → 本批次全部合集。这是"批处理"的入口：不传就是整批。
        """
        if names is None:
            return self.collections()
        wanted = [n.strip() for n in names if n and n.strip()]
        if not wanted:
            return self.collections()
        return [self.collection(n) for n in wanted]

    # ── 剪映草稿（人工命名；靠剪映索引查，不靠猜文件夹名） ──

    def drafts(self) -> list[Draft]:
        """剪映里的草稿列表（界面显示名 + 实际目录 + 时长）。

        数据源是剪映自己维护的 ``root_meta_info.json`` —— **它是明文 JSON**
        （与加密的 ``draft_content.json`` 不同），里面有：:

            all_draft_store[i].draft_name       界面显示名，如 "MC-合集一"
            all_draft_store[i].draft_fold_path  实际目录，如 ".../JianyingPro Drafts/11月7日"
            all_draft_store[i].draft_root_path  草稿根
            all_draft_store[i].tm_duration      时长（微秒）

        **关键：文件夹名 ≠ 界面显示名。** 实测某草稿文件夹叫 ``11月7日``，
        界面上显示的是 ``MC-合集一``。所以只看 listdir 会拿到错名字。
        """
        if self._drafts is None:
            self._drafts = load_jianying_index(self._local.draft_dir)
            if not self._drafts and self._local.draft_dir is not None:
                # 索引不可用（剪映没装/从没开过）但手填了目录 → 退化为扫目录
                self._drafts = drafts_from_listdir(self._local.draft_dir)
        return self._drafts

    @property
    def draft_dir(self) -> Path | None:
        """草稿根目录。`本机.yaml` 没填就自动发现。"""
        if self._local.draft_dir is not None:
            return self._local.draft_dir
        return discover_jianying_root()

    @property
    def ffmpeg(self) -> str:
        """ffmpeg 命令名或路径（来自 conf/本机.yaml）"""
        return self._local.ffmpeg

    @property
    def local(self) -> "LocalConfig":
        """机器配置（台账输出目录、片单生成脚本等都在这里）"""
        return self._local

    @property
    def ffprobe(self) -> str:
        """ffprobe 命令名或路径（来自 conf/本机.yaml）"""
        return self._local.ffprobe

    def available_drafts(self) -> list[str]:
        """剪映首页上能看到的草稿**显示名**，按最近修改倒序。"""
        return [d.name for d in self.drafts()]

    def draft_candidates(self, collection: str) -> list[str]:
        """「这个合集该选哪个草稿」的候选：还没被别的合集占用的那些。"""
        taken = {v for v in (self._manifest.get("drafts") or {}).values()}
        mine = self.draft_for(collection)
        return [d.name for d in self.drafts() if d.name not in taken or d.name == mine]

    def draft_info(self, name: str) -> Draft | None:
        """按显示名查一个草稿。"""
        for d in self.drafts():
            if d.name == name:
                return d
        return None

    # ── 体检 ──

    def missing_dirs(self) -> list[str]:
        """"批次骨架"里缺哪些目录（`init` 之后应为空）。"""
        return [n for n in BATCH_TREE if not (self.batch_dir / n).is_dir()]

    def as_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "batch": self.batch,
            "name": self.name,
            "batch_dir": str(self.batch_dir),
            "rules_file": str(self.rules_file),
            "manifest_file": str(self.manifest_file),
            "manifest_file_exists": self.manifest_file.is_file(),
            "titles_file": str(self.titles_file),
            "titles_file_exists": self.titles_file.is_file(),
            "ledger_file": str(self.ledger_file),
            "collections_dir": str(self.collections_dir),
            "intro_dir": str(self.intro_dir),
            "outro_dir": str(self.outro_dir),
            "assets_dir": str(self.assets_dir),
            "glossary_dir": str(self.glossary_dir),
            "log_dir": str(self.log_dir),
            # 用属性而不是 _local.draft_dir —— 后者绕过了自动发现
            "draft_dir": str(self.draft_dir) if self.draft_dir else None,
            "missing_dirs": self.missing_dirs(),
            "collections": [c.name for c in self.collections()],
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Project {self.name} collections={len(self.collections())}>"


# ─────────────────────────── 工具函数 ───────────────────────────

def collection_index(name: str) -> int | None:
    """``合集一`` → 1，``合集十二`` → 12。不合规返回 ``None``。

    用**往返校验**而不是"能转就行"：``合集十零`` 这种虽然能被宽松解析成 10，
    但规范化后是 ``合集十``，说明它不是一个人写的正常名字 —— 直接判不合规，
    免得它悄悄混进合集列表（排序、集数、台账全会被带歪）。
    """
    m = _COLLECTION_RE.match(name.strip())
    if not m:
        return None
    numeral = m.group(1)
    num = TextUtils.chinese_to_number(numeral)
    if num <= 0:
        return None
    return num if TextUtils.number_to_chinese(num) == numeral else None


def collection_name(index: int) -> str:
    """1 → ``合集一``。"""
    return f"{COLLECTION_PREFIX}{TextUtils.number_to_chinese(index)}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f) or {}
