# 项目概述

## 项目名称：视频处理自动化脚本

这是一个Python项目，专门用于自动化处理视频文件，实现从剪映草稿到成品视频的完整流水线。

## 核心目标

实现**全自动化的视频处理流水线**：
```
录制 → 剪辑 → 字幕处理 → LLM字幕纠正+标题生成 → 视频分割拼接 → 自动重命名 → Excel片单生成 → 上传百度网盘
```

---

## 完整工作流（从录制到Excel）

### 完成度标识说明

| 维度 | 标识 | 含义 |
|------|------|------|
| **环节内自动化** | | |
| 纯手动 | 👤 | 完全人工操作 |
| 半自动-手动运行 | ⚙️ | 配置参数，主动运行脚本 |
| 半自动-监控模式 | 👁️ | 脚本持续运行，自动处理新文件 |
| 全自动-Agent | 🤖 | LangGraph Agent，多步骤自动串联 |
| 全自动-Skill | 🎯 | OpenCode Skill，对话式引导自动完成 |
| **环节间串联** | | |
| 断链 | ❌ | 需手动加载下一个Skill/Agent |
| 已串联 | ✅ | 自动衔接 |

### 阶段零：项目初始化（创建目录）

| 步骤 | 功能 | 实现 | 完成度 | 串联 |
|------|------|------|--------|------|
| 0a | 创建项目目录 | `scaffold/new_project.py` | ⚙️ | - |
| 0b | 创建项目目录(AI版) | `scaffold/new_project_01_AI_USE.py` | ⚙️ | - |
| 0c | 素材合集间时长均衡 | `util/redistribute_material.py` | ⚙️ | - |

### 阶段一：素材准备与剪辑

| 步骤 | 功能 | 实现 | 完成度 | 串联 |
|------|------|------|--------|------|
| 1 | OBS 录屏 | OBS Studio | 👤 | - |
| 2 | 素材整理 | 手动整理到素材目录 | 👤 | - |
| 3 | 剪映剪辑 | 手动剪辑+添加元素 | 👤 | - |
| 4 | 导出草稿 | `jianying_export/export_draft.py` | ⚙️ | - |

### 阶段二：字幕处理

| 步骤 | 功能 | 实现 | 完成度 | 串联 |
|------|------|------|--------|------|
| 5 | 导出字幕(srt+txt) | 剪映导出 | 👤 | - |
| 6 | 字幕清洗为txt | `words/split_clean_srt.py` | ⚙️ | - |
| 7 | 添加行号 | `agent/tools/add_line_order.py` | 🤖 | ✅ |
| 8 | LLM字幕纠正+标题生成 | `deal_video_agent/` Agent | 🤖 | - |
| 9 | 更新srt字幕 | `agent/tools/update_srt.py` | 🤖 | ✅ |
| 10 | 导入剪映替换字幕 | 待开发 | 👤 | - |

### 阶段三：视频后处理

| 步骤 | 功能 | 实现 | 完成度 | 串联 |
|------|------|------|--------|------|
| 11 | 视频分割+片头片尾拼接 | `splice_vedio/auto_splice_mp4_4.py` | ⚙️ | - |
| 12 | 重命名视频 | `video-rename-1.0` Skill | 🎯 | ❌ |
| 13 | Excel片单生成 | `excel-sheet-generator` Skill | 🎯 | - |
| 14 | 上传百度网盘 | 待开发 | 👤 | - |

### 主入口

```
run_workflow.py  # 根目录主入口，串联各步骤（待创建）
```

---

## 项目结构

