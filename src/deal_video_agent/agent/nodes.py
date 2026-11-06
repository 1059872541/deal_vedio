# -*- coding: utf-8 -*-
"""
字幕纠正 Agent 节点定义
"""
import os
import re
import time
import functools
from pathlib import Path
from typing import Optional

from .state import SubtitleAgentState
from .tools import (
    DeepSeekClient,
    KnowledgeBaseManager,
    AddLineOrderTool,
    UpdateSRT_tool,
    TitlesManager
)
from .logger import get_logger, reset_logger


# ==================== 日志记录器 ====================

def _get_logger():
    """获取日志记录器"""
    return get_logger()


# ==================== 工具初始化 ====================

# 配置路径
SCRIPT_DIR = Path(__file__).parent.parent  # deal_video_agent 目录
CONFIG_DIR = SCRIPT_DIR / "config.yaml"
PROMPTS_DIR = SCRIPT_DIR / "prompts"       # 修正：deal_video_agent/prompts
KNOWLEDGE_BASE_DIR = SCRIPT_DIR / "knowledge_base"

# 初始化工具
_deepseek_client = None
_knowledge_base_manager = None
_add_line_order_tool = None
_update_srt_tool = None


def _get_deepseek_client() -> DeepSeekClient:
    global _deepseek_client
    if _deepseek_client is None:
        _deepseek_client = DeepSeekClient()
    return _deepseek_client


def _get_knowledge_base_manager() -> KnowledgeBaseManager:
    global _knowledge_base_manager
    if _knowledge_base_manager is None:
        _knowledge_base_manager = KnowledgeBaseManager(str(KNOWLEDGE_BASE_DIR))
    return _knowledge_base_manager


def _get_add_line_order_tool() -> AddLineOrderTool:
    global _add_line_order_tool
    if _add_line_order_tool is None:
        _add_line_order_tool = AddLineOrderTool()
    return _add_line_order_tool


def _get_update_srt_tool() -> UpdateSRT_tool:
    global _update_srt_tool
    if _update_srt_tool is None:
        _update_srt_tool = UpdateSRT_tool()
    return _update_srt_tool


def _get_titles_manager(game_name: Optional[str] = None) -> TitlesManager:
    if game_name:
        title_file = f"titles/{game_name}_titles.md"
    else:
        title_file = "titles/all_collection_titles.md"
    return TitlesManager(str(SCRIPT_DIR), title_file=title_file)


def _load_prompt_template(prompt_type: str, game_name: str = "") -> str:
    """加载提示词模板（支持游戏专属覆写）

    加载顺序：
      1. 读取通用模板 prompts/subtitle_correction.yaml（父类）
      2. 如果存在 prompts/games/{game_name}.yaml，用其字段覆盖通用模板（子类重写）
      3. 返回指定类型的提示词

    游戏专属文件只需写要覆写的字段，未覆写的自动继承通用版。
    """
    import yaml

    base_file = PROMPTS_DIR / "subtitle_correction.yaml"
    if not base_file.exists():
        raise FileNotFoundError(f"提示词文件不存在: {base_file}")

    with open(base_file, 'r', encoding='utf-8') as f:
        prompts = yaml.safe_load(f)

    # 加载游戏专属覆写（如果存在）
    if game_name:
        game_file = PROMPTS_DIR / "games" / f"{game_name}.yaml"
        if game_file.exists():
            with open(game_file, 'r', encoding='utf-8') as f:
                overrides = yaml.safe_load(f)
                if overrides:
                    prompts.update(overrides)

    # 键名与 YAML 字段名直接对应
    if prompt_type in prompts:
        return prompts.get(prompt_type, "")
    raise ValueError(f"未知的提示词类型: {prompt_type}")


# ==================== 节点定义 ====================

