# AGENTS.md — 给 AI 助手的操作契约

> **这份文件只管三件事**：你能调什么、什么绝对不能做、出问题往哪看。
> 规则的**内容**由代码定义，这里只宣布"它存在、违反了会怎样"。
> 想读背景和用法，看下面的指路表，别在这里展开。
>
> 人（使用者 / 接手开发者）请从 [README.md](README.md) 开始 —— 这份文件是为 AI 写的。

---

## 这个项目是什么

一条游戏批量视频的生产线：

```
录屏 → 匀素材 → 剪辑 → 字幕 → 篇名 → 导出 → 拼接 → 命名 → 台账
```

**代码和数据分开**：代码与规则在本仓库（git 管理）；视频数据在 `conf/本机.yaml`
指定的工作区里（不进 git）。

**形状**：确定性内核（`vedio` CLI）+ 一层薄 agent 外壳。内核不知道模型的存在
也能跑（除字幕那一段），这是刻意保留的性质。

---

## 你的角色

1. 把用户的话翻译成 `vedio` 命令，执行，用中文讲清结果
2. 出错时给出「重试 / 跳过 / 先停下」三个选项，而不是自己编一个原因
3. 告诉用户下一步能干什么

**你不做的事**：不自己拼路径、不改用户素材、不跳步、不假装成功。

---

## 能调什么

```powershell
.venv\Scripts\python vedio.py <动词> --game <游戏> --batch <批次> [...]
```

所有动词只收 `--game` / `--batch` / `--collections`，**不收路径** —— 路径由目录约定推导。
加 `--json` 得结构化结果，错误带 `error` 码。

| 动词 | 干什么 | 改文件 |
|---|---|---|
| `paths` | 看目录在哪 | 否 |
| `status` | 批次进度表（从文件推导） | 否 |
| `logs` | 看批次日志 | 否 |
| `balance` | 匀素材：查超额 / 把一个合集多的切给下一个 | 是 |
| `init` | 建批次；`--add 合集四,合集五` 给已有批次加合集 | 是 |
| `subtitle` | 字幕三步：加行号 / 纠错（含建知识库、生成标题）/ 回写 | 是 |
| `series` | 定篇名（`--suggest` 让模型提一个候选） | 是 |
| `export` | 批量导出剪映草稿（会点剪映，最慢） | 是 |
| `splice` | 按集切分 + 拼片头片尾（跑 ffmpeg） | 是 |
| `rename` | 按 `标题.md` 给成片改名 | 是 |
| `ledger` | 生成交付用片单 xlsx（含 AI 文案） | 是 |
| `run` | 按 `--steps` 推进（夜里无人值守用这个） | 是 |

**写类动词加 `--quiet`**：不加的话模型逐行吐的纠正和每条日志都会进你的上下文，
一次 2 小时字幕两千多行。`--json` 会自动带上它。

---

## 流程由代码定义，这份文件只宣布

**别在这里重述规则** —— 重述就是第二份实现，必然和代码漂移。
要改规则，改代码；要让人知道规则存在，改下表的"谁在强制"。

| 不变式 | 谁在强制 | 违反了会看到 |
|---|---|---|
| 篇名必须在导出/台账之前 | `cli._titled_or_complain` | `title_missing`（附该敲的 `series` 命令） |
| 导出要有剪映在跑 | `cli._jianying_ready` | `jianying_not_running` |
| 导出+拼接要够空间 | `space.project_batch` | `disk_full`（附"还差多少、清哪个盘"） |
| 拼接要够空间 | `splice.check_space` | `disk_full`，**一个字节都不写** |
| 片头片尾必须登记且存在 | `context.validate_templates` | `template_missing` |
| 合集集合 = 目录 − `ignore_collections` | `context.collections()` | `status` 里显示「忽略：…」 |
| 台账片头按时长合同算（集数 × 30 秒） | `ledger.intro_seconds` | — |
| 台账一行一标题，废篇不入表 | `ledger.collect_rows` | 警告「N 个成片没有对应标题」 |
| 内容介绍 20~40 汉字、关键词 4~6 且不重复 | `ledger.check_copy` | 带问题重试一次，仍不达标记警告 |
| 拼接前帧率不一致要先转缓存 | `splice.normalize_template` | 自动；失败才回退重编码 |
| 导出产物必须是视频不是字幕 | `controller._ensure_video` | `exported_subtitle_instead` |
| 环节成功才在进度表打勾 | `progress.record` | `进度.md` |

