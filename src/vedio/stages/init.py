# -*- coding: utf-8 -*-
"""vedio.stages.init —— 建批次

`init` 要做的事，按顺序：

    读 conf/默认规则.yaml
      ↓ 深合并 conf/游戏规则/{游戏}.yaml（如果存在；只写差异）
    合并后的完整规则
      ↓ 叠加本批次确认项（主播、合集数、以及用户改的那几项）
    建目录树（BATCH_TREE + 合集/合集X/COLLECTION_TREE）
    写三个文件：
        game.yaml        **规则**（建完即定稿，人可手改，程序永不重写）
        合集清单.yaml     **迟绑定事实**骨架（草稿名、片头片尾映射，程序写）
        标题.md          公共前缀（每集标题由 subtitle 阶段追加）

为什么要"合并后校验完整性"：游戏差异文件本身不完整，深合并容易漏键。
漏了键不能静默取默认 —— 要直接报错，让人补规则。

为什么 `game.yaml` 里不带 `templates` / `collection_names`：那是做完才知道的事实，
属于 `合集清单.yaml` 和 `标题.md`。混在一起会逼程序重写 `game.yaml`，
而 PyYAML 往返会抹掉人写的注释。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from .. import context, progress
from ..context import BATCH_TREE, COLLECTION_TREE, RULES_FILE, MANIFEST_FILE, TITLES_FILE
from ..events import DONE, EventLog

DEFAULT_RULES_FILE = "默认规则.yaml"
GAME_RULES_DIR = "游戏规则"

#: game.yaml 里各段的注释（顺序即渲染顺序）
SECTION_COMMENTS: list[tuple[str, str]] = [
    ("ignore_collections", "不参与流水线的合集目录（测试素材等）；空 = 全部参与"),
    ("duration", "时长（单位：秒）"),
    ("export", "视频导出（剪映「视频导出」面板上的 5 项 + 超时）"),
    ("naming", "命名规范：{host} {game} {subtitle} {collection} {cn_ep} {ep} {title}"),
    ("netdisk", "网盘目录结构：{month} {host} {game} {collection} {filename}"),
    ("meta", "本批次特有：主播 / 台账「类别」列"),
    ("encode", "ffmpeg 拼接编码参数（技术项，平时不用动）"),
]


class InitError(Exception):
    """建批次失败"""

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


# ─────────────────────────── 规则装载 ───────────────────────────

def repo_conf_dir() -> Path:
    """仓库里的 conf/ 目录"""
    return Path(__file__).resolve().parent.parent.parent.parent / "conf"


def load_rules(conf_dir: Optional[Path] = None, game: str = "") -> dict[str, Any]:
    """读默认规则，深合并游戏差异，返回完整规则"""
    conf = Path(conf_dir) if conf_dir else repo_conf_dir()
    default_path = conf / DEFAULT_RULES_FILE
    if not default_path.is_file():
        raise InitError("rules_missing", f"找不到公共规则：{default_path}",
                        hint="conf/默认规则.yaml 是建批次的模板，不能缺")

    base = _read_yaml(default_path)
    diff_path = conf / GAME_RULES_DIR / f"{game}.yaml"
    if game and diff_path.is_file():
        diff = _read_yaml(diff_path)
        missing = _missing_keys(base, diff)
        if missing:
            raise InitError(
                "game_diff_unknown_keys",
                f"{diff_path.name} 里有公共规则中不存在的键：{'、'.join(missing)}",
                hint="游戏差异只能覆盖已有键，不能新增。新增字段请先加进 conf/默认规则.yaml",
            )
        base = deep_merge(base, diff)
    return base


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise InitError("rules_invalid", f"{path} 不是一个 YAML 字典")
    return data


def deep_merge(base: dict, patch: dict) -> dict:
    """深合并：字典递归，标量覆盖，**列表整体替换**（不追加）"""
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _missing_keys(base: dict, patch: dict, prefix: str = "") -> list[str]:
    """列出 patch 里 base 没有的键（点号路径）"""
    missing: list[str] = []
    for key, value in patch.items():
        path = f"{prefix}{key}"
        if key not in base:
            missing.append(path)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            missing.extend(_missing_keys(base[key], value, prefix=f"{path}."))
    return missing


def apply_overrides(rules: dict, overrides: Optional[dict[str, Any]]) -> dict[str, Any]:
    """按点号路径覆盖，如 `{"duration.episode_body": 450}`"""
    out = copy.deepcopy(rules)
    for dotted, value in (overrides or {}).items():
        node = out
        parts = dotted.split(".")
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                raise InitError("override_unknown_key", f"规则里没有 {dotted}")
            node = node[part]
        if parts[-1] not in node:
            raise InitError("override_unknown_key", f"规则里没有 {dotted}")
        node[parts[-1]] = value
    return out


# ─────────────────────────── 计划 ───────────────────────────

@dataclass
class InitPlan:
    """建批次要做的事（先算清楚再动手，方便 dry-run）"""

    game: str
    batch: str
    collections: int
    host: str
    rules: dict[str, Any]
    batch_dir: Path
    dirs: list[Path] = field(default_factory=list)
    files: dict[Path, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return context.Project.batch_name(self.game, self.batch)

    def as_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "batch": self.batch,
            "name": self.name,
            "batch_dir": str(self.batch_dir),
            "collections": self.collections,
            "host": self.host,
            "dirs": [str(p.relative_to(self.batch_dir)) for p in self.dirs],
            "files": [p.name for p in self.files],
        }


def build_plan(game: str, batch: str, *, collections: int = 1, host: str = "",
               overrides: Optional[dict[str, Any]] = None,
               conf_dir: Optional[Path] = None,
               workspace_root: Optional[Path] = None) -> InitPlan:
    """算出"要建什么"，不落盘。

    Raises:
        InitError: 规则缺失 / 键不存在 / 参数非法 / 批次已存在
    """
    if not game.strip():
        raise InitError("bad_game", "游戏名不能为空")
    if not batch.strip():
        raise InitError("bad_batch", "批次不能为空")
    if collections < 1:
        raise InitError("bad_collections", f"合集数必须 ≥ 1，现在是 {collections}")

    rules = load_rules(conf_dir, game)
    rules = apply_overrides(rules, overrides)

    # 本批次特有：主播进 meta.host（台账 G 列和命名模板都要用）
    meta = rules.setdefault("meta", {})
    if not isinstance(meta, dict):
        raise InitError("rules_invalid", "规则里的 meta 不是一个字典")
    if host:
        meta["host"] = host
    rules["meta"] = meta

    root = Path(workspace_root) if workspace_root else _workspace_root()
    batch_dir = root / context.Project.batch_name(game, batch)
    if batch_dir.exists() and (batch_dir / RULES_FILE).exists():
        raise InitError(
            "batch_exists", f"批次已存在：{batch_dir}",
            hint="换个批次名，或者直接对现有批次跑 status",
        )

    plan = InitPlan(game=game, batch=batch, collections=collections, host=host,
                    rules=rules, batch_dir=batch_dir)

    # 目录树：批次级 + 每个合集的三个子目录
    for name in BATCH_TREE:
        plan.dirs.append(batch_dir / name)
    for index in range(1, collections + 1):
        cname = context.collection_name(index)
        for sub in COLLECTION_TREE:
            plan.dirs.append(batch_dir / "合集" / cname / sub)

    # 三个文件
    plan.files[batch_dir / RULES_FILE] = render_game_yaml(plan)
    plan.files[batch_dir / MANIFEST_FILE] = render_manifest(plan)
    plan.files[batch_dir / TITLES_FILE] = render_titles(plan)
    # 第四样：进度表。它不是"可选"的 —— 批次一建好就该有地方记进度，
    # 否则第一天就没人知道该往哪写。全 `·`，等着各环节来打勾。
    plan.files[batch_dir / progress.FILE_NAME] = render_progress(plan)
    return plan


def _workspace_root() -> Path:
    cfg = context.LocalConfig.load()
    return cfg.workspace_root


# ─────────────────────────── 渲染 ───────────────────────────

def render_game_yaml(plan: InitPlan) -> str:
    """生成完整快照。

    带段注释，但**不逐字段注释** —— 字段说明在 `conf/默认规则.yaml` 里，
    这里只保证值完整、可读、可手改。
    """
    head = f"""\
