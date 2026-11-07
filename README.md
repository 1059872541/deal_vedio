# 视频处理自动化流水线

从剪映草稿到成片、台账的批量生产线。录制与剪辑由人完成，其余环节自动跑。

> **正在重构中。**
> 现状流程（AS-IS，每步谁做、要交出什么）见 [`docs/流水线现状.md`](docs/流水线现状.md)，
> 目标架构（TO-BE）见 [`docs/目标架构.md`](docs/目标架构.md)，
> 本次交付范围见 [`docs/本次交付预期.md`](docs/本次交付预期.md)。
>
> 本项目的研究与诊断记录（剪映 GUI 实测、踩过的坑）放在本地 `research/` 目录，**不入库**。

---

## 给使用者：怎么用

**你不用敲命令、不用改文件、不用看日志。** 做法只有一步：

1. 用 **DeepSeek Harness** 打开这个目录
2. 直接说话，例如：
   - 「我要做我的世界的视频」
   - 「现在什么情况」
   - 「今晚把这几个合集跑完」

### 命令一览（给知道自己在干什么的人）

仓库根目录有 `vedio.bat`，也可以 `.venv\Scripts\python vedio.py`。
所有动词**只收 `--game` / `--batch` / `--collections`，不收路径**。

| 动词 | 干什么 |
|---|---|
| `vedio paths` | 看目录在哪（只读） |
| `vedio status` | 批次进度表（只读） |
| `vedio init` | 建批次 |
| `vedio subtitle` | 字幕三步：加行号 / 纠错 / 回写 srt |
| `vedio export` | 批量导出剪映草稿 |
| `vedio splice` | 切分长片 + 拼片头片尾 |
| `vedio rename` | 按 `标题.md` 给成片改名 |
| `vedio ledger` | 生成台账 xlsx |
| `vedio run` | 按 `--steps` 推进（可夜里跑） |

```powershell
vedio status --game 我的世界 --batch 2026-12
vedio run --game 我的世界 --batch 2026-12 --collections 合集一,合集二 --steps export,splice,rename,ledger
```

加 `--json` 得到结构化结果；错误带 `error` 码和 `hint`。

AI 会读 [`AGENTS.md`](AGENTS.md) 知道该干什么，然后引导你。

---

## 环境准备（装一次就行）

以下三样是必须的，**都只需要装一次**：

| 依赖 | 说明 | 谁来做 |
|---|---|---|
| **DeepSeek Harness** | 就是你和 AI 对话的界面 | 你自己装 |
| **剪映专业版**（6.x 及以下） | 剪辑用，本来就有 | 你自己装 |
| **Python 3.12+ 和 FFmpeg** | 程序运行需要 | **让 AI 帮你装**，见下 |

### Python 和 FFmpeg 让 AI 代劳

打开 DeepSeek Harness 后，直接说一句：

> **「帮我检查一下环境，缺什么装上」**

AI 会按 [`AGENTS.md` §1](AGENTS.md) 自动做这些事：

1. `python --version` / `where.exe ffmpeg` 检查
2. 缺 Python 就用 `winget` 装，缺 FFmpeg 就下载解压并加进 PATH
3. `python -m venv .venv` + `pip install -r src/requirements.txt`
4. 问你两个问题：
   - **视频工作区放哪个目录？**（所有合集建在它下面，例如 `D:\VedioRecords\工作区`）
   - **剪映草稿目录在哪？**（这个不用你找，AI 会搜索 `draft_content.json` 自动定位，找到后让你确认）
5. 把答案写进 `conf/本机.yaml`（该文件不进 git，每台机器一份）

**如果你自己的电脑已经装好 Python 和 FFmpeg**（比如开发机），直接跳到第 3 步即可。

### 关于剪映草稿目录

剪映每个草稿目录里都有一个 `draft_content.json`，AI 用它来定位草稿根目录。
如果自动找不到，去剪映 `设置 → 草稿位置` 看一眼实际路径告诉 AI 即可。

### 绿色包（未来）

目标形态是提供一个免安装压缩包：内含嵌入式 Python + FFmpeg，解压即用，用户只需要装 DeepSeek Harness 和剪映。

---

## 开发：跑测试

