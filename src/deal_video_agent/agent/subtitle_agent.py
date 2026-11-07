# -*- coding: utf-8 -*-
"""
字幕纠正 Agent 主入口
基于 LangGraph 实现
"""
from typing import Dict, Any
from pathlib import Path
from langgraph.graph import StateGraph, END

from .state import SubtitleAgentState
from .nodes import (
    parse_input,
    check_knowledge_base,
    build_knowledge_base,
    add_line_order,
    correct_subtitle,
    generate_title,
    update_srt
)


def create_subtitle_agent():
    """
    创建字幕纠正 Agent
    
    工作流程:
    1. parse_input - 解析用户输入
    2. check_knowledge_base - 检查知识库
    3. build_knowledge_base - 构建知识库（如需要）
    4. add_line_order - 添加行号
    5. correct_subtitle - 字幕纠正（第1次API调用）
    6. generate_title - 标题生成（第2次API调用）
    7. update_srt - 更新SRT
    """
    # 创建状态图
    graph = StateGraph(SubtitleAgentState)
    
    # 添加节点
    graph.add_node("parse_input", parse_input)
    graph.add_node("check_knowledge_base", check_knowledge_base)
    graph.add_node("build_knowledge_base", build_knowledge_base)
    graph.add_node("add_line_order", add_line_order)
    graph.add_node("correct_subtitle", correct_subtitle)
    graph.add_node("generate_title", generate_title)
    graph.add_node("update_srt", update_srt)
    
    # 设置入口点
    graph.set_entry_point("parse_input")
    
    # 添加边
    graph.add_edge("parse_input", "check_knowledge_base")
    
    # 条件分支：知识库是否存在
    def should_build_knowledge_base(state: SubtitleAgentState) -> str:
        if state.knowledge_built:
            return "add_line_order"
        else:
            return "build_knowledge_base"
    
    graph.add_conditional_edges(
        "check_knowledge_base",
        should_build_knowledge_base,
        {
            "build_knowledge_base": "build_knowledge_base",
            "add_line_order": "add_line_order"
        }
    )
    
    # 知识库构建后继续
    graph.add_edge("build_knowledge_base", "add_line_order")
    
    # 继续流程：字幕纠正 → 标题生成 → 更新SRT
    graph.add_edge("add_line_order", "correct_subtitle")
    graph.add_edge("correct_subtitle", "generate_title")
    graph.add_edge("generate_title", "update_srt")
    graph.add_edge("update_srt", END)
    
    return graph.compile()


def run_subtitle_agent(
    target_dir: str,
    user_prompt: str,
    clear_titles: bool = False
) -> Dict[str, Any]:
    """
    运行字幕纠正 Agent
    
    Args:
        target_dir: 目标目录路径
        user_prompt: 用户提示词（包含内容主题）
        clear_titles: 是否在开始时清空标题文件（用于新项目初始化）
        
    Returns:
        处理结果字典
    """
    # 创建 Agent
    agent = create_subtitle_agent()
    
    # 如果需要清空标题文件
    if clear_titles:
        from .tools import TitlesManager
        SCRIPT_DIR = Path(__file__).parent.parent
        # 从目录路径提取游戏名，确定对应的标题文件
        target_path = Path(target_dir)
        parts = target_path.parts
        game_name = "unknown"
        for i, part in enumerate(parts):
            if "工作区" in part or "游戏素材" in part or "剪辑草稿" in part:
                if i + 1 < len(parts):
                    game_name = parts[i + 1]
                    break
        title_file = f"titles/{game_name}_titles.md"
        titles_manager = TitlesManager(str(SCRIPT_DIR), title_file=title_file)
        titles_manager.clear_all_titles()
        print(f"[INFO] 标题文件已清空: {title_file}")
    
    # 初始化状态
    initial_state = SubtitleAgentState(
        target_dir=target_dir,
        user_prompt=user_prompt
    )
    
    # 执行
    result = agent.invoke(initial_state)
    
    # LangGraph 返回字典，提取结果
    return {
        "status": result.get("status", "unknown"),
        "message": result.get("message", ""),
        "game_name": result.get("game_name", ""),
        "main_topic": result.get("main_topic", ""),
        "specific_content": result.get("specific_content", ""),
        "subtitle_file": result.get("subtitle_file", ""),
        "ordered_file": result.get("ordered_file", ""),
        "corrected_file": result.get("corrected_file", ""),
        "final_srt_file": result.get("final_srt_file", ""),
        "knowledge_file": result.get("knowledge_file", ""),
        "generated_titles": result.get("generated_titles", []),
        "api_calls": result.get("api_calls", 0),
        "node_timings": result.get("node_timings", {}),
        "api_details": result.get("api_details", [])
    }


def print_result(result: Dict[str, Any]):
    """打印处理结果"""
    print("=" * 50)
    print("字幕纠正 Agent 处理结果")
    print("=" * 50)
    print(f"状态: {result['status']}")
    print(f"消息: {result['message']}")
    print(f"游戏: {result['game_name']}")
    print(f"大主题: {result['main_topic']}")
    print(f"具体内容: {result['specific_content']}")
    print(f"字幕文件: {result['subtitle_file']}")
    print(f"带行号文件: {result['ordered_file']}")
    print(f"纠正文件: {result['corrected_file']}")
    print(f"最终SRT: {result['final_srt_file']}")
    print(f"知识库: {result['knowledge_file']}")
    print(f"API调用次数: {result['api_calls']}")

    # 打印生成的标题
    titles = result.get("generated_titles", [])
    if titles:
        print("=" * 50)
        print(f"生成的标题 ({len(titles)}个):")
        print("-" * 50)
        for i, title in enumerate(titles, 1):
            print(f"  {i}. {title}")

    # 性能报告
    node_timings = result.get("node_timings", {})
    api_details = result.get("api_details", [])
    if node_timings or api_details:
        _print_performance(node_timings, api_details)

    print("=" * 50)


