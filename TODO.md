# TODO

## P0 - 下一次迭代

- [ ] 性能数据持久化（JSONL）：每次运行将性能指标写入 `logs/performance.jsonl`
- [ ] 修正量统计：解析 correct_subtitle 输出，按修正类型（同音字/术语/脏话）归类计数

## P1 - 规划中

- [ ] 回归测试集：建 20~30 条标注样本，提示词变动后自动验证是否有回归
- [ ] 标题违禁词列表可配置化：不同游戏可配置不同的违禁词，不硬编码在 YAML 中
- [ ] 标题 system prompt 硬编码修复：`负责为我的世界游戏视频` → `{clean_name}`
- [ ] 标题文件 header 硬编码修复：`我的世界系列视频标题列表` → `{clean_name}系列`

## P2 - 未来可能

- [ ] 多模型对比基准（deepseek-reasoner vs v4-flash）
- [ ] Web 可视化仪表盘（基于 JSONL 日志）
- [ ] 知识库自动合并/去重