# ══════════════════════════════════════════════════════════════════
# {plan.name} 批次配置（完整快照）
#
# 由 conf/默认规则.yaml 深合并 conf/游戏规则/{plan.game}.yaml 生成，
# 再按本批次确认项调整。建完即定稿：之后所有环节只读本文件。
# 生成时间: {date.today().isoformat()}
#
# ⚠ 本文件只放「建批次时就能定的规则」。
#   做完才知道的事实不在这里：
#     草稿名 / 片头片尾映射  → 合集清单.yaml
#     副标题 / 每集标题      → 标题.md
# ══════════════════════════════════════════════════════════════════

game: {plan.game}
batch: {plan.batch}
collections: {plan.collections}
"""
    parts = [head]
    for key, comment in SECTION_COMMENTS:
        if key not in plan.rules:
            continue
        block = yaml.safe_dump({key: plan.rules[key]}, allow_unicode=True, sort_keys=False)
        parts.append(f"\n# ── {comment} ──\n{block}")
    # 规则里有但没被 SECTION_COMMENTS 覆盖的段，兜底追加
    known = {k for k, _ in SECTION_COMMENTS}
    for key, value in plan.rules.items():
        if key in known or key in ("meta",):
            continue
        block = yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False)
        parts.append(f"\n# ── {key} ──\n{block}")
    return "".join(parts)


def render_manifest(plan: InitPlan) -> str:
    collection_names = "、".join(context.collection_name(i) for i in range(1, plan.collections + 1))
    return f"""\
