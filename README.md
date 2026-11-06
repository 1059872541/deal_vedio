# 视频处理自动化流水线

从剪映草稿到成片、片单、网盘的半自动流水线。录制与剪辑由人完成，其余环节由 Python 脚本 + LLM Agent + MCP 承担。

```
录制 → 剪辑 → 字幕处理 → LLM 字幕纠正 + 标题生成 → 分割拼接 → 重命名 → 片单 Excel → 上传网盘
 👤     👤        ⚙️            🤖                    ⚙️         🎯        🎯          🎯
```

## 完成度标识

| 标识 | 含义 |
|------|------|
| 👤 | 纯手动 |
| ⚙️ | 配置参数后手动运行脚本 |
| 👁️ | 脚本常驻，自动处理新文件 |
| 🤖 | LangGraph Agent，多步骤自动串联 |
| 🎯 | 由 LLM 驱动 Skill 编排（Claude Code / OpenCode） |

**编排模型**：本项目没有 `run_workflow.py` 这类"一键跑完"的主控。流程由 LLM + Skill + MCP 编排，Python 脚本只提供确定性的原子能力。原因见 `EVOLUTION.md` 跨模块决策。

---

## 工作流

### 阶段零：项目初始化

| 步骤 | 功能 | 实现 | 完成度 |
|------|------|------|--------|
| 0a | 创建项目目录结构 | `src/scaffold/new_project_01_AI_USE.py` | ⚙️ |
| 0b | 素材跨合集时长均衡 | `.claude/skills/material-redistribute/` | 🎯 |

### 阶段一：素材准备与剪辑（人工）

| 步骤 | 功能 | 实现 | 完成度 |
|------|------|------|--------|
| 1 | OBS 录屏 | OBS Studio | 👤 |
| 2 | 素材整理 | 手动归入 `合集{x}/素材/` | 👤 |
| 3 | 剪映剪辑 | 剪映专业版 | 👤 |
| 4 | 批量导出草稿 | `src/jianying_export/export_draft.py` | ⚙️ |

### 阶段二：字幕处理

| 步骤 | 功能 | 实现 | 完成度 |
|------|------|------|--------|
| 5 | 导出字幕 srt | 剪映导出 | 👤 |
| 6 | 字幕清洗为 txt | `src/words/split_clean_srt.py` | ⚙️ |
| 7 | 添加行号 | `agent/tools/add_line_order.py` | 🤖 |
| 8 | LLM 字幕纠正 + 标题生成 | `src/deal_video_agent/` | 🤖 |
| 9 | 回写 srt | `agent/tools/update_srt.py` | 🤖 |
| 10 | 导入剪映替换字幕 | — | 待开发 |

### 阶段三：视频后处理

| 步骤 | 功能 | 实现 | 完成度 |
|------|------|------|--------|
| 11 | 分割 + 片头片尾拼接 | `src/splice_vedio/auto_splice_mp4.py` | ⚙️ |
| 12 | 批量重命名 | `.claude/skills/batch-video-renamer/` | 🎯 |
| 13 | 片单 Excel 生成 | 外部 skill `excel-sheet-generator`（不在本仓库） | 🎯 |
| 14 | 上传 / 整理网盘 | 百度网盘 MCP、夸克 MCP | 🎯 能力已具备，待封装 |

> 步骤 14 说明：两个 MCP Server 已提供 `upload_file` / `move` / `rename` / `regex_rename` 等工具，**不需要新写 Python 模块**，缺的只是一个把"成片目录 → 网盘目录"流程固定下来的 skill。

---

## 项目结构

