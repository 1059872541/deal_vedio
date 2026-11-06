# 字幕纠正 Agent

基于 LangGraph 的 AI Agent，自动完成字幕纠正、标题生成与 SRT 回写。

## 功能

1. **字幕纠正** — 修正错别字、同音字、游戏术语误识别
2. **标题生成** — 依据实际视频内容生成 20 条有区分度的标题
3. **SRT 回写** — 把纠正结果写回 `_corrected.srt`，可直接导入剪映替换字幕

## 技术要点

- LangGraph 状态机（7 节点），每步状态可观测、失败可单点重跑
- DeepSeek `deepseek-v4-pro`，配合 Context Caching（字幕原文两次调用复用，输入成本约降 90%）
- 流式输出显示进度
- structlog 结构化日志
- 提示词支持按游戏覆写（YAML 字段级继承）
- 节点级性能追踪（`@trace_node` 装饰器），终端输出耗时占比、Token 用量与预估成本

## 目录结构

```
deal_video_agent/
├── README.md
├── monitor_subtitle.py             # 监控模式入口
├── requirements.txt
├── prompts/
│   ├── subtitle_correction.yaml    # 通用提示词模板（3 个用途字段）
│   └── games/{游戏名}.yaml          # 按游戏覆写指定字段
├── knowledge_base/
│   └── {游戏名}/{主题}.md           # 术语库，两层结构
├── titles/
│   └── {游戏名}_titles.md           # 标题按游戏隔离
└── agent/
    ├── state.py                    # 状态定义
    ├── nodes.py                    # 7 个节点实现
    ├── subtitle_agent.py           # 编排 + 主入口
    ├── logger.py                   # structlog 配置
    └── tools/
        ├── deepseek_api.py         # API 客户端（含 usage 解析）
        ├── knowledge_base.py       # 术语库读写
        ├── titles_manager.py       # 标题文件管理
        ├── add_line_order.py       # 给字幕加行号
        └── update_srt.py           # 纠正结果回写 srt
```

## 工作流

```
target_dir + user_prompt
        │
        ▼
┌───────────────┐
│  parse_input  │  解析游戏名 / 大主题 / 具体内容
└───────┬───────┘
        ▼
┌─────────────────────┐
│ check_knowledge_base│
└─────────┬───────────┘
          │ 条件分支
    ┌─────┴──────┐
    ▼            ▼
┌────────┐  ┌──────────────────┐
│ 已存在 │  │ build_knowledge  │  API 调用
└────────┘  └────────┬─────────┘
          ┌──────────┘
          ▼
┌────────────────┐
│ add_line_order │  产出 {名}_ordered.txt
└───────┬────────┘
        ▼
┌──────────────────┐
│ correct_subtitle │  API 调用 → corrected.txt
└───────┬──────────┘
        ▼
┌─────────────────┐
│ generate_title  │  API 调用 → titles/{游戏名}_titles.md
└───────┬─────────┘
        ▼
┌────────────┐
│ update_srt │  产出 {名}_corrected.srt
└────────────┘
```

## 快速开始

```bash
# 1. 设置 API Key（变量名固定为 deepseek_env_key）
set deepseek_env_key=sk-xxxxxxxx

# 2. 安装依赖
pip install -r src/deal_video_agent/requirements.txt
```

## 运行

```python
from deal_video_agent.agent import run_subtitle_agent, print_result

result = run_subtitle_agent(
    target_dir=r"D:\VedioRecords\工作区\我的世界\合集十\剪辑",
    user_prompt="本次视频主要内容关于【暮色森林模组】地牢探索与BOSS战斗",
    clear_titles=False,
)
print_result(result)
```

```bash
# CLI 模式
python src/deal_video_agent/agent/subtitle_agent.py "<目标目录>" "<内容主题>" [--clear-titles]

# 监控模式：常驻目录，新字幕自动处理
python src/deal_video_agent/monitor_subtitle.py --dir "<目录>" --time 20
python src/deal_video_agent/monitor_subtitle.py --dir "<目录>" --now
```

## 返回值

```python
{
    "status": "completed",              # pending / running / completed / error
    "message": "处理成功",
    "game_name": "我的世界",
    "main_topic": "暮色森林",
    "specific_content": "地牢探索与BOSS战斗",
    "ordered_file": "xxx_ordered.txt",
    "corrected_file": "corrected.txt",
    "final_srt_file": "xxx_corrected.srt",
    "generated_titles": ["标题1", ...],
    "api_calls": 2,
    "node_timings": {...},
    "api_details": [...],
}
```

## 提示词与知识库

**提示词三层继承**：`prompts/subtitle_correction.yaml` 是通用模板，含三个用途字段：

| 字段 | 用途 |
|------|------|
| `knowledge_building` | 构建术语库 |
| `subtitle_correction` | 字幕纠正 |
| `title_generation` | 标题生成 |

若存在 `prompts/games/{游戏名}.yaml`，其中出现的字段会覆盖通用模板的同名字段，未出现的自动继承。新增游戏只加一个 YAML，Python 代码不动。

**知识库**两层结构：`knowledge_base/{游戏名}/{主题}.md`。游戏名会先用正则 `-\d{4}(?:-\d{2})?$` 去掉日期后缀，让同一游戏不同批次共享术语库。

## 标题文件

按游戏隔离存放：`titles/{游戏名}_titles.md`（游戏名保留日期后缀，如 `我的世界-2026-06_titles.md`）。

```markdown
# 我的世界-2026-06系列视频标题列表

---
#### 合集一:
标题1
标题2
...
```

- 同一合集重复生成时覆盖该合集的段落
- 其它合集内容不做解析、不做重写（避免解析异常导致数据丢失）
- `clear_titles=True` 清空整份文件，用于新项目初始化

## 依赖

Python 3.13+ · langgraph · openai · pydantic · pyyaml · structlog

## 注意事项

1. 首次运行会自动生成带行号的 `_ordered.txt`
2. 剪映期望的 srt 编码是 UTF-8 **带 BOM**，`update_srt` 已按此写出
3. 字幕分段时长（`split_clean_srt`）必须与视频分割时长一致，否则字幕与画面对不上
4. 终端避免输出 emoji，Windows GBK 控制台会报 `UnicodeEncodeError`

## 相关文档

| 文件 | 内容 |
|------|------|
| [`EVOLUTION.md`](../../EVOLUTION.md) | 决策因果链（为什么用 LangGraph / 为什么两层知识库 / 为什么按游戏拆标题文件） |
| [`TODO.md`](../../TODO.md) | 待办清单 |
| [`docs/agent_worklog.md`](../../docs/agent_worklog.md) | 需求讨论与实施进度 |
| [`docs/agent_iteration_20260606.md`](../../docs/agent_iteration_20260606.md) | 单次迭代详录（含改前改后对比） |