# ══════════════════════════════════════════════════════════════════
# {plan.name} 合集清单
#
# ⚠ 本文件由程序维护（登记迟绑定事实），人只核对，不要手改。
#   手改会被下一次登记覆盖。
#
# 装什么：做完才知道、但之后每个环节都要查的事实。
#   规格：批次建好后由 init 生成骨架，之后各环节陆续补。
#
# 本批次合集：{collection_names}
# ══════════════════════════════════════════════════════════════════

# ── 剪映草稿名 ──
# 草稿是人随手命名的（MC-合集一 / 合集10-混剪 / 11月7日 都可能出现），
# 程序不解析名字，只查这张表。查不到就报 draft_not_found，并列出当前所有草稿。
#
# 注意：剪映的「文件夹名」不等于「界面显示名」——
#   索引在 %LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\root_meta_info.json
drafts: {{}}

# ── 片头片尾 ──
# 成品文件在这里登记；没登记就说明还没做好，拼接前会报错停下。
# intro_mapping：按合集名查，查不到用 default。允许多个合集指向同一个文件
#                （实际常是 1-3 / 4-5 / 6-7-8 / 9-10 共用一套）。
templates:
  intro_mapping: {{}}
  outro: null
"""


def render_titles(plan: InitPlan) -> str:
    prefix = f"{plan.host}之{plan.game}" if plan.host else f"之{plan.game}"
    return f"""\
# {plan.game}系列视频标题列表
公共前缀:{prefix}