```
deal_vedio/
├── .env                        # 本地环境配置（FFmpeg路径等）
├── EVOLUTION.md                # 项目演进决策日志
├── .venv/                      # Python虚拟环境
├── run_workflow.py             # 主入口（待创建）
├── IFLOW.md                    # 项目说明文件
├── system_prompt.md            # AI助手系统提示
├── doc/                        # 文档目录
├── src/                        # 源代码目录
│   ├── scaffold/               # 项目初始化（创建目录）
│   ├── deal_video_agent/      # 字幕纠正+标题生成Agent (LangGraph)
│   ├── jianying_export/       # 剪映自动化导出 ✅
│   ├── words/                 # 字幕处理模块
│   ├── splice_vedio/          # 视频拼接模块
│   ├── title/                 # 标题处理模块
│   ├── util/                  # 工具模块（素材时长均衡等）
│   └── repeat/                # 重复检测模块
├── .opencode/                  # OpenCode Skills
│   └── skills/
│       └── video-cut/
│           ├── video-rename-1.0/     # 视频重命名Skill
│           └── excel-sheet-generator/  # Excel片单生成Skill
└── test/                       # 测试目录

---

## 各模块详细说明

### 0. 项目初始化模块 (scaffold/)

**功能**：创建视频项目目录结构，规定真正的目录框架

**位置**：`src/scaffold/new_project.py`（基础版）、`src/scaffold/new_project_01_AI_USE.py`（AI调用版）

**完成度**：⚙️ 半自动化（手动运行脚本）

**核心功能**：
- 新建游戏项目：创建完整工作区+可配置合集数量
- 追加新合集：自动推断序号或指定名称
- 批量追加合集：`--add-collections N` 一次追加N个
- 列出所有合集：中文数字智能排序
- 目录深度控制：`--depth 1~4`（1=仅游戏目录，4=完整结构）
- 试运行预览：只打印不执行，验证结果
- JSON输出：`--json` 供AI解析
- 断点日志：已处理合集状态持久化，支持断点续跑

**目录结构**：
```
工作区/{游戏名}/
├── game.yaml              # 合集命名映射、片头片尾配置
├── 术语库/
├── 片头/
├── 片尾/
├── 素材库/
├── 合集/
│   ├── 合集一/
│   │   ├── 素材/
│   │   ├── 剪辑/
│   │   └── 成片/
│   ├── 合集二/
│   └── 合集三/
└── log/                    # 运行日志
```

**使用方式**：
```bash
# 基础版（旧）
python src/scaffold/new_project.py 我的世界

# AI调用版（新）
python src/scaffold/new_project_01_AI_USE.py 泰拉瑞亚 --json
python src/scaffold/new_project_01_AI_USE.py 我的世界 --depth 3 --collections 5
python src/scaffold/new_project_01_AI_USE.py 我的世界 --add-collections 3 --json
python src/scaffold/new_project_01_AI_USE.py 我的世界 --list --json
python src/scaffold/new_project_01_AI_USE.py 我的世界 --force --depth 2  # 补缺
```

---

### 1. 字幕纠正 Agent (deal_video_agent/)

**功能**：基于 LangGraph 的 AI Agent，自动化完成字幕纠正和标题生成

**完成度**：🤖 全自动化（Agent）

**核心特性**：
- 使用 DeepSeek Reasoner 模型
- Context Caching 优化 API 费用（90%节省）
- 流式输出显示进度
- 结构化日志（structlog）
- 知识库支持（两层结构：大主题+具体内容）

**文件**：
- `agent/state.py` - Agent 状态定义
- `agent/nodes.py` - LangGraph 节点实现
- `agent/subtitle_agent.py` - 主入口
- `agent/logger.py` - 日志系统
- `agent/tools/deepseek_api.py` - DeepSeek API 客户端
- `agent/tools/knowledge_base.py` - 知识库工具
- `agent/tools/titles_manager.py` - 标题管理
- `prompts/subtitle_correction.yaml` - 提示词模板

**使用方式**：
```python
from src.deal_video_agent.agent import run_subtitle_agent, print_result

result = run_subtitle_agent(
    target_dir=r"D:\VedioRecords\工作区\我的世界\合集十\剪辑",
    user_prompt="本次视频主要内容关于【暮色森林模组】..."
)
print_result(result)
```

**监控模式**：
```bash
python src/deal_video_agent/monitor_subtitle.py
```

---

### 2. 剪映自动化模块 (jianying_export/)

**功能**：通过uiautomation自动化控制剪映，批量导出草稿视频

**完成度**：⚙️ 半自动化（手动运行脚本）

**文件**：
- `controller.py` - 剪映控制器核心（修复了CPU使用率问题）
- `exceptions.py` - 异常定义
- `export_draft.py` - 批量导出脚本（主入口，支持JSON配置）
- `config.example.json` - 配置文件示例
- `README.md` - 详细使用文档
- `test_import.py` - 导入测试脚本

**使用方式**：
```bash
# 使用默认配置
python -m src.jianying_export.export_draft

