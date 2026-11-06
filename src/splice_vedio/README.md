# 视频分割与拼接 — `auto_splice_mp4.py`

监听多个合集目录，自动把长录播切成 6 分钟片段，每段拼接片头与片尾，输出到 `成片/`。

## 做什么

```
剪辑/长视频.mp4
   │  ① 关键帧分割（-c copy，无重编码，零画质损失）
   ▼
片段队列（每段约 6 分钟）
   │  ② 并行拼接：片头 + 片段 + 片尾（硬件编码器优先）
   ▼
成片/xxx-1.mp4、xxx-2.mp4 …
   │  ③ 拼接成功后清理中间片段
   ▼
完成
```

## 运行

```bash
python src/splice_vedio/auto_splice_mp4.py
```

需要先改文件顶部的配置常量（见下节）。Ctrl+C 可中断，状态保存在元数据文件中。

## 配置

| 常量 | 作用 |
|------|------|
| `WATCH_DIRECTORIES` | 待监听目录字典，每个 key 可单独配 `watch_duration`（稳定时长）、`input_dir`（默认 `剪辑`）、`output_dir`（默认 `成片`）、`start_video`、`end_video` |
| `START_VIDEO` / `END_VIDEO` | 全局片头片尾；目录级配置优先，未配则回退到全局 |
| `SEGMENT_DURATION` | 分段时长，默认 360 秒（6 分钟） |
| `DURATION_TOLERANCE` | 关键帧分割允许的时长偏差，默认 ±3 秒 |
| `MAX_CONCURRENT_CONCAT` | 并行拼接任务数上限，默认 2 |
| `PROCESSOR_THREADS` | 分割处理线程数，默认 2 |
| `MAX_RETRY_COUNT` | 单任务最大重试次数 |
| `ENCODER_PRIORITY` | 编码器优先级列表，当前只启用 `h264_qsv` |
| `METADATA_FILE` / `LOG_FILE` | 元数据与日志文件名 |

> ⚠️ 监听目录目前写死在源码里，属于已知待改进项（见 `TODO.md`）。

## 架构

线程化生产者-消费者模型：

| 组件 | 职责 | 线程数 |
|------|------|--------|
| `WatcherThread` | 目录轮询，发现就绪文件 | 1（每目录） |
| `ProcessorPool` | 消费任务队列，做分割 | `PROCESSOR_THREADS` |
| `ParallelProcessor` | 片段拼接与进度追踪 | `MAX_CONCURRENT_CONCAT` |

关键类：

| 类 | 职责 |
|---|---|
| `EncoderManager` | 编码器探测、成功率统计、失败回退 |
| `ProgressTracker` | 基于首个成功片段的耗时估算 ETA，输出进度条 |
| `DirectoryStateManager` | 单目录状态机 `pending → processing → completed/failed` |
| `TaskQueue` | Queue + 锁封装，线程安全的生产/消费 |
| `ProcessingMetadata` | 元数据持久化，`RLock` 保护；记录 `retry_count` 防止无限重试 |

线程安全依赖三把独立的锁（元数据、目录状态、任务队列），`stop_event` 链式传播实现优雅关闭。

## 文件就绪判定

文件大小在 `FILE_STABLE_DURATION`（默认 10 秒）内不再变化，才认为写入完成。避免 OBS 仍在写盘时被误处理。

## 日志

双通道：控制台只输出关键信息，明细写入 `video_processing.log`（每次运行覆盖）。
三级分隔符区分粒度：`===== 视频名 =====`（新视频）、`----- 阶段 -----`（处理阶段）、`..... 片段 .....`（单片段）。

## 已知问题

见 `TODO.md`：

- **首选编码器广播失效** —— 日志显示已把 `h264_qsv` 设为首选，但后续拼接仍会走错误编码器并重新尝试 QSV，硬编实际未生效，速度退回软件编码
- 监听目录与片头片尾未外置为配置

## 历史

原文件名为 `auto_splice_mp4_4.py`，2026-11-06 更名为 `auto_splice_mp4.py`。
早期本文件中的"企业级可观测性""Docker / K8s 部署""CDN 分发""Prometheus 指标"等段落属于规划设想，代码中并未实现，已移除。
