---
name: material-redistribute
des: 素材时长均衡——扫描合集目录、自动切割超限素材、溢出入下一合集，全流程自动执行并输出结构化结果
---

# 素材时长均衡（自动化流程）

## 什么时候用

某合集录制的原始素材总时长超过预期（如拍了 2h30m 但每合集只要 2h），需要把超出的部分自动切割并移入下一合集。

---

## 执行流程（3 步，无冗余交互）

### 第一步：提取参数

**game_name**：从用户路径中提取

| 输入路径 | 提取结果 |
|---|---|
| `D:\VedioRecords\工作区\我的世界-2026-06` | 我的世界-2026-06 |
| `D:\VedioRecords\工作区\我的世界-2026-06\合集` | 我的世界-2026-06 |
| `D:\VedioRecords\工作区\我的世界-2026-06\合集\合集三\素材` | 我的世界-2026-06 |

提取逻辑：路径中查找 `工作区` → 取下一级目录名。

**target**：三种方式（互斥），不指定则用默认值：

| 方式 | 示例 | 说明 |
|------|------|------|
| `--target` | `--target 90m` | 直接指定，支持 7200/2h/90m/1.5h |
| `--video-config` | `--video-config 370 20` | 自动计算 = 视频时长×个数 |
| （都不指定） | - | 默认 370s×20 = **7400s（~2.06h）** |

不询问，用户不指定就用默认值。

---

### 第二步：执行均衡

先清除过期日志（防止日志与真实文件状态不一致导致误判），然后直接运行正式命令：

```bash
# 清除过期日志（如有）
rm -f "D:/VedioRecords/工作区/{game_name}/log/.redistribute_log.json"

# 执行均衡（默认 370s×20=7400s）
cd d:/study/python/deal_vedio/src/util && python redistribute_material.py {game_name}

# 自定义视频时长和每合集数量（互斥参数，二选一）
cd d:/study/python/deal_vedio/src/util && python redistribute_material.py {game_name} --video-config 370 20
python redistribute_material.py {game_name} --target 90m
```

> **为什么先清日志？** 脚本的断点续跑依赖日志中的文件快照做双重验证。但如果日志是旧的（文件已被手动移动/删除/重命名），验证会失败或产生误导性跳过。清除日志让脚本从头扫描所有合集，最可靠。

**边界情况处理：**

| 场景 | 处理方式 |
|---|---|
| 用户要求重跑/重新均衡 | 清除日志，执行正式命令 |
| 只处理特定合集（如从合集四开始） | 加 `--start N` 参数，同时清除日志 |
| 只想预览不执行 | 加 `--dry-run` 参数，且**必须**同时加 `--force` 才能绕过旧日志 |
| 用户明确说"强制重扫" | 清除日志，执行正式命令 |

---

### 第三步：结构化输出

命令执行后，AI 必须按以下模板输出结果：

```
## 处理结果

### 执行操作
{逐条列出切割/移动操作}

### 合集状态变化
| 合集 | 处理前 | 处理后 | 状态 |
|------|--------|--------|------|
| ... | ...h | ...h | ✅ 跳过 / ✂ 切割 / ➡ 接收溢出 |

### 关键文件
- {合集}/素材/{文件} → {时长}（{说明}）
- ...

### 验证
{运行验证命令后的结果}
```

**验证模板命令：**

```bash
cd d:/study/python/deal_vedio/src && python -c "
import sys; sys.path.insert(0, '.')
from util.ffmpeg_utils import get_video_duration, VIDEO_EXTENSIONS
from pathlib import Path

base = Path('D:/VedioRecords/工作区/{game_name}/合集')
for col_name in ['合集四', '合集五']:
    mat = base / col_name / '素材'
    files = sorted(f for f in mat.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS)
    total = 0.0
    for f in files:
        dur = get_video_duration(f)
        total += dur
        print(f'  {col_name}/素材/{f.name}: {dur/60:.1f}min ({dur:.0f}s)')
    print(f'  {col_name} 合计: {total/3600:.2f}h')
"
```

说明：
- 若所有合集均未超限，操作列为空，直接输出 "✅ 所有合集均在目标时长内，无需处理"
- 若有切割操作，必须执行验证检查实际结果

---

## 参考

### 脚本路径
```
d:\study\python\deal_vedio\src\util\redistribute_material.py
```

### 输出解读

| 脚本输出 | 含义 |
|---|---|
| `切割 {file} @ {sec}s` | 在指定秒数处关键帧切割 |
| `前段替换原文件` | 原文件被切割后的前段覆盖 |
| `后段 → {合集}/素材/{file}` | 溢出段移入下一合集 |
| `找不到切割点` | 合集已在目标时长内，无需切割 |
| `未超限` | 合集时长 ≤ 目标，无需操作 |

### 限制说明

- 切割基于 ffmpeg 关键帧（`-c copy`），无重编码，零画质损失
- 溢出文件固定命名为 `{下一合集号}-0.mkv`（0 为溢出位）
- 仅支持合集一 ~ 合集九十九
- 最后一个合集的溢出段不会被移除（无下一合集可接收）

### 错误排查

| 现象 | 原因 | 解决 |
|---|---|---|
| 合集明明有文件但显示 0.00h/跳过 | 过期日志干扰 | 清除日志后重跑 |
| `找不到切割点（内部异常）` | 合集总时长刚好等于 target（整数精度问题），或日志文件快照为空 | 清除日志重跑 |
| `文件已变更，需重新处理` | 日志快照与实际文件不一致 | 清除日志重跑 |