# 使用配置文件
cp src/jianying_export/config.example.json src/jianying_export/config.json
# 编辑config.json后运行
python -m src.jianying_export.export_draft
```

---

### 3. 字幕处理模块 (words/)

**功能**：SRT字幕文件的清洗、分割、更新

**完成度**：⚙️ 半自动化（手动运行脚本）

**文件**：
- `split_clean_srt.py` - 将srt按时间段分割为纯文本txt
- `updateSRT.py` - 将纠正后的文本更新回srt文件
- `add_line_order.py` - 给txt添加行号

---

### 5. 视频拼接模块 (splice_vedio/)

**功能**：监听目录，自动分割长视频并添加片头片尾

**完成度**：⚙️ 半自动化（手动运行脚本）

**文件**：
- `auto_splice_mp4_4.py` - **主用**，功能完善的版本
- `split_by_time.py` - 按时间分割工具
- `path_to_json.py` - 路径转JSON工具
- `with_end.py` - 添加片尾

**功能特点**：
- 多目录并行监听
- 硬件加速编码支持
- 任务队列+失败重试
- 元数据记录
- 支持合集级片头片尾配置

---

### 6. 标题处理模块 (title/)

**功能**：获取视频时长、重命名视频

**完成度**：⚙️ 半自动化（脚本可用）

**文件**：
- `update_title.py` - 按"前缀 第X集"格式重命名
- `get_videos_duration.py` - 批量获取视频时长

---

### 6b. 素材时长均衡 (util/redistribute_material.py)

**功能**：将超限合集的末尾素材自动切割，溢出部分移至下一合集，级联处理

**完成度**：⚙️ 半自动化（手动运行脚本）

**使用场景**：每个合集预期 2h 素材，实际录制超时。自动找到跨越 2h 边界的文件，ffmpeg 关键帧切割，后段以 {N}-0.mkv 命名移入下一合集。

**核心特性**：
- ffmpeg 无重编码切割（`-c copy`，秒级精度）
- 级联处理：合集二收到溢出后重新计算，若仍超限继续切割
- 断点续跑：`.redistribute_log.json` 持久化处理状态，双重验证跳过已处理合集
- JSON输出供AI调用

**使用方式**：
```bash
python src/util/redistribute_material.py 我的世界-2026-06
python src/util/redistribute_material.py 我的世界-2026-06 --target 90m --dry-run
python src/util/redistribute_material.py 我的世界-2026-06 --json
python src/util/redistribute_material.py 我的世界-2026-06 --force  # 忽略日志，强制重跑
```

---

### 7. 视频重命名 Skill (video-rename-1.0)

**功能**：OpenCode对话式引导，批量重命名视频文件

**完成度**：🎯 全自动化（Skill）

**位置**：`D:\study\zack的个人知识库\opencode-skills-global\video-cut\video-rename-1.0`

**文件**：
- `SKILL.md` - Skill定义文件
- `scripts/rename_videos.py` - 重命名脚本

**工作流程**：
1. 用户提供合集目录、前缀、20个标题
2. AI引导确认重命名方案
3. 安全预览实际效果
4. 执行批量重命名

**使用方式**：
```bash
# 在OpenCode中加载 skill
skill: video-rename-1.0
```

**串联状态**：❌ 断链（需手动加载Skill）

---

### 8. Excel片单生成 Skill (excel-sheet-generator)

**功能**：扫描视频目录，生成片单Excel，AI自动生成内容介绍和关键字

**完成度**：🎯 全自动化（Skill）

**位置**：`D:\study\zack的个人知识库\opencode-skills-global\video-cut\excel-sheet-generator`

**功能**：
1. 扫描视频目录，提取视频信息（标题、时长等）
2. 填充Excel模板
3. 调用AI生成内容介绍和关键字

**使用方式**：
```bash
# 在OpenCode中加载 skill
skill: excel-sheet-generator
```

---

## 技术栈

- **编程语言**：Python 3.13+
- **视频处理**：FFmpeg (通过subprocess调用)
- **剪映自动化**：uiautomation
- **AI Agent**：LangGraph + DeepSeek Reasoner
- **MCP Server**：百度网盘、夸克网盘等
- **依赖管理**：pip + requirements.txt
- **并发处理**：threading + ThreadPoolExecutor
- **日志系统**：structlog

---

## 痛点解决状态

| 痛点 | 解决方案 | 完成度 |
|------|----------|--------|
| 字幕纠正（手动10-20分钟） | deal_video_agent Agent | 🤖 |
| 标题生成（手动AI对话） | deal_video_agent Agent | 🤖 |
| 字幕审查（人工验证10-30分钟） | 待改进 | 👤 |
| 剪映导出（40分钟等待） | jianying_export | ⚙️ |
| 视频重命名（手动） | video-rename-1.0 Skill | 🎯 |
| Excel填写（手动+AI对话） | excel-sheet-generator Skill | 🎯 |
| 素材跨合集时长不均 | redistribute_material | ⚙️ |
| 百度网盘上传（人工） | 待开发 | 👤 |

---

## 待办事项

### 高优先级

- [ ] 创建 run_workflow.py 主入口（实现全流程串联）
- [ ] 实现字幕导入剪映功能（步骤10）

### 中优先级

- [ ] 百度网盘上传自动化（步骤14）

### 终极目标

```
只需录制视频 → AI自动完成后续所有环节 → 审阅最终结果
```

### 暂停/废弃

- [x] adjust_vedio/ 模块 - 效果未达预期，暂停开发
- [x] watermark/ 模块 - 效果未达预期，暂停开发
- [x] client/ 模块 - 架构复杂，已弃用

---

## 开发规范

1. **按步骤执行**：按照工作流顺序逐步开发
2. **先分析后动手**：先理解代码再修改
3. **简洁原则**：回答简洁，不做不必要的解释
4. **代码规范**：
   - 不添加多余注释
   - 复用现有代码
   - 保持代码风格一致

---

## 使用说明

### 运行主流程

```bash
# 激活虚拟环境
.venv\Scripts\activate.bat

