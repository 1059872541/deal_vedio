# -*- coding: utf-8 -*-
"""
字幕纠正 Agent 日志系统
使用 structlog 实现结构化日志
"""
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

import structlog


class AgentLogger:
    """Agent执行日志记录器"""
    
    def __init__(self, log_dir: Optional[str] = None):
        """
        初始化日志记录器
        
        Args:
            log_dir: 日志存储目录，默认 deal_video_agent/logs
        """
        if log_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            log_dir = base_dir / "logs"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self._logger: Optional[structlog.BoundLogger] = None
        self._run_id: Optional[str] = None
        self._start_time: Optional[datetime] = None
        self._log_events: list = []  # 用于保存到JSON的日志事件
        
        self._configure_logger()
    
    def _configure_logger(self):
        """配置structlog"""
        # 确保日志目录存在
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置处理器
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.dev.ConsoleRenderer()  # 开发时彩色输出
        ]
        
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
        
        self._logger = structlog.get_logger("subtitle_agent")
    
    def _get_log_file_path(self) -> Path:
        """获取当前运行日志文件路径"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.log_dir / f"agent_run_{timestamp}.json"
    
    def start(self, target_dir: str, user_prompt: str):
        """
        开始记录任务
        
        Args:
            target_dir: 目标目录
            user_prompt: 用户提示词
        """
        self._run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._start_time = datetime.now()
        self._log_events = []  # 重置日志事件列表
        
        self._logger.info(
            "agent_start",
            target_dir=target_dir,
            user_prompt=user_prompt[:100] + "..." if len(user_prompt) > 100 else user_prompt,
            run_id=self._run_id,
        )
        
        return self
    
    def log_parse_result(self, game_name: str, main_topic: str, specific_content: str, subtitle_file: str):
        """记录解析结果"""
        self._logger.info(
            "parse_complete",
            game_name=game_name,
            main_topic=main_topic,
            specific_content=specific_content,
            subtitle_file=subtitle_file,
        )
    
    def log_knowledge_base_check(self, main_topic: str, exists: bool, file_path: str):
        """记录知识库检查结果"""
        self._logger.info(
            "knowledge_base_check",
            main_topic=main_topic,
            exists=exists,
            file_path=file_path,
        )
    
    def log_knowledge_base_built(self, main_topic: str, file_path: str):
        """记录知识库构建结果"""
        self._logger.info(
            "knowledge_base_built",
            main_topic=main_topic,
            file_path=file_path,
        )
    
    def log_add_line_order(self, input_file: str, output_file: str):
        """记录字幕添加行号"""
        self._logger.info(
            "add_line_order",
            input_file=input_file,
            output_file=output_file,
        )
    
    def log_correct_subtitle_start(self, ordered_file: str, knowledge_file: str):
        """记录字幕纠正开始"""
        self._logger.info(
            "correct_subtitle_start",
            ordered_file=ordered_file,
            knowledge_file=knowledge_file,
        )
    
    def log_correct_subtitle_complete(self, corrected_file: str, correction_count: int):
        """记录字幕纠正完成"""
        self._logger.info(
            "correct_subtitle_complete",
            corrected_file=corrected_file,
            correction_count=correction_count,
        )
    
    def log_title_generation_start(self, ordered_file: str):
        """记录标题生成开始"""
        self._logger.info(
            "title_generation_start",
            ordered_file=ordered_file,
        )
    
    def log_title_generation_complete(self, titles_count: int, duplicate_count: int):
        """记录标题生成完成"""
        self._logger.info(
            "title_generation_complete",
            titles_count=titles_count,
            duplicate_count=duplicate_count,
        )
    
    def log_update_srt(self, corrected_file: str, final_srt_file: str):
        """记录SRT更新"""
        self._logger.info(
            "update_srt",
            corrected_file=corrected_file,
            final_srt_file=final_srt_file,
        )
    
    def log_api_call(self, call_type: str, call_count: int, model: str = "deepseek-chat"):
        """记录API调用"""
        self._logger.info(
            "api_call",
            call_type=call_type,
            call_count=call_count,
            model=model,
        )
    
    def log_result(self, status: str, message: str, api_calls: int):
        """记录最终结果"""
        end_time = datetime.now()
        duration = (end_time - self._start_time).total_seconds() if self._start_time else 0
        
        self._logger.info(
            "agent_complete",
            status=status,
            message=message,
            api_calls=api_calls,
            duration_seconds=round(duration, 2),
        )
    
    def log_error(self, stage: str, error: str):
        """记录错误"""
        self._logger.error(
            "agent_error",
            stage=stage,
            error=error,
        )
    
    def save_to_json(self, data: dict = None):
        """保存日志到JSON文件"""
        if data is None:
            data = {"events": self._log_events, "run_id": self._run_id}
        
        log_file = self._get_log_file_path()
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _add_log_event(self, event_type: str, **kwargs):
        """添加日志事件"""
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self._log_events.append(event)


# 全局日志记录器实例
_logger_instance: Optional[AgentLogger] = None


def get_logger(log_dir: Optional[str] = None) -> AgentLogger:
    """获取全局日志记录器实例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = AgentLogger(log_dir)
    return _logger_instance


def reset_logger():
    """重置日志记录器实例"""
    global _logger_instance
    _logger_instance = None