# AOP 切面：自动记录节点执行耗时
def trace_node(func):
    """装饰器：记录节点执行耗时，存入 state.node_timings"""
    @functools.wraps(func)
    def wrapper(state: SubtitleAgentState) -> SubtitleAgentState:
        start = time.time()
        result = func(state)
        elapsed = time.time() - start
        result.node_timings[func.__name__] = round(elapsed, 3)
        return result
    return wrapper


@trace_node
def parse_input(state: SubtitleAgentState) -> SubtitleAgentState:
    """
    解析用户输入
    - 提取游戏名：从目录路径
    - 提取大主题和具体内容：从用户提示词
    - 查找字幕文件
    """
    target_dir = state.target_dir
    user_prompt = state.user_prompt
    
    # 1. 提取游戏名（从目录路径）
    game_name = _extract_game_name(target_dir)
    state.game_name = game_name
    
    # 2. 提取大主题和具体内容（从用户提示词）
    kb_manager = _get_knowledge_base_manager()
    main_topic, specific_content = kb_manager._extract_topics_from_prompt(user_prompt)
    state.main_topic = main_topic or ""
    state.specific_content = specific_content or ""
    
    # 3. 查找字幕文件
    subtitle_file = _find_subtitle_file(target_dir)
    if subtitle_file:
        state.subtitle_file = subtitle_file
    else:
        state.status = "error"
        state.message = f"未找到字幕文件，目录: {target_dir}"
        _get_logger().log_error("parse_input", f"未找到字幕文件: {target_dir}")
        return state
    
    # 记录解析结果
    logger = _get_logger()
    # 每次调用 parse_input 时重新开始日志（避免重复）
    reset_logger()
    logger = get_logger()
    logger.start(target_dir, user_prompt)
    
    logger.log_parse_result(
        game_name=game_name,
        main_topic=main_topic or "",
        specific_content=specific_content or "",
        subtitle_file=subtitle_file
    )
    
    state.status = "running"
    state.message = f"解析完成：游戏={game_name}, 大主题={main_topic}, 具体内容={specific_content}"
    
    return state


def _extract_game_name(dir_path: str) -> str:
    """从目录路径中提取游戏名"""
    # 示例路径: D:\VedioRecords\工作区\我的世界\合集六\剪辑\
    # 游戏名通常是工作区下的第一级目录
    path = Path(dir_path)
    
    # 向上查找，找到"工作区"或"游戏素材"等关键词所在层级
    parts = path.parts
    for i, part in enumerate(parts):
        if "工作区" in part or "游戏素材" in part or "剪辑草稿" in part:
            if i + 1 < len(parts):
                return parts[i + 1]
    
    # 如果没找到，返回最后一个目录名
    return parts[-1] if parts else "未知游戏"


def _clean_game_name(raw_name: str) -> str:
    """去掉末尾的日期/版本后缀，返回纯粹的游戏名"""
    # 去掉 -YYYY-MM 或 -YYYY 格式后缀
    return re.sub(r'-\d{4}(?:-\d{2})?$', '', raw_name)


def _extract_content_topic(prompt: str) -> str:
    """从用户提示词中提取内容主题（兼容旧接口）"""
    # 匹配【】中的内容
    match = re.search(r'【(.+?)】', prompt)
    if match:
        topic = match.group(1)
        # 去掉常见后缀
        topic = re.sub(r'(模组|内容|主题)$', '', topic)
        return topic
    
    # 如果没有找到，返回空
    return ""


def _find_subtitle_file(dir_path: str) -> Optional[str]:
    """在目录中查找字幕文件"""
    path = Path(dir_path)
    if not path.exists():
        return None
    
    # 查找 .txt 文件（排除 corrected.txt, xxx_ordered.txt）
    txt_files = []
    for f in path.glob("*.txt"):
        if f.name not in ["corrected.txt"] and "_ordered" not in f.name:
            txt_files.append(f)
    
    if not txt_files:
        return None
    
    # 返回最新的文件
    latest = max(txt_files, key=lambda f: f.stat().st_mtime)
    return str(latest)


