# 字幕纠正 Agent 迭代记录 2026-06-06

> 本次迭代围绕三个问题展开：标题质量、知识库质量、标题文件管理。涉及 5 个文件，包含已实施和已设计待实施的变更。

---

## 一、标题生成质量修复

### 问题
用户输入"愚者整合包"后，生成的 20 个标题全部以"愚者"开头（如"初入愚者世界""愚者遗物探寻"）。

### 根因
`generate_title` 节点读取了字幕文件（`subtitle_content`），但从未将其传入 prompt 模板。LLM 收到的唯一语义信息是系统提示词中的"当前合集主题：我的世界愚者整合包"，因此唯一能用的关键词只有"愚者"。

```python
# ❌ 改前：subtitle_content 读到就扔
subtitle_content = f.read()  # 读了
user_prompt = title_prompt_template.format(existing_titles=existing_titles)  # 没传
```

### 改动

**文件**：`prompts/subtitle_correction.yaml`（title_prompt）、`agent/nodes.py`（generate_title）

1. 在 title_prompt 中添加 `{subtitle_content}` 占位符
2. 新增要求"标题应多样化，不要在每个标题中都重复合集主题词"
3. `generate_title` 中将 `subtitle_content` 传入 `format()`

```python
# ✅ 改后：subtitle_content 传进 prompt
user_prompt = title_prompt_template.format(
    subtitle_content=subtitle_content,
    existing_titles=existing_titles
)
```

### 效果
第二次生成的 20 条标题无一条以"愚者"开头，主题覆盖了探索、战斗、建造等多个维度。

---

## 二、知识库构建 Prompt 优化

### 问题
知识库内容单薄，仅包含一张模组概览表。整合包实际包含的大量实体（生物、物品、机制）未被收录。

### 分析
原 prompt 只有一句"搜索网络信息收集词汇"，缺乏对输出结构和内容的指引。LLM 倾向于输出概括性描述而非实体清单。

### 改动

**文件**：`prompts/subtitle_correction.yaml`（system_prompt → knowledge_build）

1. **保留原始角色设定**："游戏资深主播，负责纠正字幕问题"
2. **不注入字幕原文**：知识库覆盖整个模组，单集字幕不能代表全集
3. **新增 5 个通用提取维度**：

| 维度 | 说明 |
|---|---|
| 实体名称 | 生物/怪物、物品/装备、方块/材料、技能/能力 |
| 地点与场景 | 维度、建筑、结构、区域 |
| 玩法机制与术语 | 特有系统和对应术语 |
| 玩家惯用语 | 简称、谐音、社区黑话 |
| ASR 易错词 | 同音/近音误识别形式（字幕纠正的关键依据） |

4. **新增输出约束**：表格输出、反幻觉（不确定标"需确认"）、搜索补充标注

### 决策依据
- 5 个维度是**全游戏通用**的，不绑定"愚者整合包"或任何特定游戏
- 强调 ASR 易错词的维度，因为知识库的核心用途是提高字幕纠正准确率
- 约束"不编造"+"搜索补充标注"两段话约束幻觉

---

## 三、标题文件管理重构

### 问题集合

| # | 问题 | 表现 |
|---|---|---|
| 1 | 所有游戏共用标题文件 | 不同游戏的标题混在一起，互相干扰 |
| 2 | 合集名提取错误 | `_extract_collection_name` 只查最后一级文件夹名 |
| 3 | 追加方式有风险 | 全文解析→重建，解析出错则数据丢失 |

### 改动

#### 3.1 文件命名：per-game 独立文件

**文件**：`agent/nodes.py`（`_get_titles_manager`）

```python
# 改前：单文件
title_file = "titles/all_collection_titles.md"

# 改后：按 game_name 命名
title_file = f"titles/{game_name}_titles.md"
```

同时删除了 `_titles_manager` 全局单例——每次调用按需创建新实例即可。

**影响范围**：`agent/subtitle_agent.py` 中的 `clear_titles` 同步更新。

#### 3.2 合集名提取：遍历全部路径层级

**文件**：`agent/nodes.py`（`_extract_collection_name`）

```python
# 改前：只查 path.name
folder_name = path.name  # = "剪辑"
match = re.search(r'合集[一二三四五六七八九十\d]+', folder_name)  # 不匹配

# 改后：遍历 path.parts（从内到外）
for part in reversed(parts):  # "剪辑" → "合集一" → "合集" → ...
    match = re.search(r'合集[一二三四五六七八九十\d]+', part)
    if match:
        return match.group()  # = "合集一"
```

#### 3.3 追加策略：新合集直接追加，同名才重建

**文件**：`agent/tools/titles_manager.py`（`append_titles`）

```
新合集 → 直接 append 到文件末尾，已有内容不做任何解析或重写
同名合集且 overwrite=True → 全文重建以替换内容
```

降低了解析异常导致数据丢失的风险。

#### 3.4 数据恢复

由于文件名变更，第一次运行（合集一）产生的标题存储在旧文件 `all_collection_titles.md` 中，第二次运行创建了新文件，数据断裂。已手动将合集一的 20 条标题恢复到新文件 `我的世界-2026-06_titles.md`。

---

## 四、性能追踪方案（待实施）

已设计但尚未编码的性能评估方案：

### 设计

```
┌─────────────────────────────────────────────┐
│  装饰器 @trace_node（AOP 切面）               │
│  作用：包裹所有 langgraph 节点函数             │
│  功能：记录节点耗时 → 写入 state.node_timings  │
├─────────────────────────────────────────────┤
│  DeepSeekClient 改造                         │
│  作用：stream_chat_with_progress 返回 usage   │
│  功能：解析最后 chunk 的 usage 字段            │
├─────────────────────────────────────────────┤
│  终端展示 + 日志存储                           │
│  终端：节点耗时百分比、token 汇总、缓存命中率   │
│  日志：逐次 API 明细、完整 JSON 留底           │
└─────────────────────────────────────────────┘
```

### 产出样例

```
节点耗时:
  parse_input（解析输入）          0.002s    0.0%
  correct_subtitle（纠正字幕）    12.340s   78.2%  ← API调用
  generate_title（生成标题）       3.210s   20.3%  ← API调用
  ────────────────────────────────────────────────
  总计                           15.783s  100.0%

Token 消耗: 4,650 tokens | 预估成本 ~$0.008
缓存命中: 0 / 3,650 = 0.0%
```

### 状态：待编码
- [ ] `state.py` — 加 `node_timings` 和 `api_details` 字段
- [ ] `deepseek_api.py` — `stream_chat` 解析 usage 并返回
- [ ] `nodes.py` — 节点加上 `@trace_node` 装饰器
- [ ] `subtitle_agent.py` — `print_result` 增加性能区块
