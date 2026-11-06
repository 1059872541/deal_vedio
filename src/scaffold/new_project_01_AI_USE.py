#!/usr/bin/env python3
"""
工具: new_project_01_AI_USE.py
用途: 创建/管理视频项目的目录结构（AI 调用版）
路径: src/scaffold/new_project_01_AI_USE.py

=== 何时使用 ===
- 用户说"创建新视频项目"、"新建游戏项目" → 传 game_name + [参数]
- 用户说"追加合集"、"再加5个合集" → 传 game_name --add-collections N
- 用户说"看看有哪些合集"、"列出合集" → 传 game_name --list
- 用户说"预览创建结果"、"试运行" → 加 --dry-run

=== 何时不用 ===
- 用户要处理视频文件本身（拼接、字幕、水印等）
- 用户要上传文件到网盘

=== 参数列表 ===

定位参数:
  game_name                  游戏名称（可选，省略时进入交互模式）

目录控制:
  --root / -r     PATH      工作区根目录（默认 D:/VedioRecords/工作区）
  --depth / -d    1|2|3|4   目录创建深度，默认 4
  --collections / -c  INT   合集数量（默认配置值10；0=不创建合集）

合集操作:
  --add-collections     INT  批量追加N个合集（名称递增：合集十一、合集十二...）
  --add-collection / -a      追加单个合集（兼容旧版）
  --collection-name     STR  指定合集名（搭配 --add-collection 使用）
  --list / -l                列出指定项目的所有合集

输出控制:
  --json                     结构化 JSON 输出（供 AI 解析，见下方返回格式）
  --quiet / -q               安静模式，仅输出结果摘要

其他:
  --dry-run / -n             试运行，只打印不执行
  --force / -f               目标目录已存在时仍创建内部结构
  --target / -t        STR   目标目录名称（跳过交互选择）
  --config              PATH 指定配置文件路径
  --show-config              显示当前配置并退出

=== depth 层级说明 ===
  depth=1  仅创建游戏目录
  depth=2  + game.yaml + 术语库/ 片头/ 片尾/ 素材库/ 合集/
  depth=3  + 合集一/ 合集二/...（空目录，无子目录）
  depth=4  + 合集一/素材/ 剪辑/ 成片/（完整结构，默认）

=== JSON 返回格式（--json） ===

成功时:
  {"status":"ok", "action":"init_game",
   "game_name":"泰拉瑞亚", "game_path":"D:/.../泰拉瑞亚",
   "depth":4, "collections":10, "created_count":67,
   "created":["目录: ...game.yaml", "目录: ...术语库/", ...]}

批量追加时:
  {"status":"ok", "action":"add_collections",
   "game_name":"泰拉瑞亚", "added_count":3,
   "added_names":["合集十一","合集十二","合集十三"],
   "created_count":9, "created":[...]}

出错时:
  {"status":"error", "action":"init_game",
   "game_name":"泰拉瑞亚", "error_type":"already_exists",
   "errors":["游戏已存在: D:/.../泰拉瑞亚"]}

=== 调用示例 ===
  python new_project_01_AI_USE.py 泰拉瑞亚 --json
  python new_project_01_AI_USE.py 我的世界 --depth 3 --collections 5 --json
  python new_project_01_AI_USE.py 我的世界 --add-collections 3 --json
  python new_project_01_AI_USE.py 我的世界 --list --json
  python新项目 泰拉瑞亚 --root E:/Videos --depth 2 --collections 0 --quiet
"""

import os
import sys
import json as json_module
import argparse
import io
from pathlib import Path
from datetime import datetime

# 修正 Windows 终端 Unicode 输出（解决 GBK 编码无法打印 ✓ ✗ 的问题）
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 添加项目根目录到路径（用于导入其他模块）
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 尝试导入yaml，无则使用内嵌配置
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# ============== 默认配置 ==============

DEFAULT_CONFIG = {
    "workspace": {
        "root": "D:/VedioRecords/工作区"
    },
    "scaffold": {
        "game_structure": [
            "game.yaml",
            "术语库/",
            "片头/",
            "片尾/",
            "素材库/",
            "合集/",
            "log/"
        ],
        "collection_structure": [
            "成片/",
            "素材/",
            "剪辑/"
        ],
        "default_collections": 10
    }
}

