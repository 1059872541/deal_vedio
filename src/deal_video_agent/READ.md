# 字幕纠正 Agent (Subtitle Correction Agent)

基于 LangGraph 的 AI Agent，用于自动化视频剪辑工作流中的字幕纠正和标题生成。

## 功能特性

### 核心功能
1. **字幕纠正** - 自动识别并纠正字幕中的错别字、格式错误
2. **标题生成** - 基于视频内容自动生成吸引人的标题
3. **SRT更新** - 将纠正后的字幕同步回 SRT 格式

### 技术特点
- 基于 **LangGraph** 工作流引擎
- 使用 **DeepSeek Reasoner** 模型进行智能处理
- 支持 **Context Caching** 优化 API 费用（两次调用复用字幕内容）
- **流式输出**支持，实时显示处理进度
- **结构化日志**（structlog）记录完整处理过程

## 项目架构

```
deal_video_agent/
├── config.yaml                      # 配置文件
├── requirements.txt                 # 依赖
├── monitor_subtitle.py             # 字幕文件监控脚本
├── prompts/
│   └── subtitle_correction.yaml     # 提示词模板
├── titles/
│   └── all_collection_titles.md  # 标题容器文件
├── knowledge_base/                  # 知识库
│   └── 我的世界/
│       ├── 暮色森林.md
│       ├── 养殖业.md
│       └── ...
└── agent/
    ├── __init__.py
    ├── state.py                     # Agent 状态定义
    ├── nodes.py                     # LangGraph 节点
    ├── subtitle_agent.py           # 主入口
    ├── logger.py                    # 日志系统
    └── tools/
        ├── __init__.py
        ├── deepseek_api.py          # DeepSeek API 客户端
        ├── knowledge_base.py        # 知识库工具
        ├── add_line_order.py        # 添加行号
        ├── update_srt.py            # 更新 SRT
        └── titles_manager.py        # 标题管理
```

## 工作流

```
用户输入 (target_dir + user_prompt)
        │
        ▼
┌───────────────────┐
│   parse_input     │  解析用户输入，提取游戏名、大主题、具体内容
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ check_knowledge   │  检查知识库是否存在
└─────────┬─────────┘
          │
    ┌─────┴─────┐
    │  条件分支  │
    └─────┬─────┘
          │
    ┌─────┴─────┐
    ▼           ▼
┌────────┐  ┌────────────────┐
│ 已存在 │  │ build_knowledge│  构建知识库（读取知识库文件）
└────────┘  └───────┬────────┘
                    │
                    ▼
┌───────────────────┐
│  add_line_order   │  给字幕添加行号
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ correct_subtitle  │  第1次 API 调用：字幕纠正
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  generate_title   │  第2次 API 调用：标题生成
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│   update_srt      │  更新 SRT 文件
└─────────┬─────────┘
          │
          ▼
        完成
```

## 快速开始

### 1. 环境准备

```bash
# 设置环境变量
set subtitle_correction=your-deepseek-api-key

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置文件 (config.yaml)

```yaml
api:
  provider: "deepseek"
  model: "deepseek-reasoner"
  max_tokens: 8192
  env_key: "deepseek_env_key"

workspace:
  root: "D:\\VedioRecords\\工作区"

knowledge_base:
  root: "D:\\study\\python\\deal_vedio\\src\\deal_video_agent\\knowledge_base"
```

### 3. 运行 Agent

```python
from agent import run_subtitle_agent, print_result

result = run_subtitle_agent(
    target_dir=r"D:\VedioRecords\工作区\我的世界\合集十\剪辑",
    user_prompt="本次视频主要内容关于【暮色森林模组】地牢探索与BOSS战斗..."
)

print_result(result)
```

### 4. 监控模式

```bash
python monitor_subtitle.py
```

持续监控字幕目录，新文件自动处理。

## API 调用

### 直接调用

```python
from agent.subtitle_agent import run_subtitle_agent

result = run_subtitle_agent(
    target_dir="目标目录",
    user_prompt="视频主题描述"
)
```

### 返回值

```python
{
    "status": "completed",          # pending/running/completed/error
    "message": "处理成功",
    "game_name": "我的世界",
    "main_topic": "暮色森林",
    "specific_content": "地牢探索与BOSS战斗",
    "ordered_file": "xxx_ordered.txt",
    "corrected_file": "corrected.txt",
    "final_srt_file": "xxx_corrected.srt",
    "generated_titles": ["标题1", "标题2", ...],
    "api_calls": 2
}
```

## 知识库

知识库采用两层结构：
- **大主题**（如 `暮色森林.md`）
- **具体内容**（如 `地牢探索与BOSS战斗.md`）

知识库路径：`knowledge_base/游戏名/主题.md`

Agent 会根据用户输入自动匹配相关知识库内容，用于提升字幕纠正和标题生成的准确性。

## 标题管理

生成的标题存储在 `titles/all_collection_titles.md`，按合集分类管理。

**特性**：
- 同一合集再次生成标题时自动覆盖（而非追加）
- 支持清空所有标题（新项目初始化时）

**格式**：
```markdown
# 我的世界系列视频标题列表

---
#### 合集一:
标题1
标题2
...

---
#### 合集二:
标题1
标题2
...
```

**清空标题**：
```python
result = run_subtitle_agent(
    target_dir=r"...",
    user_prompt="...",
    clear_titles=True  # 清空所有历史标题
)
```

## 依赖

- Python 3.13+
- langgraph
- openai
- pydantic
- pyyaml
- structlog
- srt (字幕处理)

## 注意事项

1. 首次运行会自动创建带行号的字幕文件
2. API 调用采用流式输出，显示实时进度
3. Context Caching 可节省约 90% API 费用
4. 终端编码问题：避免在日志中输出 emoji

## 项目文档索引

| 文件 | 定位 | 适合谁看 |
|---|---|---|
| [`EVOLUTION.md`](/EVOLUTION.md) | 每个模块关键决策的因果链（问题→方案→取舍→结果） | 面试复盘、架构回顾 |
| [`TODO.md`](/TODO.md) | 待办清单，按 P0/P1/P2 优先级排列 | 下一个做什么 |
| [`docs/agent_worklog.md`](/docs/agent_worklog.md) | 需求讨论、方案设计、实施进度、测试记录 | 记录开发过程 |
| [`docs/agent_iteration_20260606.md`](/docs/agent_iteration_20260606.md) | 单次迭代的完整记录，含改前/改后对比 | 交接、回溯细节 |