```
deal_vedio/
├── README.md                  # 本文件
├── EVOLUTION.md               # 决策因果链（问题 → 方案 → 取舍 → 结果）
├── TODO.md                    # 待办，按 P0/P1/P2 排列
├── docs/                      # 迭代记录与工作日志
├── .env                       # 本地环境配置（FFMPEG_DIR）
├── .mcp.json                  # MCP Server 配置，含明文 Token → 仅本地，不入库
├── .gitignore / .gitattributes
├── .venv/                     # Python 3.13.5 虚拟环境，不入库
├── subtitle_agent.bat         # 字幕 Agent 启动器
│
├── .claude/skills/            # LLM 编排用的 Skill
│   ├── batch-video-renamer/   # 视频批量重命名（入 git）
│   └── material-redistribute/ # 素材时长均衡（入 git）
│
├── tools/
│   └── quark-nd-mcp/          # 夸克网盘 MCP Server（预编译 exe）
│
└── src/
    ├── requirements.txt
    ├── setup.bat / activate.bat / activate.ps1
    │
    ├── deal_video_agent/      # 字幕纠正 + 标题生成 Agent（LangGraph）
    │   ├── agent/             # state / nodes / subtitle_agent / logger
    │   ├── agent/tools/       # deepseek_api / knowledge_base / titles_manager
    │   │                      # add_line_order / update_srt
    │   ├── prompts/           # 提示词模板（YAML，支持按游戏覆写）
    │   ├── knowledge_base/    # 术语库（按游戏分目录）
    │   ├── titles/            # 已生成的标题（按游戏+月份分文件）
    │   └── monitor_subtitle.py
    │
    ├── jianying_export/       # 剪映 uiautomation 自动化导出
    ├── splice_vedio/          # 多目录监听、分割、片头片尾拼接
    ├── scaffold/              # 项目目录脚手架
    ├── title/                 # 视频时长统计 / 按"第X集"重命名
    ├── words/                 # 字幕清洗为 txt / 纠正结果回写 srt
    └── util/                  # ffmpeg 封装 / 文本工具 / 片单对比
```

> **`.mcp.json` 不入库**：内含百度网盘 access_token。新机器上需按
> `.claude/skills/baiducloud-operate/references/BaiduCloud-MCP-README.md` 与
> `.claude/skills/quarkpan-mcp-operate/references/quark-nd-mcp-README.md` 重建。

---

## 模块说明

### 1. 字幕纠正 Agent — `src/deal_video_agent/`

基于 LangGraph 的 7 节点状态机：`parse_input → check_knowledge → build_knowledge → add_line_order → correct_subtitle → generate_title → update_srt`。

- 模型：DeepSeek（`deepseek-v4-pro`），Context Caching 降低约 90% 输入成本
- 提示词按游戏覆写：`prompts/games/{游戏名}.yaml` 存在则覆盖 `prompts/subtitle_correction.yaml` 的同名字段
- 知识库两层结构：`knowledge_base/{游戏名}/{主题}.md`
- 标题按游戏隔离：`titles/{游戏名}_titles.md`

```bash
# 交互模式
python src/deal_video_agent/agent/subtitle_agent.py

# CLI 模式
python src/deal_video_agent/agent/subtitle_agent.py "<目标目录>" "<内容主题>" [--clear-titles]

# 监控模式（常驻，自动处理新字幕）
python src/deal_video_agent/monitor_subtitle.py --dir "<目录>" --time 20
```

需要环境变量 `deepseek_env_key`。详见 [`src/deal_video_agent/README.md`](src/deal_video_agent/README.md)。

### 2. 剪映自动化导出 — `src/jianying_export/`

用 uiautomation 模拟 GUI 操作批量导出草稿。仅 Windows，需剪映保持在主页且窗口在前台。

```bash
python -m src.jianying_export.export_draft                      # 默认配置
python -m src.jianying_export.export_draft --config config.json # 指定配置
python -m src.jianying_export.export_draft --list-resolutions
```

### 3. 视频分割拼接 — `src/splice_vedio/`

多目录并行监听 → 6 分钟关键帧分割（`-c copy` 无重编码）→ 片头 + 片段 + 片尾拼接（硬件编码器优先）。

```bash
python src/splice_vedio/auto_splice_mp4.py
```

⚠️ 监听目录与片头片尾目前写在文件顶部的 `WATCH_DIRECTORIES` 常量里，尚未外置为配置文件。这是已知待改进项。

### 4. 字幕清洗与回写 — `src/words/`

- `split_clean_srt.py` — 把 srt 按 6 分钟切段，去时间戳，输出纯文本 `words/第X集.txt`
- `updateSRT.py` — 把 `corrected.txt`（格式 `行号:纠正后内容`）回写为新 srt

> 两者的 6 分钟要与视频分割的 `SEGMENT_DURATION = 360` 保持一致，否则字幕与画面对不上。这个耦合目前靠人工保证。

### 5. 素材时长均衡 — `.claude/skills/material-redistribute/`

扫描各合集累加时长，超限的用 ffmpeg 关键帧切割（`-c copy`），溢出段以 `{N}-0.mkv` 移入下一合集，级联处理。支持断点续跑（`.redistribute_log.json`）。

### 6. 视频重命名 — `.claude/skills/batch-video-renamer/`

按 `前缀 第X集 标题.mp4` 批量重命名。核心实现 `rename_videos.py`（685 行，仅依赖标准库）。

### 7. 片单对比 — `src/util/video_compare.py`

把网盘文件名与片单 Excel 逐集比对，支持定制（带合集名前缀）/ 非定制两种命名格式。