NODE_ALIASES = {
    "parse_input": "解析输入",
    "check_knowledge_base": "检查知识库",
    "build_knowledge_base": "构建知识库",
    "add_line_order": "添加行号",
    "correct_subtitle": "纠正字幕",
    "generate_title": "生成标题",
    "update_srt": "更新SRT",
}

API_NODES = {"correct_subtitle", "generate_title", "build_knowledge_base"}

#: 每百万 token 的人民币单价：(缓存命中输入, 缓存未命中输入, 输出)。
#:
#: **故意留空**。原因：模型换了之后原来那套价目（reasoner 输入 ¥4 / 输出 ¥16）
#: 已经不适用；而我没有权威单价，编一个比不显示更糟 —— 会让人以为知道花了多少。
#: 想恢复成本估算，把当前模型的单价填进来即可，例如：
#:
#:     MODEL_PRICES = {
#:         "deepseek-flash": (0.1, 0.5, 2.0),   # ← 用官方价目核实后替换
#:     }
#:
#: 查不到时只报 token 数，不算钱。
MODEL_PRICES: Dict[str, tuple] = {}


def _current_model() -> str:
    """当前配置的模型名（从 conf/agent.yaml 读，不建客户端、不花 token）"""
    try:
        from .tools.deepseek_api import load_model
        return load_model()
    except Exception:          # noqa: BLE001
        return "unknown"


def _print_performance(node_timings: dict, api_details: list):
    """打印性能报告"""
    total = sum(node_timings.values())
    if total <= 0:
        return

    print("=" * 50)
    print("性能报告")
    print("=" * 50)
    print("节点耗时:")
    for node, secs in node_timings.items():
        pct = secs / total * 100
        alias = NODE_ALIASES.get(node, node)
        marker = "  ← API调用" if node in API_NODES else ""
        print(f"  {node}（{alias}）{secs:>8.3f}s  {pct:>5.1f}%{marker}")
    print(f"  {'─' * 45}")
    print(f"  总计{total:>22.3f}s 100.0%")

    # API 调用明细
    if api_details:
        print()
        print("API 调用明细:")
        total_prompt = 0
        total_completion = 0
        total_hit = 0
        total_miss = 0
        for detail in api_details:
            usage = detail.get("usage", {})
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            hit = usage.get("prompt_cache_hit_tokens", 0)
            miss = usage.get("prompt_cache_miss_tokens", 0)
            total_prompt += pt
            total_completion += ct
            total_hit += hit
            total_miss += miss
            alias = NODE_ALIASES.get(detail["node"], detail["node"])
            hit_rate = hit / (hit + miss) * 100 if (hit + miss) > 0 else 0
            print(f"  {alias}: prompt={pt}, completion={ct}, 缓存命中={hit_rate:.0f}%")

        # 成本估算按模型名查表。查不到就**只报 token 数、不算钱** ——
        # 编一个单价出来比不算更糟：会让人以为知道成本。
        total_tok = total_prompt + total_completion
        cache_rate = total_hit / (total_hit + total_miss) * 100 if (total_hit + total_miss) > 0 else 0

        print(f"  {'─' * 40}")
        print(f"  总计: {total_tok} tokens | prompt {total_prompt} | completion {total_completion}")
        print(f"  缓存命中: {total_hit}/{total_hit + total_miss} = {cache_rate:.0f}%")

        price = MODEL_PRICES.get(_current_model())
        if price is None:
            print(f"  预估成本: 未配置 {_current_model()} 的单价，跳过（见 MODEL_PRICES）")
        else:
            hit_price, miss_price, out_price = price
            cost = (total_hit * hit_price + total_miss * miss_price
                    + total_completion * out_price) / 1_000_000
            print(f"  预估成本: ~¥{cost:.4f}（{_current_model()}，输入¥{miss_price}/1M，"
                  f"输出¥{out_price}/1M）")
    
    print("=" * 50)


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        # ── CLI 模式：python subtitle_agent.py <target_dir> <user_prompt> [--clear-titles] ──
        import argparse
        parser = argparse.ArgumentParser(description="字幕纠正 Agent")
        parser.add_argument("target_dir", help="目标目录路径")
        parser.add_argument("user_prompt", help="用户提示词")
        parser.add_argument("--clear-titles", action="store_true", help="清空标题文件")
        args = parser.parse_args()
        result = run_subtitle_agent(
            target_dir=args.target_dir,
            user_prompt=args.user_prompt,
            clear_titles=args.clear_titles
        )
    else:
        # ── 交互模式：直接运行，用户手动输入 ──
        print("字幕纠正 Agent - 交互模式")
        print("=" * 50)

        default_dir = r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集三\剪辑"
        dir_input = input(f"目标目录（回车使用默认）:\n  {default_dir}\n> ").strip()
        target_dir = dir_input if dir_input else default_dir

        default_prompt = "本次视频主要内容关于【我的世界愚者整合包】..."
        prompt_input = input(f"用户提示词（回车使用默认）:\n  {default_prompt}\n> ").strip()
        user_prompt = prompt_input if prompt_input else default_prompt

        clear_input = input("清空标题文件？(y/N): ").strip().lower()
        clear_titles = clear_input == "y"

        print()
        result = run_subtitle_agent(
            target_dir=target_dir,
            user_prompt=user_prompt,
            clear_titles=clear_titles
        )

    print_result(result)