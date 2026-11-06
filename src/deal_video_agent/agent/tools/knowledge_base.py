# -*- coding: utf-8 -*-
"""
知识库管理工具
支持两层结构：
1. 大主题（如暮色森林）- 长期维护，多合集复用
2. 具体内容（如地牢探索与BOSS战斗）- 当前合集的内容
"""
import os
import re
from pathlib import Path
from typing import Optional, List, Tuple


class KnowledgeBaseManager:
    """知识库管理器"""
    
    def __init__(self, base_dir: str):
        """
        初始化知识库管理器
        
        Args:
            base_dir: 知识库根目录，如 <项目根>/src/deal_video_agent/knowledge_base
        """
        self.base_dir = Path(base_dir)
    
    def _extract_topics_from_prompt(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """
        从用户提示词中提取大主题和具体内容
        
        Args:
            prompt: 用户提示词
            
        Returns:
            (大主题, 具体内容)
            例如: "本次视频主要内容关于【暮色森林】的地牢探索与BOSS战斗"
            -> ("暮色森林", "地牢探索与BOSS战斗")
        """
        # 匹配第一个【】作为大主题
        main_topic_match = re.search(r'【(.+?)】', prompt)
        main_topic = None
        specific_content = None
        
        if main_topic_match:
            main_topic = main_topic_match.group(1)
            # 去掉常见后缀
            main_topic = re.sub(r'(模组|内容|主题)$', '', main_topic)
            
            # 提取大主题后的具体内容
            remaining = prompt[main_topic_match.end():].strip()
            if remaining:
                # 取前50个字符作为具体内容描述
                specific_content = remaining[:50]
        
        return main_topic, specific_content
    
    def find_main_topic_kb(self, game_name: str, main_topic: str) -> Optional[str]:
        """
        查找大主题知识库
        
        Args:
            game_name: 游戏名称，如"我的世界"
            main_topic: 大主题，如"暮色森林"
            
        Returns:
            知识库文件路径，如不存在则返回None
        """
        if not main_topic:
            return None
            
        game_dir = self.base_dir / game_name
        if not game_dir.exists():
            return None
        
        # 精确匹配大主题
        exact_file = game_dir / f"{main_topic}.md"
        if exact_file.exists():
            return str(exact_file)
        
        # 模糊匹配
        for f in game_dir.glob("*.md"):
            if main_topic in f.stem:
                return str(f)
        
        return None
    
    def find(self, game_name: str, topic: str) -> Optional[str]:
        """
        查找匹配的知识库文件（兼容旧接口）
        
        Args:
            game_name: 游戏名称
            topic: 内容主题
            
        Returns:
            知识库文件路径
        """
        return self.find_main_topic_kb(game_name, topic)
    
    def find_by_prompt(self, game_name: str, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """
        根据提示词查找知识库
        
        Args:
            game_name: 游戏名称
            prompt: 用户提示词
            
        Returns:
            (大主题知识库路径, 具体内容描述)
        """
        main_topic, specific_content = self._extract_topics_from_prompt(prompt)
        
        if not main_topic:
            return None, None
        
        kb_path = self.find_main_topic_kb(game_name, main_topic)
        return kb_path, specific_content
    
    def find_main_topic_kb_by_prompt(self, game_name: str, prompt: str) -> Optional[str]:
        """
        根据提示词查找大主题知识库（简化接口）
        """
        kb_path, _ = self.find_by_prompt(game_name, prompt)
        return kb_path
    
    def save_main_topic_kb(self, game_name: str, main_topic: str, content: str) -> str:
        """
        保存大主题知识库
        
        Args:
            game_name: 游戏名称
            main_topic: 大主题（如"暮色森林"）
            content: 知识库内容
            
        Returns:
            保存的文件路径
        """
        game_dir = self.base_dir / game_name
        game_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = game_dir / f"{main_topic}.md"
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)
    
    def save(self, game_name: str, topic: str, content: str) -> str:
        """
        保存知识库文件（兼容旧接口）
        """
        return self.save_main_topic_kb(game_name, topic, content)
    
    def exists(self, game_name: str, main_topic: str) -> bool:
        """
        检查大主题知识库是否存在
        """
        return self.find_main_topic_kb(game_name, main_topic) is not None
    
    def list_topics(self, game_name: str) -> List[str]:
        """
        列出指定游戏的所有知识库主题
        """
        game_dir = self.base_dir / game_name
        if not game_dir.exists():
            return []
        
        return [f.stem for f in game_dir.glob("*.md")]


if __name__ == "__main__":
    # 测试代码
    kb = KnowledgeBaseManager(r"D:\study\python\deal_vedio\src\deal_video_agent\knowledge_base")
    
    # 测试查找
    result = kb.find("我的世界", "暮色森林")
    print(f"查找结果: {result}")
    
    # 测试列表
    topics = kb.list_topics("我的世界")
    print(f"知识库列表: {topics}")