@trace_node
def check_knowledge_base(state: SubtitleAgentState) -> SubtitleAgentState:
    """
    检查大主题知识库是否存在
    """
    game_name = state.game_name
    clean_name = _clean_game_name(game_name or "")
    main_topic = state.main_topic

    if not main_topic:
        state.message = "未提取到大主题，跳过知识库检查"
        return state

    # 使用新的方法查找大主题知识库
    kb_manager = _get_knowledge_base_manager()
    knowledge_file = kb_manager.find_main_topic_kb(clean_name, main_topic or "")
    
    # 记录知识库检查结果
    logger = _get_logger()
    logger.log_knowledge_base_check(
        main_topic=main_topic or "",
        exists=bool(knowledge_file),
        file_path=knowledge_file or ""
    )
    
    if knowledge_file:
        state.knowledge_file = knowledge_file
        state.knowledge_built = True
        state.message = f"找到大主题知识库: {knowledge_file}"
    else:
        state.knowledge_file = ""
        state.knowledge_built = False
        state.message = f"未找到大主题知识库，需要构建: {main_topic}"
    
    return state


@trace_node
def build_knowledge_base(state: SubtitleAgentState) -> SubtitleAgentState:
    """
    构建大主题知识库（如需要）
    """
    if state.knowledge_built:
        return state
    
    logger = _get_logger()
    logger.log_knowledge_base_built(
        main_topic=state.main_topic or "",
        file_path=state.knowledge_file or ""
    )
    
    game_name = state.game_name
    clean_name = _clean_game_name(game_name or "")
    main_topic = state.main_topic

    if not main_topic:
        state.status = "error"
        state.message = "无法构建知识库：未指定大主题"
        logger.log_error("build_knowledge_base", "未指定大主题")
        return state

    # 加载提示词模板
    system_prompt = _load_prompt_template("knowledge_building", clean_name)
    system_prompt = system_prompt.format(
        game_name=clean_name,
        content_topic=main_topic
    )

    # 调用 API（使用流式输出，显示进度）
    deepseek = _get_deepseek_client()
    try:
        print("开始构建知识库（流式输出中）...")

        response, usage = deepseek.stream_chat_with_progress(
            system_prompt=system_prompt,
            user_prompt="请开始构建知识库。",
            show_progress=True
        )

        # 保存大主题知识库
        kb_manager = _get_knowledge_base_manager()
        knowledge_file = kb_manager.save_main_topic_kb(clean_name, main_topic, response)

        # 记录API调用
        logger.log_api_call(call_type="build_knowledge_base", call_count=1)
        state.api_details.append({
            "node": "build_knowledge_base",
            "usage": usage
        })
        
        state.knowledge_file = knowledge_file
        state.knowledge_built = True
        state.message = f"知识库构建完成: {knowledge_file}"
        state.api_calls += 1
        
    except Exception as e:
        state.status = "error"
        state.message = f"知识库构建失败: {str(e)}"
        logger.log_error("build_knowledge_base", str(e))
    
    return state


@trace_node
def add_line_order(state: SubtitleAgentState) -> SubtitleAgentState:
    """
    字幕添加行号
    """
    subtitle_file = state.subtitle_file
    logger = _get_logger()
    
    if not subtitle_file:
        state.status = "error"
        state.message = "未找到字幕文件"
        logger.log_error("add_line_order", "未找到字幕文件")
        return state
    
    try:
        tool = _get_add_line_order_tool()
        output_file = tool.run(subtitle_file)
        
        # 记录日志
        logger.log_add_line_order(
            input_file=subtitle_file,
            output_file=output_file
        )
        
        state.ordered_file = output_file
        state.message = f"字幕添加行号完成: {output_file}"
        
    except Exception as e:
        state.status = "error"
        state.message = f"添加行号失败: {str(e)}"
        logger.log_error("add_line_order", str(e))
    
    return state