# 运行工作流
python run_workflow.py
```

### 单独运行各模块

```bash
# 项目初始化（⚙️ 半自动化-手动运行脚本）
python src/scaffold/new_project.py 我的世界
python src/scaffold/new_project.py 我的世界 -a  # 追加合集

# 项目初始化 - AI调用版
python src/scaffold/new_project_01_AI_USE.py 泰拉瑞亚 --json
python src/scaffold/new_project_01_AI_USE.py 我的世界 --add-collections 3
python src/scaffold/new_project_01_AI_USE.py 我的世界 --list

# 素材合集间时长均衡
python src/util/redistribute_material.py 我的世界-2026-06
python src/util/redistribute_material.py 我的世界-2026-06 --dry-run --json

# 字幕纠正 Agent（🤖 全自动化-Agent）
python src/deal_video_agent/monitor_subtitle.py

# 字幕清洗（⚙️ 半自动化-手动运行脚本）
python -m src.words.split_clean_srt

# 视频拼接（⚙️ 半自动化-手动运行脚本）
python -m src.splice_vedio.auto_splice_mp4_4

# 视频重命名（🎯 全自动化-Skill）
# 在OpenCode中加载: skill: video-rename-1.0

# Excel片单生成（🎯 全自动化-Skill）
# 在OpenCode中加载: skill: excel-sheet-generator
```

---

## 注意事项

- 所有路径配置在脚本顶部，便于修改
- 视频分割默认6分钟一段，可配置
- 片头片尾按合集独立配置
- 剪映自动化需要保持剪映窗口在前台
