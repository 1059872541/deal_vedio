# -*- coding: utf-8 -*-
"""
字幕纠正 Agent 状态定义
"""
from typing import Optional, Literal
from pydantic import BaseModel, Field


class SubtitleAgentState(BaseModel):
    """字幕纠正 Agent 状态"""
    
    # 用户输入
    target_dir: str = Field(description="目标目录路径")
    user_prompt: str = Field(description="用户提示词，包含大主题和具体内容")
    
    # 解析结果（由 parse_input 节点填充）
    game_name: Optional[str] = Field(default="", description="游戏名称")
    main_topic: Optional[str] = Field(default="", description="大主题（如暮色森林）")
    specific_content: Optional[str] = Field(default="", description="具体内容（如地牢探索与BOSS战斗）")
    subtitle_file: Optional[str] = Field(default="", description="字幕文件路径")
    
    # 知识库状态
    knowledge_file: Optional[str] = Field(default="", description="大主题知识库文件路径")
    knowledge_built: bool = Field(default=False, description="大主题知识库是否已构建")
    
    # 处理结果
    ordered_file: Optional[str] = Field(default="", description="带行号的字幕文件")
    corrected_file: Optional[str] = Field(default="", description="纠正后的字幕文件")
    final_srt_file: Optional[str] = Field(default="", description="最终的SRT文件")
    
    # 状态追踪
    status: Literal["pending", "running", "completed", "error"] = Field(
        default="pending",
        description="处理状态"
    )
    message: str = Field(default="", description="状态消息或错误信息")
    
    # API 调用记录
    api_calls: int = Field(default=0, description="API调用次数")
    tokens_used: Optional[int] = Field(default=None, description="使用的Token数")
    
    # 标题生成
    title_file: str = Field(default="titles/所有合集标题列表.md", description="标题文件路径")
    generated_titles: Optional[list[str]] = Field(default=None, description="生成的标题列表")

    # 性能追踪
    node_timings: dict = Field(default_factory=dict, description="各节点耗时（秒）")
    api_details: list = Field(default_factory=list, description="API调用明细")