```bash
.venv\Scripts\python -m unittest discover -s tests -v
```

或双击 `run_tests.bat`。

测试用标准库 `unittest`（零依赖），**不需要 ffmpeg、不需要真实的 `conf/本机.yaml`、不碰真实视频**：

- 时长探测通过 `Env.probe` 注入假函数
- 配置以字典直接传入 `Env`
- 全部在临时目录里造占位文件

加新能力时请一并加测试。当前覆盖 `src/util/balance.py`（37 个用例）。

---

## 完成度标识

| 标识 | 含义 |
|------|------|
| 👤 | 纯手动 |
| ⚙️ | 配置参数后手动运行脚本 |
| 👁️ | 脚本常驻，自动处理新文件 |
| 🤖 | LLM Agent 自动串联 |
| 🎯 | 由 LLM 驱动 Skill 编排 |

**编排模型**：对外是「对话」，对内是「确定性 CLI + 文件系统为真相」。
用户只说人话，AI 把它翻译成 `vedio` 命令；流程本身不依赖 LLM 即兴决策，因此可复现、可断点续跑。
设计细节见 [`docs/目标架构.md`](docs/目标架构.md)。

---

## 工作流

### 阶段零：项目初始化

| 步骤 | 功能 | 实现 | 完成度 |
|------|------|------|--------|
| 0a | 创建项目目录结构 | `src/scaffold/new_project_01_AI_USE.py` | ⚙️ |
| 0b | 素材跨合集时长均衡 | `src/util/balance.py` | ⚙️ |

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
| 6 | 添加行号 | `agent/tools/add_line_order.py` | 🤖 |
| 7 | LLM 字幕纠正 + 标题生成 | `src/deal_video_agent/` | 🤖 |
| 8 | 回写 srt | `agent/tools/update_srt.py` | 🤖 |
| 9 | 导入剪映替换字幕 | — | 待开发 |

### 阶段三：视频后处理

| 步骤 | 功能 | 实现 | 完成度 |
|------|------|------|--------|
| 10 | 分割 + 片头片尾拼接 | `src/splice_vedio/auto_splice_mp4.py` | ⚙️ |
| 11 | 批量重命名 | `.claude/skills/batch-video-renamer/` | 🎯 |
| 12 | 片单 Excel 生成 | 外部 skill `excel-sheet-generator`（不在本仓库） | 🎯 |
| 13 | 上传 / 整理网盘 | 百度网盘 MCP、夸克 MCP | 🎯 能力已具备，待封装 |

> 步骤 13 说明：两个 MCP Server 已提供 `upload_file` / `move` / `rename` / `regex_rename` 等工具，**不需要新写 Python 模块**，缺的只是一个把"成片目录 → 网盘目录"流程固定下来的 skill。

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
│   ├── baiducloud-operate/    # 百度网盘 MCP 用法（含 Token，不入库）
│   └── quarkpan-mcp-operate/  # 夸克网盘 MCP 用法（含 Token，不入库）
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
- 知识库是**游戏级资产**：`conf/知识库/{游戏名}/{主题}.md`（跨批次复用，跟着规则入库）

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

### 4. 字幕回写 — `src/words/`

- `updateSRT.py` — 把 `corrected.txt`（格式 `行号:纠正后内容`）回写为新 srt

> 旧版 `split_clean_srt.py`（按 6 分钟切 srt、去时间戳）已于 2026-11-07 删除：字幕在剪映导出时已烧录进画面，不需要再切分 srt。

### 5. 素材时长均衡 — `src/util/balance.py`

扫描各合集累加时长，超限的用 ffmpeg 关键帧切割（`-c copy`），溢出段移入下一合集。

```bash
python src/util/balance.py check --game 我的世界 --batch 2026-12
python src/util/balance.py move  --game 我的世界 --batch 2026-12 --from 合集一 --to 合集二 --apply
```

> 原 `.claude/skills/material-redistribute/` 已于 2026-11-07 删除：它和 `balance.py` 是同一件事的两套实现，且旧版路径写死、不支持跨批次。`balance.py` 有 37 个单测，是唯一保留的实现。

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
| 素材跨合集时长不均 | `src/util/balance.py` | ⚙️ 已自动 |
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