```bash
python src/util/video_compare.py --excel "<片单.xlsx>" --data "<网盘文件列表.json>" --format custom
```

### 8. 工具 — `src/util/`

- `ffmpeg_utils.py` — ffmpeg/ffprobe 路径、时长探测、关键帧切割
- `file_utils.py` — 中文数字转换、自然排序、UTF-8 输出修正
- `video_compare.py` — 见上

---

## 技术栈

Python 3.13 · FFmpeg（含 Intel QSV 硬编）· LangGraph · DeepSeek API · uiautomation · PyYAML · openpyxl · MCP（百度网盘 / 夸克网盘）

---

## 痛点与现状

| 痛点 | 解决方式 | 状态 |
|------|----------|------|
| 字幕纠正（手工 10–20 分钟） | `deal_video_agent` | 🤖 已自动 |
| 标题生成（手工与 AI 对话） | `deal_video_agent` | 🤖 已自动 |
| 剪映导出（等待 40 分钟） | `jianying_export` | ⚙️ 已自动化 |
| 素材跨合集时长不均 | `material-redistribute` | 🎯 已自动 |
| 视频批量重命名 | `batch-video-renamer` | 🎯 已自动 |
| 片单 Excel 填写 | 外部 skill | 🎯 已自动 |
| 网盘上传整理 | MCP 已具备能力 | 待封装 |
| 字幕复查（人工 10–30 分钟） | **暂无** | 👤 无工具 |

> 字幕复查原本有 `check_subtitle.py` + `llm_validate_subtitle.py` 两阶段工具，但第二阶段的 Ollama 客户端依赖已被删除的 `src/client/` 模块，链路断裂，故在 2026-11-06 的清理中移除。需要时重写。

---

## 使用说明

```bash
# 激活环境
.venv\Scripts\activate.bat

# 各环节单独运行（见上文各模块说明）
python src/splice_vedio/auto_splice_mp4.py
python src/deal_video_agent/agent/subtitle_agent.py
```

部分脚本使用 `from util.xxx import ...` 的相对包导入，需要 `src/` 在 `sys.path` 中
（脚本内部已自动插入，`subtitle_agent.bat` 也会设置 `PYTHONPATH`）。

---

## 开发规范

1. 先读代码再改，不凭猜测动手
2. 复用现成实现，不新建重复工具函数
3. 不写多余注释
4. 产线脚本的行为冻结项：固定文件名（`corrected.txt` / `_ordered.txt` / `_corrected.srt`）、6 分钟分段、`x-0.mkv` 溢出命名、`合集一~九十九` 命名、标题文件格式
5. 涉及 ffmpeg 切割的改动先跑 `--dry-run`

---

## 2026-11-06 清理记录

全项目 Python 文件从 55 个 / 11,165 行降到 **27 个 / 6,883 行**（其中 `src/` 下 53 → 26 个、10,314 → 6,198 行，减少约 40%）。删除内容与理由：

| 删除 | 理由 |
|------|------|
| `src/watermark/`（6 文件） | EVOLUTION.md 已标记暂停，效果未达预期，无引用 |
| `src/util/text_utils.py`、`console.py`、`path_resolver.py`、`config_manager.py` | 全项目零引用；后两个 `import` 即报 `NameError: name 'Path' is not defined` |
| `src/words/add_line_order.py` | 与 `agent/tools/add_line_order.py` 重复 |
| `src/words/check_subtitle.py`、`llm_validate_subtitle.py` | 依赖已删除的 `src/client/`，链路断裂 |
| `src/splice_vedio/{split_by_time,path_to_json,with_end}.py` | `auto_splice_mp4` 的旧版与一次性辅助脚本 |
| `src/util/{generate_excel,quark_search_videos,query_quark,quark_video_duration,video_info,video_watch,treegen,minecraft_auto_clicker}.py` | 零引用；网盘相关功能已被 MCP 覆盖 |
| `src/scaffold/{new_project,new_project_01}.py` | 被 `new_project_01_AI_USE.py` 取代 |
| `rename_images.py`、`src/words/extract_voice.py` | 一次性脚本，无引用 |
| `src/deal_video_agent/config.yaml` | 从未被 `yaml.safe_load`，且 `api.model` / `titles.file` 与代码矛盾 |
| `.opencode/`、共享的 `quark-nd-mcp/README.md` | 内容重复或已废弃 |

同时修复：`AddLineOrderTool` 的死参数 `script_path`、`knowledge_base.py` 的无效转义 `\s`、`auto_splice_mp4_4.py` 更名为 `auto_splice_mp4.py`。
