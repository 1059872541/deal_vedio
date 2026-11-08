# 视频处理自动化流水线

把「录好的游戏素材」变成「能交付的成片 + 台账」的一条批量生产线。

录制和剪辑由人做，其余环节自动跑。一行命令推进一批，出错会说清楚下一步该做什么。

```powershell
vedio run --game 我的世界 --batch 2026-12 --collections 合集一,合集二 `
          --steps export,splice,rename,ledger
```

> 状态：**可用**。字幕、导出、拼接、命名、台账已在真实批次上跑通。
> 已知缺口见 [docs/现状.md](docs/现状.md)。

---

## 它解决什么

一批 20 集合集，手工做一遍要：剪 20 段、导 20 次、切 20 段、拼 40 个片头片尾、改 20 个文件名，
再对着 Excel 抄 20 行时长和标题。**每一步都不难，但每一步都会错。**

这个项目把中间那些"不难但会错"的活交给程序，人只保留需要判断的动作：

| 人做 | 机器做 |
|---|---|
| 录素材 | 匀素材（超额检测与切分） |
| 剪片（剪映） | 字幕加行号 / 纠错 / 回写 |
| 审字幕 | 导出（点剪映）、切分拼接（ffmpeg） |
| 定篇名 | 重命名、生成台账 |

---

## 快速开始

**依赖**：Windows、Python 3.12+、ffmpeg、剪映专业版（只用于导出）。

```powershell
python -m venv .venv
.venv\Scripts\pip install -r src/requirements.txt
```

**两个配置文件**（都不进 git）：

```yaml
# conf/本机.yaml —— 这台机器有什么
workspace:
  root: D:\VedioRecords\工作区
tool:
  ffmpeg: D:\softwares\ffmpeg\bin\ffmpeg.exe
  ffprobe: D:\softwares\ffmpeg\bin\ffprobe.exe
paths:
  ledger_root: D:\VedioRecords\剪辑要求
  excel_generator: ...\generate_excel_from_json.py   # 片单格式由它决定
```

```yaml
# conf/agent.yaml —— 用哪个账号和模型
deepseek:
  api_key: "sk-..."
  model: "deepseek-flash"
  max_tokens: 98304
```

模板分别是 `conf/本机.example.yaml`、`conf/agent.example.yaml`。逐步引导见
[docs/安装与配置.md](docs/安装与配置.md)。

**第一批**：

```powershell
vedio init --game 我的世界 --batch 2026-12 --collections 2 --host 波波
vedio status --game 我的世界 --batch 2026-12
```

---

## 一次完整流程

```
素材 → 匀素材 → 剪辑 → 字幕 → 篇名 → 导出 → 拼接 → 命名 → 台账
        ↑                ↑      ↑      ↑
      程序             程序   人工   程序
```

| 环节 | 谁做 | 交出什么 | 命令 |
|---|---|---|---|
| 素材 | 人 | `合集X/素材/*.mp4` | — |
| 匀素材 | 程序 | 各合集时长在容差内 | `vedio balance` |
| 剪辑 | 人（剪映） | 草稿 + 导出的 `.txt/.srt` | — |
| 字幕 | 程序 + 人审 | `*_corrected.srt` | `vedio subtitle` |
| 篇名 | 人拍板（模型提候选） | `标题.md` 的副标题 | `vedio series` |
| 导出 | 程序（点剪映） | `剪辑/*.mp4` | `vedio export` |
| 拼接 | 程序（ffmpeg） | `成片/*.mp4` | `vedio splice` |
| 命名 | 程序 | 按标题改好名 | `vedio rename` |
| 台账 | 程序 + 模型 | `{批次}/26年…片单.xlsx` | `vedio ledger` |

细节：[批次与目录](docs/批次与目录.md) · [状态与校验](docs/状态与校验.md)

---

## 命令一览

```powershell
vedio <动词> --game <游戏> --batch <批次> [--collections 合集一,合集二]
```

| 动词 | 干什么 |
|---|---|
| `paths` | 看目录在哪 |
| `status` | 进度表（从文件推导，不是数据库） |
| `logs` | 看批次日志 |
| `balance` | 查素材超额 / 把一个合集多的切给下一个 |
| `init` | 建批次；`--add` 给已有批次加合集 |
| `subtitle` | 加行号 → 纠错 → 回写 srt |
| `series` | 定篇名；`--suggest` 让模型提候选 |
| `export` | 批量导出剪映草稿 |
| `splice` | 切分 + 拼片头片尾 |
| `rename` | 按 `标题.md` 改名 |
| `ledger` | 生成交付用片单 |
| `run` | 按 `--steps` 顺序推进（夜里无人值守用这个） |

全局参数：`--json`（结构化结果）、`--quiet`（只留结论，过程进日志）。

---

## 目录长什么样

```
<workspace.root>/我的世界-2026-12/
├── game.yaml          本批次配置（建完定稿）
├── 进度.md            每个合集走到哪一步（人可手改）
├── 标题.md            公共前缀 + 每合集一节（副标题 + 各集标题）
├── 合集清单.yaml      草稿名、片头片尾映射
├── 26年波波12月第一批片单.xlsx   台账（交付物）
├── log/               每次调用的完整日志
└── 合集/合集一/{素材,剪辑,成片}/
```

---

## 代码结构

| 目录 | 是什么 |
|---|---|
| `src/vedio/` | **命令行内核**：12 个动词、从文件推状态、跑 ffmpeg |
| `src/deal_video_agent/` | 字幕纠错 agent（LangGraph）+ 提示词目录 |
| `src/jianying_export/` | 剪映 GUI 自动化（导出） |
| `src/util/` | 零散工具（匀素材的底层实现等） |

设计原则：**文件系统即真相**（没有数据库）；**内核不知道模型存在也能跑**（除字幕那一段）。

为什么这样设计、踩过什么坑：见 [EVOLUTION.md](EVOLUTION.md)。

---

## 开发

```powershell
.venv\Scripts\python -m unittest discover -s tests     # 634 个用例
```

---

## 文档地图

| 你是谁 | 从哪开始 |
|---|---|
| **使用者** | 本文件 → [安装与配置](docs/安装与配置.md) → [批次与目录](docs/批次与目录.md) |
| **想接手的开发者** | [现状](docs/现状.md) → [EVOLUTION.md](EVOLUTION.md) → `src/vedio/` |
| **AI 助手** | [AGENTS.md](AGENTS.md)（操作契约，不是给用户读的入口） |

其余文档：[日志](docs/日志.md) · [状态与校验](docs/状态与校验.md) ·
[目标架构](docs/目标架构.md) · [流水线现状](docs/流水线现状.md)
