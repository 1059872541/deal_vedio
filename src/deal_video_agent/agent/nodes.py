# -*- coding: utf-8 -*-
"""
字幕纠正 Agent 节点定义
"""
import os
import re
import time
import difflib
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


#: 模型名不再写在这里。
#: 三个用途（构建知识库 / 字幕纠错 / 标题生成）共用 `conf/agent.yaml` 的
#: `deepseek.model`，由 `DeepSeekClient.default_model` 提供；调用时不传 `model=`
#: 就用它。之所以搬走：模型名会随厂商更新（deepseek-chat → deepseek-v4-pro
#: → deepseek-flash → …），写死在调用点等于每次改名都要改代码。
#:
#: ⚠ 有一件事不能靠配置忘掉：**纠错这一环不能用推理模型**。
#:   实测推理模型会把额度全烧在推理里、正文一个字都不吐
#:   （finish_reason=length、content 为空），结果是"跑完了但什么都没改"。
#:   换模型后如果 corrected.txt 变成 0 字节，先怀疑这一条。

# ==================== 日志记录器 ====================

def _get_logger():
    """获取日志记录器"""
    return get_logger()


# ==================== 工具初始化 ====================

# 配置路径
SCRIPT_DIR = Path(__file__).parent.parent  # deal_video_agent 目录
REPO_ROOT = SCRIPT_DIR.parent.parent       # 仓库根
CONFIG_DIR = SCRIPT_DIR / "config.yaml"
PROMPTS_DIR = SCRIPT_DIR / "prompts"       # 修正：deal_video_agent/prompts
#: 知识库是**游戏级资产**（跨批次复用的 ASR 易错词表），不是代码，
#: 所以放 conf/知识库/{游戏}/，跟着规则一起入库；换机器 clone 后必须还在。
KNOWLEDGE_BASE_DIR = REPO_ROOT / "conf" / "知识库"

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
        logger.log_api_call(call_type="build_knowledge_base", call_count=1,
                             model=deepseek.default_model)
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

        # 额度被推理吃光时 content 为空、finish_reason=length —— 必须报错，
        # 否则会写出 0 字节 corrected.txt 却报告"纠正完成"。
        if usage.get("finish_reason") == "length":
            state.status = "error"
            state.message = (
                f"字幕纠正输出被截断（completion_tokens={usage.get('completion_tokens')}），"
                f"结果不可用。多半是推理把额度吃光了 —— 调大 conf/agent.yaml 的 max_tokens"
            )
            logger.log_error("correct_subtitle", state.message)
            return state

        # 只保留「行号:内容」行：模型偶尔会把分析过程混进正文，
        # 这些行回写 srt 会把字幕改成一段议论文。
        raw_lines = [line.strip() for line in response.splitlines() if line.strip()]
        kept_lines = [line for line in raw_lines if re.match(r'^\d+\s*[:：]', line)]
        if raw_lines and not kept_lines:
            state.status = "error"
            state.message = f"字幕纠正输出格式不符（{len(raw_lines)} 行没有一行是 行号:内容）"
            logger.log_error("correct_subtitle", state.message)
            return state

        # 只留真正改过的行：模型经常把整篇原文照抄回来，
        # 照抄的行回写 srt 等于没改，却让"改了几处"这个数字失真。
        original = {}
        for line in Path(ordered_file).read_text(encoding="utf-8").splitlines():
            matched = re.match(r'^(\d+)\s*[:：](.*)$', line.strip())
            if matched:
                original[matched.group(1)] = matched.group(2).strip()

        changed_lines = []
        rejected = 0
        for line in kept_lines:
            matched = re.match(r'^(\d+)\s*[:：](.*)$', line)
            if not matched:
                continue
            num, text = matched.group(1), matched.group(2).strip()
            old = original.get(num)
            if old == text:
                continue
            if old is None:
                rejected += 1
                continue
            # 只接受"改几个字"：模型会顺手删语气词、甚至拿别的行来整句替换。
            # 用相似度 + 长度比兜住，改得面目全非的一律不要。
            ratio = difflib.SequenceMatcher(None, old, text).ratio()
            if ratio < 0.7 or len(text) < len(old) * 0.8:
                rejected += 1
                continue
            changed_lines.append(f"{num}:{text}")
        response = "\n".join(changed_lines)
        if rejected:
            logger.log_error(
                "correct_subtitle",
                f"丢弃 {rejected} 条可疑纠正（删词/整句替换/相似度过低）"
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
        logger.log_api_call(call_type="correct_subtitle", call_count=1,
                             model=deepseek.default_model)
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

    # 这个合集已有标题就跳过：重跑字幕纠错不该把标题洗掉（标题是门面，
    # 人工可能已经改过）。要重新生成就先清掉 titles/ 里该合集那一节。
    collection_name = _extract_collection_name(state.target_dir)
    existing_for_collection = titles_manager.get_collection_titles(collection_name)
    if existing_for_collection:
        state.generated_titles = existing_for_collection
        state.message = f"{collection_name} 已有 {len(existing_for_collection)} 条标题，跳过重新生成"
        logger.log_title_generation_complete(
            titles_count=len(existing_for_collection), duplicate_count=0
        )
        return state
    
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

        # 偶尔会返回空内容。用同一个模型重试一次 ——
        # 否则「0 条标题」会被当成"生成完成"，标题却再也没人重写。
        #
        # 注意：以前这里是"从推理模型退回非推理模型再试"，那是两套模型时代的
        # 兜底。现在三次调用共用一个模型（conf/agent.yaml），所以这只是
        # 一次普通重试；如果空内容持续出现，说明该换模型了，不是该重试。
        if not response.strip():
            print("[WARNING] 标题生成返回空内容，重试一次")
            response, usage = deepseek.stream_chat_with_progress(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                show_progress=True
            )
            if not response.strip():
                state.status = "error"
                state.message = "标题生成返回空内容（重试一次仍为空，检查 conf/agent.yaml 的模型）"
                logger.log_error("generate_title", state.message)
                return state

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
        
        # 追加到标题文件（覆盖模式）
        if valid_titles:
            titles_manager.append_titles(collection_name, valid_titles, overwrite=True)
            print(f"\n[SUCCESS] 标题已写入: titles/{state.game_name}_titles.md")
        
        # 记录日志
        logger.log_title_generation_complete(
            titles_count=len(valid_titles),
            duplicate_count=duplicate_count
        )
        logger.log_api_call(call_type="generate_title", call_count=1,
                             model=deepseek.default_model)
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