GAME_YAML_TEMPLATE = """# {game_name} 游戏配置
# 生成时间: {timestamp}

naming:
  collection_names:
    # 剪辑完成后填写，如 "合集一": "新手教程篇"
{collection_entries}

templates:
  intro_mapping:
    "default": null  # 请填写默认片头路径，如 "片头/通用片头.mp4"

  outro: null        # 请填写片尾路径，如 "片尾/固定结尾.mp4"

terminology:
  hotwords: "术语库/default_terms.txt"  # 请创建或复制其他游戏术语库
"""


# ============== 核心类 ==============

class ScaffoldEngine:
    """目录脚手架引擎"""

    def __init__(self, config_path: Path = None):
        self.config = self._load_config(config_path)
        self.workspace_root = Path(self.config["workspace"]["root"])
        self.scaffold = self.config["scaffold"]

    def _load_config(self, config_path: Path = None) -> dict:
        """加载配置，优先级：指定路径 > 项目配置 > 内嵌默认"""
        if config_path is None:
            project_global = PROJECT_ROOT / "global.yaml"
            if project_global.exists():
                config_path = project_global

        if config_path is None:
            workspace_global = Path("D:/VedioRecords/global.yaml")
            if workspace_global.exists():
                config_path = workspace_global

        if config_path and config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    if YAML_AVAILABLE:
                        return yaml.safe_load(f)
                    else:
                        return self._parse_simple_yaml(f.read())
            except Exception as e:
                print(f"警告: 加载配置失败 {config_path}: {e}")
                return DEFAULT_CONFIG

        return DEFAULT_CONFIG

    def _parse_simple_yaml(self, content: str) -> dict:
        """简单YAML解析（无PyYAML时的备用）"""
        return DEFAULT_CONFIG

    # ────────── 核心创建方法 ──────────

    def init_game(self, game_name: str, dry_run: bool = False,
                  exist_ok: bool = False, depth: int = 4,
                  num_collections: int = None) -> dict:
        """
        初始化游戏工作区（支持层级深度控制）

        参数:
            game_name:       游戏名称
            dry_run:         试运行模式
            exist_ok:        目标目录已存在时仍尝试创建
            depth:           创建深度 1~4
            num_collections: 合集数量（None=使用配置默认值，0=不创建合集）
        """
        internal_created = []
        internal_errors = []

        # 确定合集数量
        actual_num = (num_collections if num_collections is not None
                      else self.scaffold["default_collections"])

        if not self._ensure_workspace():
            return self._make_result(game_name, None, internal_created,
                                     internal_errors, dry_run,
                                     extra={"error_type": "workspace_failed"})

        game_path = self.workspace_root / game_name

        if game_path.exists() and not exist_ok:
            return self._make_result(game_name, str(game_path), internal_created,
                                     [f"游戏已存在: {game_path}"], dry_run,
                                     extra={"error_type": "already_exists"})

        # depth >= 1: 确保游戏目录存在
        if depth >= 1:
            if dry_run:
                internal_created.append(f"[DRY-RUN] 目录: {game_path}")
            else:
                game_path.mkdir(parents=True, exist_ok=True)
                internal_created.append(f"目录: {game_path}")

        # depth >= 2: 创建游戏级目录结构
        if depth >= 2:
            for item in self.scaffold["game_structure"]:
                item_path = game_path / item
                self._create_item(item_path, item, internal_created,
                                  internal_errors, dry_run,
                                  num_collections=actual_num,
                                  exist_ok=exist_ok)

        # depth >= 3: 创建合集目录
        if depth >= 3 and actual_num > 0:
            for i in range(1, actual_num + 1):
                collection_name = f"合集{self._number_to_chinese(i)}"
                collection_path = game_path / "合集" / collection_name

                if depth >= 4:
                    # 深度4：合集目录 + 子目录
                    if dry_run:
                        internal_created.append(f"[DRY-RUN] 目录: {collection_path}")
                    else:
                        collection_path.mkdir(parents=True, exist_ok=True)
                        internal_created.append(f"目录: {collection_path}")
                    for sub_item in self.scaffold["collection_structure"]:
                        sub_path = collection_path / sub_item
                        self._create_item(sub_path, sub_item, internal_created,
                                          internal_errors, dry_run, is_collection=True)
                else:
                    # 深度3：只创建合集目录本身
                    if dry_run:
                        internal_created.append(f"[DRY-RUN] 目录: {collection_path}")
                    else:
                        collection_path.mkdir(parents=True, exist_ok=True)
                        internal_created.append(f"目录: {collection_path}")

        return self._make_result(game_name, str(game_path), internal_created,
                                 internal_errors, dry_run,
                                 extra={"depth": depth, "collections": actual_num})

    def add_collections(self, game_name: str, count: int = 1,
                        dry_run: bool = False) -> dict:
        """
        为已有游戏批量追加合集

        参数:
            game_name: 游戏名称
            count:     追加数量
            dry_run:   试运行模式
        """
        internal_created = []
        internal_errors = []

        game_path = self.workspace_root / game_name
        if not game_path.exists():
            return self._make_result(game_name, None, internal_created,
                                     [f"游戏不存在: {game_path}"], dry_run,
                                     extra={"error_type": "not_found"})

        existing = self._list_existing_collections(game_path)
        start_num = len(existing) + 1
        added_names = []

        for offset in range(count):
            num = start_num + offset
            collection_name = f"合集{self._number_to_chinese(num)}"
            collection_path = game_path / "合集" / collection_name

            if collection_path.exists():
                internal_created.append(f"跳过（已存在）: {collection_name}")
                continue

            for sub_item in self.scaffold["collection_structure"]:
                sub_path = collection_path / sub_item
                self._create_item(sub_path, sub_item, internal_created,
                                  internal_errors, dry_run, is_collection=True)
            added_names.append(collection_name)

        return self._make_result(game_name, str(game_path), internal_created,
                                 internal_errors, dry_run,
                                 extra={"added_count": len(added_names),
                                        "added_names": added_names})

    def add_collection(self, game_name: str, collection_name: str = None,
                       dry_run: bool = False) -> dict:
        """为已有游戏追加单个合集（兼容旧版）"""
        internal_created = []
        internal_errors = []

        game_path = self.workspace_root / game_name
        if not game_path.exists():
            return self._make_result(game_name, None, internal_created,
                                     [f"游戏不存在: {game_path}"], dry_run,
                                     extra={"error_type": "not_found"})

        if collection_name is None:
            existing = self._list_existing_collections(game_path)
            next_num = len(existing) + 1
            collection_name = f"合集{self._number_to_chinese(next_num)}"

        collection_path = game_path / "合集" / collection_name
        if collection_path.exists():
            return self._make_result(game_name, str(game_path), internal_created,
                                     [f"合集已存在: {collection_path}"], dry_run,
                                     extra={"error_type": "collection_exists"})

        for sub_item in self.scaffold["collection_structure"]:
            sub_path = collection_path / sub_item
            self._create_item(sub_path, sub_item, internal_created,
                              internal_errors, dry_run, is_collection=True)

        return self._make_result(game_name, str(game_path), internal_created,
                                 internal_errors, dry_run,
                                 extra={"collection_name": collection_name})

    def list_collections(self, game_name: str) -> list:
        """列出游戏的所有合集"""
        game_path = self.workspace_root / game_name
        if not game_path.exists():
            return []
        return self._list_existing_collections(game_path)

    # ────────── 内部工具方法 ──────────

    def _make_result(self, game_name: str, game_path: str,
                     created: list, errors: list, dry_run: bool,
                     extra: dict = None) -> dict:
        """统一构建返回字典"""
        result = {
            "game_name": game_name,
            "game_path": game_path,
            "created": created,
            "errors": errors,
            "dry_run": dry_run,
        }
        if extra:
            result.update(extra)
        return result

    def _create_item(self, item_path: Path, item_name: str,
                     created_list: list, errors_list: list,
                     dry_run: bool, is_collection: bool = False,
                     num_collections: int = None,
                     exist_ok: bool = False) -> bool:
        """创建单个文件或目录

        参数:
            exist_ok: 文件已存在时跳过，不覆盖（目录不受影响，自带 exist_ok）
        """
        try:
            if item_name.endswith("/"):
                if dry_run:
                    created_list.append(f"[DRY-RUN] 目录: {item_path}")
                else:
                    item_path.mkdir(parents=True, exist_ok=True)
                    created_list.append(f"{'  ' if is_collection else ''}目录: {item_path}")
            else:
                if item_path.exists() and exist_ok:
                    return True  # 文件已存在，跳过
                if dry_run:
                    created_list.append(f"[DRY-RUN] 文件: {item_path}")
                else:
                    item_path.parent.mkdir(parents=True, exist_ok=True)
                    content = self._generate_file_content(item_name, item_path,
                                                          num_collections)
                    item_path.write_text(content, encoding="utf-8")
                    created_list.append(f"{'  ' if is_collection else ''}文件: {item_path}")
            return True
        except Exception as e:
            errors_list.append(f"失败 {item_path}: {e}")
            return False

    def _generate_file_content(self, filename: str, filepath: Path,
                               num_collections: int = None) -> str:
        """根据文件名生成默认内容"""
        if filename == "game.yaml":
            game_name = filepath.parent.name
            return self._generate_game_yaml(game_name, num_collections)
        return ""

    def _generate_game_yaml(self, game_name: str,
                            num_collections: int = None) -> str:
        """生成 game.yaml 内容"""
        count = (num_collections if num_collections is not None
                 else self.scaffold["default_collections"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entries = []
        for i in range(1, count + 1):
            cn = self._number_to_chinese(i)
            entries.append(f'    "合集{cn}": null')

        return GAME_YAML_TEMPLATE.format(
            game_name=game_name,
            timestamp=timestamp,
            collection_entries="\n".join(entries)
        )

    def _ensure_workspace(self) -> bool:
        """确保工作区根目录存在"""
        try:
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False

    def _number_to_chinese(self, num: int) -> str:
        """数字转中文（1-99）"""
        chinese_nums = "零一二三四五六七八九十"
        if num <= 10:
            return chinese_nums[num]
        elif num < 20:
            return "十" + (chinese_nums[num - 10] if num > 10 else "")
        elif num < 100:
            tens = num // 10
            ones = num % 10
            if ones == 0:
                return chinese_nums[tens] + "十"
            else:
                return chinese_nums[tens] + "十" + chinese_nums[ones]
        return str(num)

    def _list_existing_collections(self, game_path: Path) -> list:
        """列出已有合集"""
        collections_dir = game_path / "合集"
        if not collections_dir.exists():
            return []

        collections = []
        for item in collections_dir.iterdir():
            if item.is_dir() and item.name.startswith("合集"):
                collections.append(item.name)

        def sort_key(name):
            num_part = name.replace("合集", "")
            mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                       "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            if num_part in mapping:
                return mapping[num_part]
            return 0

        return sorted(collections, key=sort_key)

    def print_config(self):
        """打印当前配置（调试用）"""
        print(f"工作区根目录: {self.workspace_root}")
        print(f"默认合集数: {self.scaffold['default_collections']}")
        print(f"游戏级结构: {self.scaffold['game_structure']}")
        print(f"合集级结构: {self.scaffold['collection_structure']}")


# ============== 输出处理 ==============

def format_result_for_ai(result: dict, dry_run: bool) -> dict:
    """将引擎返回结果转换为 AI 友好格式"""
    status = "ok"
    if result.get("errors"):
        status = "error"

    # 检测是否有实际创建内容
    has_added = "added_count" in result or "added_names" in result
    collection_name = result.get("collection_name")

    ai_output = {
        "status": status,
        "game_name": result.get("game_name"),
        "game_path": result.get("game_path"),
        "dry_run": dry_run,
    }

    if has_added:
        ai_output["action"] = "add_collections"
        ai_output["added_count"] = result.get("added_count", 0)
        ai_output["added_names"] = result.get("added_names", [])
    elif collection_name:
        ai_output["action"] = "add_collection"
        ai_output["collection_name"] = collection_name
    else:
        ai_output["action"] = "init_game"
        ai_output["depth"] = result.get("depth", 4)
        ai_output["collections"] = result.get("collections", 0)

    ai_output["created_count"] = len(result.get("created", []))
    if result.get("created"):
        ai_output["created"] = result["created"]

    if result.get("errors"):
        ai_output["errors"] = result["errors"]
        ai_output["error_type"] = result.get("error_type", "unknown")

    return ai_output


def print_banner():
    print("=" * 50)
    print("  视频工作区目录脚手架 (AI 调用版)")
    print(f"  项目: {PROJECT_ROOT}")
    print("=" * 50)


def print_result(result: dict, json_mode: bool = False, quiet: bool = False):
    """智能输出：json_mode 输出 JSON，否则输出人类文本"""

    dry_run = result.get("dry_run", False)

    if json_mode:
        # JSON 模式：只输出一个 JSON 对象
        ai_output = format_result_for_ai(result, dry_run)
        print(json_module.dumps(ai_output, ensure_ascii=False, indent=2))
        return

    if quiet:
        # 安静模式：精简输出
        if result.get("errors"):
            for e in result["errors"]:
                print(f"✗ {e}")
        else:
            created_count = len(result.get("created", []))
            print(f"✓ {result.get('game_name', '?')} 完成，创建 {created_count} 项")
        return

    # 人类友好模式
    print("\n" + "-" * 50)
    if dry_run:
        print("[试运行模式] 未实际创建")
        print("-" * 50)

    print(f"游戏: {result.get('game_name')}")
    if result.get("game_path"):
        print(f"路径: {result['game_path']}")

    # 合集追加信息
    added_names = result.get("added_names")
    if added_names:
        print(f"批量追加 {len(added_names)} 个合集:")
        for name in added_names:
            print(f"  + {name}")
    elif result.get("collection_name"):
        print(f"合集: {result['collection_name']}")
    else:
        depth = result.get("depth")
        collections = result.get("collections")
        if depth:
            print(f"创建深度: depth={depth}")
        if collections is not None:
            print(f"合集数量: {collections}")

    print("-" * 50)

    if result.get("created"):
        print(f"\n✓ 创建 ({len(result['created'])} 项):")
        for item in result["created"]:
            print(f"  {item}")

    if result.get("errors"):
        print(f"\n✗ 错误 ({len(result['errors'])} 项):")
        for item in result["errors"]:
            print(f"  {item}")
        sys.exit(1)
    else:
        print("\n✓ 完成")
        if not added_names and not result.get("collection_name") and result.get("game_path"):
            print(f"\n下一步:")
            print(f"  1. 放置片头片尾到: {Path(result['game_path']) / '片头'}")
            print(f"  2. 编辑 game.yaml 配置合集名称")
            print(f"  3. 录制素材到合集一/素材/")


# ============== 交互式选择逻辑（AI版备用） ==============

def scan_subdirs(root: Path, max_depth: int = 1) -> list[dict]:
    """扫描子目录（简版）"""
    if not root.exists():
        return []
    result = []
    def scan(parent, collector, depth):
        if depth >= max_depth:
            return
        try:
            for child in sorted([p for p in parent.iterdir() if p.is_dir()], key=lambda p: p.name):
                node = {"path": child, "depth": depth + 1, "children": []}
                collector.append(node)
                scan(child, node["children"], depth + 1)
        except PermissionError:
            pass
    scan(root, result, 0)
    return result


def prompt_game_name(engine: ScaffoldEngine) -> str:
    """交互式输入游戏名称"""
    while True:
        name = input("\n请输入游戏名称: ").strip()
        if not name:
            print("名称不能为空。")
            continue
        game_path = engine.workspace_root / name
        if game_path.exists():
            print(f"游戏「{name}」已存在: {game_path}")
            again = input("换一个名称？(y/n): ").strip().lower()
            if again == "y":
                continue
            return None
        return name


def interactive_select_target(engine: ScaffoldEngine, dry_run: bool):
    """交互式选择（AI版简化保留）"""
    root = engine.workspace_root
    if not root.exists():
        print(f"\n工作区根目录不存在: {root}")
        choice = input("是否创建根目录并新建项目？(y/n, 默认 y): ").strip().lower()
        if choice == "n":
            sys.exit(0)
        root.mkdir(parents=True, exist_ok=True)
        game_name = prompt_game_name(engine)
        if game_name is None:
            return {"game_name": None, "errors": ["用户取消操作"]}
        return engine.init_game(game_name, dry_run)

    tree = scan_subdirs(root, 1)
    if not tree:
        print("\n工作区根目录下没有子目录。")
        game_name = prompt_game_name(engine)
        if game_name is None:
            return {"game_name": None, "errors": ["用户取消操作"]}
        return engine.init_game(game_name, dry_run)

    while True:
        print(f"\n工作区根目录: {root}\n")
        print("已有的项目:")
        for i, node in enumerate(tree):
            print(f"  {i+1}. {node['path'].name}")
        print(f"  {len(tree)+1}. <创建新项目>")
        print(f"  0. 退出")

        raw = input(f"\n请选择 (0-{len(tree)+1}): ").strip()
        if raw == "0":
            sys.exit(0)
        try:
            idx = int(raw)
        except ValueError:
            print("无效输入。")
            continue

        if 1 <= idx <= len(tree):
            selected = tree[idx - 1]
            game_name = selected["path"].name
            has_structure = (selected["path"] / "game.yaml").exists()
            if has_structure:
                print(f"项目「{game_name}」已初始化。使用 --add-collections 追加合集。")
                collections = engine.list_collections(game_name)
                if collections:
                    print(f"现有合集: {', '.join(collections)}")
                return None
            else:
                print(f"\n目标目录: {selected['path']}")
                confirm = input("是否在其中创建工作区结构？(y/n, 默认 y): ").strip().lower()
                if confirm == "n":
                    continue
                return engine.init_game(game_name, dry_run, exist_ok=True)
        elif idx == len(tree) + 1:
            game_name = prompt_game_name(engine)
            if game_name is None:
                continue
            return engine.init_game(game_name, dry_run)
        else:
            print("序号超出范围。")


# ============== CLI ==============

def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="视频工作区目录脚手架（AI 调用版）— 参数驱动，非交互为主",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
AI 调用示例:
  python new_project_01_AI_USE.py 泰拉瑞亚 --json
  python new_project_01_AI_USE.py 我的世界 --depth 3 --collections 5 --json --quiet
  python new_project_01_AI_USE.py 我的世界 --add-collections 3 --json
  python new_project_01_AI_USE.py 测试项目 --depth 1 --collections 0
        """
    )

    # ── 定位参数 ──
    parser.add_argument("game_name", nargs="?",
                        help="游戏名称（省略时进入交互模式）")

    # ── 目录控制 ──
    parser.add_argument("--root", "-r", default="",
                        help="工作区根目录路径（覆盖默认配置中的路径）")
    parser.add_argument("--depth", "-d", type=int, default=4, choices=[1, 2, 3, 4],
                        help="目录创建深度: 1=仅游戏目录 2=+顶层结构 3=+合集空目录 4=完整结构（默认）")
    parser.add_argument("--collections", "-c", type=int, default=None,
                        help="创建合集数量（默认使用配置值；0=不创建合集）")

    # ── 合集操作 ──
    parser.add_argument("--add-collections", type=int, default=0,
                        help="批量追加N个合集（名称自动递增：合集十一、合集十二...）")
    parser.add_argument("--add-collection", "-a", action="store_true",
                        help="追加单个合集（兼容旧版）")
    parser.add_argument("--collection-name",
                        help="指定合集名（搭配 --add-collection 使用）")
    parser.add_argument("--list", "-l", action="store_true",
                        help="列出所有合集")

    # ── 输出控制 ──
    parser.add_argument("--json", action="store_true",
                        help="JSON 格式输出（供 AI 解析）")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="安静模式，精简输出")

    # ── 其他 ──
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="试运行，只打印不执行")
    parser.add_argument("--force", "-f", action="store_true",
                        help="目标目录已存在时仍创建内部结构（相当于 exist_ok）")
    parser.add_argument("--target", "-t", default="",
                        help="目标目录名称（跳过交互选择）")
    parser.add_argument("--config", help="指定配置文件路径")
    parser.add_argument("--show-config", action="store_true",
                        help="显示当前配置并退出")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # ── 加载配置 ──
    config_path = None
    if args.config:
        config_path = Path(args.config)
    else:
        project_config = PROJECT_ROOT / "global.yaml"
        if project_config.exists():
            config_path = project_config

    engine = ScaffoldEngine(config_path)

    # ── 覆盖工作区根目录 ──
    if args.root:
        engine.workspace_root = Path(args.root)
        engine.config["workspace"]["root"] = args.root

    # ── 输出模式 ──
    json_mode = args.json
    quiet = args.quiet

    # ── 调试信息 ──
    if args.show_config:
        if json_mode:
            print(json_module.dumps({
                "workspace_root": str(engine.workspace_root),
                "default_collections": engine.scaffold["default_collections"],
                "game_structure": engine.scaffold["game_structure"],
                "collection_structure": engine.scaffold["collection_structure"],
            }, ensure_ascii=False, indent=2))
        else:
            engine.print_config()
        return

    # ── 确定目标游戏名称 ──
    game_name = None
    if args.target:
        game_name = args.target.strip()
    elif args.game_name:
        game_name = args.game_name

    # ── 执行操作 ──

    # 场景 A: 列出合集
    if args.list:
        if not game_name:
            msg = "--list 需要指定游戏名称或 --target"
            if json_mode:
                print(json_module.dumps({"status": "error", "errors": [msg]}, ensure_ascii=False))
            else:
                print(f"错误: {msg}")
            sys.exit(1)
        collections = engine.list_collections(game_name)
        if json_mode:
            print(json_module.dumps({
                "status": "ok",
                "game_name": game_name,
                "collections": collections,
                "count": len(collections),
            }, ensure_ascii=False, indent=2))
        else:
            if not collections:
                print(f"项目「{game_name}」不存在或暂无合集。")
            else:
                print(f"\n{game_name} 合集列表 ({len(collections)} 个):")
                for c in collections:
                    print(f"  - {c}")
        return

    # 场景 B: 批量追加合集
    if args.add_collections > 0:
        if not game_name:
            msg = "--add-collections 需要指定游戏名称或 --target"
            if json_mode:
                print(json_module.dumps({"status": "error", "errors": [msg]}, ensure_ascii=False))
            else:
                print(f"错误: {msg}")
            sys.exit(1)
        if not quiet and not json_mode:
            print_banner()
        result = engine.add_collections(game_name, args.add_collections, args.dry_run)
        print_result(result, json_mode=json_mode, quiet=quiet)
        return

    # 场景 C: 追加单个合集
    if args.add_collection:
        if not game_name:
            msg = "--add-collection 需要指定游戏名称或 --target"
            if json_mode:
                print(json_module.dumps({"status": "error", "errors": [msg]}, ensure_ascii=False))
            else:
                print(f"错误: {msg}")
            sys.exit(1)
        if not quiet and not json_mode:
            print_banner()
        result = engine.add_collection(game_name, args.collection_name, args.dry_run)
        print_result(result, json_mode=json_mode, quiet=quiet)
        return

    # 场景 D: 创建新项目
    if game_name:
        if not quiet and not json_mode:
            print_banner()
        result = engine.init_game(
            game_name,
            dry_run=args.dry_run,
            exist_ok=args.force,
            depth=args.depth,
            num_collections=args.collections,
        )
        print_result(result, json_mode=json_mode, quiet=quiet)
        return

    # 场景 E: 交互模式（无参数时的后备）
    if not quiet:
        print_banner()
    result = interactive_select_target(engine, args.dry_run)
    if result:
        print_result(result, json_mode=json_mode, quiet=quiet)


if __name__ == "__main__":
    main()
