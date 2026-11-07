# -*- coding: utf-8 -*-
"""
标题管理器 - 管理所有合集的标题列表
"""
import os
import re
from pathlib import Path
from typing import Optional


class TitlesManager:
    """标题管理器"""
    
    def __init__(self, base_dir: str, title_file: str = "titles/all_collection_titles.md",
                 game_name: Optional[str] = None):
        """
        初始化标题管理器
        
        Args:
            base_dir: 项目根目录
            title_file: 标题文件名（相对于 base_dir）
            game_name: 游戏名，用于生成一级标题。不传则从文件名反推
                       （`我的世界-2026-06_titles.md` → `我的世界`）
        """
        self.base_dir = Path(base_dir)
        self.title_file = self.base_dir / title_file
        self.game_name = game_name or self._derive_game_name()
        #: 解析时填充：各合集节里的副标题
        self._section_subtitles: dict = {}
        self._ensure_title_file()
    
    #: 批次后缀，用来从标题文件名反推游戏名：``我的世界-2026-06`` → ``我的世界``
    _BATCH_SUFFIX = re.compile(r"-\d{4}-\d{2}$")

    #: 合集小节标题行：``#### 合集一:收集强力变身-上篇``（副标题可省略）
    _SECTION_HEADER = re.compile(r"^####\s*([^:：]+?)\s*(?:[:：]\s*(.*))?$")

    def _derive_game_name(self) -> str:
        """从标题文件名反推游戏名。

        ``titles/我的世界-2026-06_titles.md`` → ``我的世界``
        ``titles/足球在线4-2026-06_titles.md`` → ``足球在线4``
        推不出来就退回文件名主干，宁可难看也不写死。
        """
        stem = self.title_file.stem
        if stem.endswith("_titles"):
            stem = stem[: -len("_titles")]
        stem = self._BATCH_SUFFIX.sub("", stem).strip()
        return stem or self.title_file.stem

    @property
    def _header(self) -> str:
        """文件一级标题。

        原实现三处都写死 ``# 我的世界系列视频标题列表``，导致
        ``足球在线4-2026-06_titles.md`` 的第一行也变成"我的世界"。
        """
        return f"# {self.game_name}系列视频标题列表\n\n"

    @classmethod
    def _parse_section_header(cls, line: str):
        """拆出合集名与副标题。

        ``#### 合集一:收集强力变身-上篇`` → ``("合集一", "收集强力变身-上篇")``
        ``#### 合集一`` → ``("合集一", None)``

        原实现用 ``replace(':', '')`` 把整行变成一个 key，
        副标题被并进名字里，于是覆盖匹配永远失败。
        """
        m = cls._SECTION_HEADER.match(line.strip())
        if not m:
            return line.replace("####", "").strip(), None
        subtitle = (m.group(2) or "").strip()
        return m.group(1).strip(), (subtitle or None)

    def _ensure_title_file(self):
        """确保标题文件存在"""
        if not self.title_file.exists():
            self.title_file.parent.mkdir(parents=True, exist_ok=True)
            self.title_file.write_text(self._header, encoding='utf-8')
    
    def clear_all_titles(self) -> bool:
        """
        清空所有标题（项目初始化时调用）
        
        Returns:
            是否成功
        """
        try:
            self.title_file.write_text(self._header, encoding='utf-8')
            return True
        except Exception as e:
            print(f"清空标题失败: {e}")
            return False
    
    @staticmethod
    def _is_title_line(line: str) -> bool:
        """判断一行是不是"标题"。

        要排除的不只是注释和分隔符，还有 ``公共前缀:波波之我的世界`` ——
        原实现漏了它，导致这条前缀被当成一条已有标题喂给 LLM 做去重，
        既干扰提示词，也会让 ``is_duplicate`` 误判。
        """
        s = line.strip()
        if not s:
            return False
        if s.startswith("#") or s.startswith("---"):
            return False
        if s.startswith("公共前缀"):
            return False
        if s.startswith("**") and s.endswith("**"):
            return False
        return True

    def read_all_titles(self) -> str:
        """
        读取所有已有标题
        
        Returns:
            标题列表的纯文本内容
        """
        if not self.title_file.exists():
            return ""
        
        content = self.title_file.read_text(encoding='utf-8')
        
        titles = [line.strip() for line in content.split('\n') if self._is_title_line(line)]
        
        return '\n'.join(titles)
    
    def read_all_titles_list(self) -> list[str]:
        """
        读取所有已有标题（列表形式）
        
        Returns:
            标题列表
        """
        if not self.title_file.exists():
            return []
        
        content = self.title_file.read_text(encoding='utf-8')
        
        return [line.strip() for line in content.split('\n') if self._is_title_line(line)]
    
    def read_all_titles_set(self) -> set[str]:
        """
        读取所有已有标题（集合形式，O(1) 查找）

        Returns:
            标题集合
        """
        if not self.title_file.exists():
            return set()
        return set(self.read_all_titles_list())

    def check_duplicate(self, new_title: str) -> bool:
        """
        检查标题是否重复（O(1) 哈希查找）

        Args:
            new_title: 新标题

        Returns:
            True 表示重复，False 表示不重复
        """
        existing_titles = self.read_all_titles_set()
        return new_title in existing_titles
    
    def append_titles(self, collection_name: str, titles: list[str], overwrite: bool = True) -> bool:
        """
        追加新合集的标题

        - 新合集：直接追加到文件末尾，不触碰已有内容
        - 已有合集（overwrite=True）：全文重建以替换内容

        Args:
            collection_name: 合集名称（如 "合集九"）
            titles: 标题列表（20个标题）
            overwrite: 是否覆盖已存在的同名合集标题

        Returns:
            是否成功
        """
        if not titles:
            return False

        try:
            # 读取现有内容
            content = ""
            if self.title_file.exists():
                content = self.title_file.read_text(encoding='utf-8')

            # 检查合集是否已存在
            existing_collections = self._parse_all_collections(content)

            if collection_name in existing_collections and overwrite:
                # 同名合集需要覆盖 → 全文重建
                existing_collections[collection_name] = titles
                new_content = self._header
                for name, title_list in existing_collections.items():
                    subtitle = self._section_subtitles.get(name)
                    if subtitle:
                        new_content += f"---\n#### {name}:{subtitle}\n"
                    else:
                        new_content += f"---\n#### {name}:\n"
                    for t in title_list:
                        new_content += f"{t}\n"
                    new_content += "\n"
                self.title_file.write_text(new_content, encoding='utf-8')
            else:
                # 新合集 → 直接追加到末尾，不改动已有内容
                if content.rstrip() and not content.endswith('\n'):
                    content += '\n'
                section = f"---\n#### {collection_name}:\n" + "\n".join(titles) + "\n\n"
                content += section
                self.title_file.write_text(content, encoding='utf-8')

            return True
        except Exception as e:
            print(f"追加标题失败: {e}")
            return False
    
    def _parse_all_collections(self, content: str) -> dict:
        """解析文件中所有合集"""
        collections = {}
        if not content:
            return collections
        
        current_collection = None
        current_titles = []
        
        for line in content.split('\n'):
            line_stripped = line.strip()
            
            if line_stripped.startswith('#### '):
                # 保存上一个合集
                if current_collection and current_titles:
                    collections[current_collection] = current_titles
                
                # 拆出合集名与副标题。原实现把整行（含副标题）当成 key，
                # 于是 "合集一" 永远匹配不上 "合集一收集强力变身-上篇"，
                # overwrite 失效 → 每次重跑都追加一个重复小节。
                current_collection, subtitle = self._parse_section_header(line_stripped)
                self._section_subtitles[current_collection] = subtitle
                current_titles = []
            elif line_stripped and not line_stripped.startswith('#') and not line_stripped.startswith('---'):
                if current_collection:
                    current_titles.append(line_stripped)
        
        # 保存最后一个合集
        if current_collection and current_titles:
            collections[current_collection] = current_titles
        
        return collections
    
    def _remove_collection(self, content: str, collection_name: str) -> str:
        """
        删除指定合集的内容
        
        Args:
            content: 文件内容
            collection_name: 合集名称
            
        Returns:
            删除后的内容
        """
        lines = content.split('\n')
        result_lines = []
        skip_until_next_collection = False
        
        for line in lines:
            # 检查是否是合集标题行
            if line.strip().startswith('#### '):
                if collection_name in line:
                    skip_until_next_collection = True
                    continue
                else:
                    skip_until_next_collection = False
            
            if not skip_until_next_collection:
                result_lines.append(line)
        
        # 清理多余的空行和分隔符
        cleaned_lines = []
        prev_empty = False
        for line in result_lines:
            is_empty = not line.strip()
            if is_empty and prev_empty:
                continue
            cleaned_lines.append(line)
            prev_empty = is_empty
        
        return '\n'.join(cleaned_lines)
    
    def get_collection_titles(self, collection_name: str) -> Optional[list[str]]:
        """
        获取指定合集的标题
        
        Args:
            collection_name: 合集名称
            
        Returns:
            标题列表，如果不存在则返回 None
        """
        if not self.title_file.exists():
            return None
        
        content = self.title_file.read_text(encoding='utf-8')
        
        pattern = rf"####\s*{re.escape(collection_name)}:\s*\n((?:.+\n?)+)"
        match = re.search(pattern, content)
        
        if not match:
            return None
        
        titles_block = match.group(1)
        titles = [line.strip() for line in titles_block.split('\n') if line.strip()]
        
        return titles


if __name__ == "__main__":
    manager = TitlesManager(r"D:\study\python\deal_vedio\src\deal_video_agent")
    
    titles = manager.read_all_titles_list()
    print(f"已有标题数量: {len(titles)}")
    print("\n已有标题:")
    for i, t in enumerate(titles, 1):
        print(f"{i}. {t}")
    
    print("\n检查重复:")
    print(f"'落入积雪中': {manager.check_duplicate('落入积雪中')}")
    print(f"'测试标题123': {manager.check_duplicate('测试标题123')}")
