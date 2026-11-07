# TODO

> 只放**当前仍然有效**的待办。
> 判断标准：这条在当前架构下还有意义吗？
>
> 会被重构整体取代的、判断为不需要的，已移到 `research/TODO-归档.md`（不入库）。
> 架构与流程见 `docs/`。

---

## P0 — 能立刻动手的 bug

- [ ] **`jianying_export/controller.py` 的三个坑**

      1. **死循环**：`while True` 里的 `if app_status != "pre_export": continue`
         跳过了下面的超时检查 → 状态认不出时永不退出，
         而且每圈 `SetActive + SetTopmost` 反复把剪映抢到前台。
         （README 里"可能陷入死循环"说的就是它）

      2. **固定 `sleep(60) + sleep(60)`**（`controller_new` 版是 `10 + 10`）。
         加等待的原因是真实的：笔记本上剪映渲染慢，尤其 2 小时草稿。
         但固定值两头不对 —— 短草稿浪费、长草稿可能还不够。
         **改法**：条件等待 = 等目标控件出现 + `BoundingRectangle` 非零且连续 2 次稳定，
         上限 **180 秒**。

      3. **导出路径走 `SetValue`**，在 6.0.1 上无效（控件是 `QQuickText`，无 ValuePattern）。
         `controller_new` 因此把 `shutil.move` 注释掉了 —— 方向错了。
         **改法**：恢复 `shutil.move`，用界面读到的真实路径
         （导出面板里有个 `TextControl`，其 `FullDescription` 就是完整输出路径）。

- [ ] **标题文件 header 硬编码 + 修复已损坏的数据**

      `titles_manager.py` 第 30 / 40 / 153 行写死 `# 我的世界系列视频标题列表`。
      **后果已经发生**：`titles/足球在线4-2026-06_titles.md` 第一行现在是"我的世界"。
      两件事：① 改成 `f"# {clean_name}系列视频标题列表"`；② 修正已有文件。

---

## P1 — 该做但要排期

- [ ] **把用户数据从 `src/` 清出仓库**

      `src/deal_video_agent/titles/` 2 个 `.md` 和 `knowledge_base/` 8 个 `.md` 都被 git 跟踪。
      按新架构，标题应写到批次的 `标题.md`；知识库属于游戏级配置。
      这批文件留在 `src/` 里 = 用户业务数据跟着代码走，`git clean` 会一起删掉。

- [ ] **回归测试集**

      建 20–30 条标注样本，提示词变动后自动验证是否回归。

---

## P2 — 未来可能

- [ ] **网盘上传整理 skill 封装**（**暂缓**）

      百度 / 夸克 MCP 已提供 `upload_file` / `move` / `rename` / `regex_rename`，
      不需要写 Python，只缺一个固定「成片目录 → 网盘目录」流程的 skill。

- [ ] 多模型对比基准（deepseek-v4-pro vs reasoner）
- [ ] Web 可视化仪表盘（基于 `events.jsonl`）
- [ ] 知识库自动合并 / 去重

---

## 已完成

- [x] **草稿自动发现**：改读剪映索引 `root_meta_info.json`，不再靠文件夹名（2026-11-07，`context.py` + 13 个测试）
- [x] **`_corrected.srt` 去 BOM**：改为 UTF-8 无 BOM + CRLF，对齐剪映自己导出的格式（2026-11-07）
- [x] **删除 `split_clean_srt.py`**：字幕已烧录进画面，不需要再按 6 分钟切 srt（2026-11-07）
- [x] **删除 `material-redistribute` skill**：与 `balance.py` 重复实现（2026-11-07）
- [x] 标题 system prompt 硬编码：已改为模板变量（2026-11-06）
- [x] 移除死代码约 4,300 行（详见 README 的「2026-11-06 清理记录」）
- [x] 建立 git 版本控制基线