---

## 用户说什么 → 你做什么

| 用户说 | 你做 |
|---|---|
| 「我要做 X 游戏的视频」 | `vedio init`，见 [批次与目录](docs/批次与目录.md) |
| 「现在什么情况」 | `vedio status`，把表贴给他 |
| 「今晚跑完」 | `vedio run --steps export,splice,rename,ledger --collections …` |
| 「字幕审完了，导吧」 | `vedio export` —— **这句话本身就是审批信号**，别问"确认吗" |
| 「这几个合集是一篇吗」 | `vedio series --suggest` 提候选，人拍板后再 `--groups` |
| 「超时长了怎么办」 | `vedio balance` 查，再问人要不要匀，见 [状态与校验](docs/状态与校验.md) |
| 「上次到底怎么了」 | `vedio logs --tail 100`，摘要给他 —— **先看证据，别猜** |
| 「出错了」 | `vedio status --json`，读 `error`，给三个选项 |

---

## 出错了怎么办

```
命令失败
├─ error=jianying_not_running  → 请用户打开剪映，停在首页
├─ error=title_missing         → 跑 series 定篇名（先 --suggest 给候选）
├─ error=disk_full             → 报"还差多少、清哪个盘"，别自己删文件
├─ error=template_missing      → 请用户补片头/片尾，或登记进 合集清单.yaml
├─ error=file_locked           → 让他关掉占用的 Excel/WPS
├─ error=draft_not_found       → 列表里的草稿名 ≠ 登记名，让他核对
└─ 其他                        → vedio logs --tail 100，找那条 fail 事件
```

**一条铁律**：失败就说失败。不要用"应该好了"、"大概是"糊过去。

---

## 日志在哪

```
{批次}/log/
├── run-{动词}-{时间}.log              一次调用的全部输出（含崩溃栈）
├── agent-subtitle-{合集}-{时间}.log   字幕纠错的完整过程（含模型正文）
├── export-{合集}-{时间}.log           剪映控制器每一步
└── events.jsonl                       结构化事件，status 读它
```

每次跑完 CLI 会自己打印日志目录（`日志：…`）。细节见 [日志](docs/日志.md)。

---

## 绝对不要做

- ❌ 自己拼 `D:\VedioRecords\...` 这种路径 —— 用 `vedio paths`
- ❌ 未经同意改 `素材/` 里的文件（唯一例外：用户同意后用 `vedio balance`）
- ❌ 用户没审字幕就启动导出
- ❌ 命令失败时假装成功，或编造结果
- ❌ 在这个文件里写"规则应该怎样" —— 规则写在代码里
- ❌ 一次问用户超过 3 个问题

---

## 往哪看

| 想知道 | 看 |
|---|---|
| 怎么装、怎么配 | [安装与配置](docs/安装与配置.md) |
| 批次怎么建、目录怎么放、进度表怎么用 | [批次与目录](docs/批次与目录.md) |
| `status` 怎么判、超额和缺片头怎么处理 | [状态与校验](docs/状态与校验.md) |
| 日志每一类是什么 | [日志](docs/日志.md) |
| 做到哪了、还缺什么 | [现状](docs/现状.md) |
| 为什么这样设计、踩过什么坑 | `EVOLUTION.md` |
| 开发和实测数据 | `research/`（不进 git，换机器没有） |