@trace_node
def correct_subtitle(state: SubtitleAgentState) -> SubtitleAgentState:
    """
    调用 DeepSeek API 进行字幕纠正
    """
    ordered_file = state.ordered_file
    game_name = state.game_name
    clean_name = _clean_game_name(game_name or "")
    main_topic = state.main_topic
    specific_content = state.specific_content
    logger = _get_logger()
    
    if not ordered_file:
        state.status = "error"
        state.message = "未找到带行号的字幕文件"
        logger.log_error("correct_subtitle", "未找到带行号的字幕文件")
        return state
    
    # 记录字幕纠正开始
    logger.log_correct_subtitle_start(
        ordered_file=ordered_file,
        knowledge_file=state.knowledge_file or ""
    )
    
    # 读取字幕内容
    try:
        with open(ordered_file, 'r', encoding='utf-8') as f:
            subtitle_content = f.read()
    except Exception as e:
        state.status = "error"
        state.message = f"读取字幕文件失败: {str(e)}"
        return state
    
    # 读取大主题知识库内容
    knowledge_content = ""
    if state.knowledge_file:
        try:
            with open(state.knowledge_file, 'r', encoding='utf-8') as f:
                knowledge_content = f.read()
        except Exception:
            pass
    
    # 加载提示词模板
    user_prompt_template = _load_prompt_template("subtitle_correction", clean_name)
    user_prompt = user_prompt_template.format(
        subtitle_content=subtitle_content,
        knowledge_content=knowledge_content,
        game_name=clean_name,
        content_topic=main_topic
    )

    # 构建系统提示词（包含大主题和具体内容）
    content_desc = f"{main_topic}的{specific_content}" if specific_content else main_topic
    system_prompt = f"你是游戏资深主播，负责帮我纠正游戏解说视频字幕的问题。游戏：{clean_name}。内容主题：{content_desc}。"
    
    # 调用 API（使用流式输出，显示进度）
    deepseek = _get_deepseek_client()
    try:
        print("开始字幕纠正（流式输出中）...")

        # 流式调用，显示进度
        response, usage = deepseek.stream_chat_with_progress(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            show_progress=True
        )

        # 保存纠正结果
        output_dir = Path(ordered_file).parent
        corrected_file = output_dir / "corrected.txt"

        with open(corrected_file, 'w', encoding='utf-8') as f:
            f.write(response)

        # 计算纠正条数
        correction_count = len([line for line in response.strip().split('\n') if line.strip()])

        # 记录日志
        logger.log_correct_subtitle_complete(
            corrected_file=str(corrected_file),
            correction_count=correction_count
        )
        logger.log_api_call(call_type="correct_subtitle", call_count=1)
        state.api_details.append({
            "node": "correct_subtitle",
            "usage": usage
        })
        
        state.corrected_file = str(corrected_file)
        state.message = f"字幕纠正完成: {corrected_file}"
        state.api_calls += 1
        
    except Exception as e:
        state.status = "error"
        state.message = f"字幕纠正失败: {str(e)}"
        logger.log_error("correct_subtitle", str(e))
    
    return state