# 每集的标题由 subtitle 阶段追加，格式：
# ---
# #### 合集一:副标题-上篇
# 第一集标题
# 第二集标题
# ...
"""


def render_progress(plan: InitPlan) -> str:
    """建批次时的进度表：所有合集全 `·`，等着各环节来打勾。"""
    collections = [context.collection_name(i) for i in range(1, plan.collections + 1)]
    ignored = plan.rules.get("ignore_collections") or []
    if isinstance(ignored, str):
        ignored = [ignored]
    return progress.ProgressTable.create(plan.name, collections, list(ignored)).render()


# ─────────────────────────── 落盘 ───────────────────────────

def apply(plan: InitPlan, log: Optional[EventLog] = None) -> dict[str, Any]:
    """按计划建目录、写文件。幂等：目录已存在就跳过。"""
    plan.batch_dir.mkdir(parents=True, exist_ok=True)
    created_dirs = 0
    for d in plan.dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created_dirs += 1
    for path, content in plan.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    if log is not None:
        log.emit("init", DONE, collections=plan.collections,
                 batch_dir=str(plan.batch_dir), created_dirs=created_dirs)

    return {
        "ok": True,
        **plan.as_dict(),
        "created_dirs": created_dirs,
    }


# ─────────────────────────── 给已有批次加合集 ───────────────────────────

#: `game.yaml` 里 `collections:` 那一行。只做行级替换，**不做 YAML 往返** ——
#: 往返会抹掉人写的注释，那是本项目的冻结规则。
_COLLECTIONS_LINE_RE = re.compile(r"^(collections:\s*)(\d+)(\s*)$", re.MULTILINE)


def add_collections(project: "context.Project", names: list[str], *,
                    log: Optional[EventLog] = None) -> dict[str, Any]:
    """给已有批次补建合集目录，并在进度表里追加行。

    场景：2026-12 先做了 3 个合集就交付了，过几天继续做 4、5 个。

    - 只补缺的子目录，已有的一个不动
    - 进度表追加行（已有的行原样保留）
    - `game.yaml` 的 `collections` 更新到最大序号（行级替换，不碰注释）
    - 幂等：名字都存在时什么都不改，如实报"已存在"

    Raises:
        InitError: 批次不存在 / 名字不合法 / 一个名字都没给
    """
    cleaned: list[str] = []
    for raw in names:
        name = str(raw).strip()
        if not name:
            continue
        if context.collection_index(name) is None:
            raise InitError("bad_collection_name",
                            f"合集名不合法：{name!r}（应形如「合集四」「合集十二」）")
        if name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        raise InitError("no_collections", "没有指定要加哪些合集",
                        hint="例如：vedio init --add 合集四,合集五")

    batch_dir = project.batch_dir
    if not (batch_dir / RULES_FILE).is_file():
        raise InitError("batch_not_found", f"批次不存在：{batch_dir}",
                        hint="先正常建批次（不带 --add）")

    created_dirs = 0
    for name in cleaned:
        for sub in (None, *COLLECTION_TREE):
            d = batch_dir / "合集" / name if sub is None else batch_dir / "合集" / name / sub
            if not d.is_dir():
                d.mkdir(parents=True, exist_ok=True)
                created_dirs += 1

    # 进度表：追加行
    ignored = project.ignored_collections()
    result = progress.add_collections(batch_dir / progress.FILE_NAME,
                                      project.name, cleaned, ignored)

    # game.yaml 的 collections 更新到最大序号
    bumped = _bump_collections(batch_dir / RULES_FILE,
                               max(context.collection_index(n) for n in cleaned))

    if log is not None:
        log.emit("init", DONE, mode="add", collections=cleaned,
                 created_dirs=created_dirs,
                 progress_added=result["added"], progress_rebuilt=result["rebuilt"],
                 collections_field=bumped)

    return {
        "ok": True,
        "mode": "add",
        "name": project.name,
        "batch_dir": str(batch_dir),
        "requested": cleaned,
        "added": result["added"],
        "already_present": result["existing"],
        "created_dirs": created_dirs,
        "progress_file": str(batch_dir / progress.FILE_NAME),
        "progress_rebuilt": result["rebuilt"],
        "collections_field": bumped,
    }


def _bump_collections(rules_path: Path, minimum: int) -> Optional[int]:
    """把 `collections:` 拉到至少 `minimum`。返回新值（没变则 None）。

    只替换那一行数字，**不重写整个 YAML** —— PyYAML 往返会把注释抹掉。
    """
    try:
        text = rules_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _COLLECTIONS_LINE_RE.search(text)
    if match is None:
        return None
    current = int(match.group(2))
    if current >= minimum:
        return None
    new_text = _COLLECTIONS_LINE_RE.sub(
        lambda m: f"{m.group(1)}{minimum}{m.group(3)}", text, count=1)
    rules_path.write_text(new_text, encoding="utf-8", newline="\n")
    return minimum