@trace_node
def generate_title(state: SubtitleAgentState) -> SubtitleAgentState:
    """
    调用 DeepSeek API 进行标题生成（第2次API调用，复用字幕缓存）
    """
    ordered_file = state.ordered_file
    game_name = state.game_name
    clean_name = _clean_game_name(game_name or "")
    main_topic = state.main_topic
    logger = _get_logger()
    
    if not ordered_file:
        state.status = "error"
        state.message = "未找到带行号的字幕文件"
        logger.log_error("generate_title", "未找到带行号的字幕文件")
        return state
    
    # 记录标题生成开始
    logger.log_title_generation_start(ordered_file=ordered_file)
    
    # 读取字幕内容
    try:
        with open(ordered_file, 'r', encoding='utf-8') as f:
            subtitle_content = f.read()
    except Exception as e:
        state.status = "error"
        state.message = f"读取字幕文件失败: {str(e)}"
        logger.log_error("generate_title", f"读取字幕失败: {str(e)}")
        return state
    
    # 读取已有标题列表
    titles_manager = _get_titles_manager(game_name)
    existing_titles = titles_manager.read_all_titles()
    
    # 加载标题生成提示词模板
    title_prompt_template = _load_prompt_template("title_generation", clean_name)
    user_prompt = title_prompt_template.format(subtitle_content=subtitle_content, existing_titles=existing_titles)

    # 构建系统提示词
    system_prompt = f"你是游戏视频标题助手，负责为{clean_name}游戏视频生成标题。游戏：{clean_name}。当前合集主题：{main_topic}。"
    
    # 调用 API（使用流式输出，显示进度）
    deepseek = _get_deepseek_client()
    try:
        print("\n开始标题生成（流式输出中）...")

        # 流式调用，显示进度
        response, usage = deepseek.stream_chat_with_progress(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            show_progress=True
        )

        # 解析标题列表
        titles = [line.strip() for line in response.strip().split('\n') if line.strip()]
        
        # 检查重复
        duplicate_count = 0
        valid_titles = []
        for title in titles:
            if titles_manager.check_duplicate(title):
                duplicate_count += 1
                print(f"[WARNING] Title duplicate, skipped: {title}")
            else:
                valid_titles.append(title)
        
        # 如果有效标题不足20个，尝试补充
        if len(valid_titles) < 20:
            print(f"有效标题数量: {len(valid_titles)}，不足20个")
        
        # 从目录路径提取合集名称
        collection_name = _extract_collection_name(state.target_dir)
        
        # 追加到标题文件（覆盖模式）
        if valid_titles:
            titles_manager.append_titles(collection_name, valid_titles, overwrite=True)
            print(f"\n[SUCCESS] 标题已写入: titles/{state.game_name}_titles.md")
        
        # 记录日志
        logger.log_title_generation_complete(
            titles_count=len(valid_titles),
            duplicate_count=duplicate_count
        )
        logger.log_api_call(call_type="generate_title", call_count=1)
        state.api_details.append({
            "node": "generate_title",
            "usage": usage
        })

        state.generated_titles = valid_titles
        state.message = f"标题生成完成: {len(valid_titles)}个标题"
        state.api_calls += 1
        
    except Exception as e:
        state.status = "error"
        state.message = f"标题生成失败: {str(e)}"
        logger.log_error("generate_title", str(e))
    
    return state


def _extract_collection_name(dir_path: str) -> str:
    """从目录路径中提取合集名称"""
    path = Path(dir_path)
    parts = path.parts

    # 从内到外查找"合集X"模式
    for part in reversed(parts):
        match = re.search(r'合集[一二三四五六七八九十\d]+', part)
        if match:
            return match.group()

    # 如果没找到，返回最内层文件夹名
    return parts[-1] if parts else "未知合集"


@trace_node
def update_srt(state: SubtitleAgentState) -> SubtitleAgentState:
    """
    更新 SRT 字幕文件
    """
    logger = _get_logger()
    
    if not state.corrected_file:
        state.status = "error"
        state.message = "未找到纠正后的字幕文件"
        logger.log_error("update_srt", "未找到纠正后的字幕文件")
        return state
    
    # 字幕目录
    subtitle_dir = Path(state.corrected_file).parent
    
    try:
        tool = _get_update_srt_tool()
        output_file = tool.run(str(subtitle_dir))
        
        # 记录日志
        logger.log_update_srt(
            corrected_file=state.corrected_file,
            final_srt_file=output_file
        )
        
        state.final_srt_file = output_file
        state.status = "completed"
        state.message = f"SRT字幕更新完成: {output_file}"
        
    except Exception as e:
        state.status = "error"
        state.message = f"SRT更新失败: {str(e)}"
        logger.log_error("update_srt", str(e))
    
    # 记录最终结果
    logger.log_result(
        status=state.status,
        message=state.message,
        api_calls=state.api_calls
    )
    
    return state