# 剪映自动化导出模块

从 [pyJianYingDraft](https://github.com/yourusername/pyJianYingDraft) 项目迁移而来，提供剪映草稿的自动化导出功能。

## 功能特性

- ✅ **批量导出**：支持配置多个导出任务，自动顺序执行
- ✅ **参数配置**：可设置分辨率、帧率、超时时间等导出参数
- ✅ **错误处理**：完善的异常处理，避免程序崩溃
- ✅ **配置灵活**：支持硬编码配置和JSON配置文件
- ✅ **平台检查**：自动检测Windows平台，非Windows给出清晰错误提示
- ✅ **剪映版本**：支持剪映6及以下版本

## 系统要求

- **操作系统**：Windows 10/11（仅支持Windows平台）
- **Python版本**：Python 3.8+
- **依赖库**：`uiautomation`
- **剪映版本**：剪映专业版 6.x 及以下版本

## 安装依赖

```bash
pip install uiautomation
```

## 使用方式

### 方式一：直接运行脚本（使用默认配置）

```bash
# 从项目根目录运行
python -m src.jianying_export.export_draft
```

### 方式二：使用配置文件

1. 复制配置文件示例：
   ```bash
   cp src/jianying_export/config.example.json src/jianying_export/config.json
   ```

2. 编辑 `config.json` 配置导出任务

3. 运行脚本：
   ```bash
   python -m src.jianying_export.export_draft
   ```

### 方式三：指定配置文件路径

```bash
python -m src.jianying_export.export_draft --config path/to/your/config.json
```

### 查看支持的分辨率和帧率

```bash
python -m src.jianying_export.export_draft --list-resolutions
python -m src.jianying_export.export_draft --list-framerates
```

## 配置文件说明

配置文件示例：`config.example.json`

```json
{
  "export_jobs": [
    {
      "draft_name": "MC-合集-7",
      "output_path": "D:\\VedioRecords\\工作区\\我的世界\\合集\\合集七\\成片",
      "resolution": "1080P",
      "framerate": "30fps",
      "timeout": 10800
    }
  ],
  "pause_between": 10.0
}
```

### 字段说明

| 字段 | 类型 | 说明 | 必填 |
|------|------|------|------|
| `draft_name` | 字符串 | 剪映草稿名称（在剪映中显示的名称） | ✅ |
| `output_path` | 字符串 | 输出路径，可以是文件或目录 | ✅ |
| `resolution` | 字符串 | 分辨率，可选：`8K`, `4K`, `2K`, `1080P`, `720P`, `480P` | ❌ |
| `framerate` | 字符串 | 帧率，可选：`24fps`, `25fps`, `30fps`, `50fps`, `60fps` | ❌ |
| `timeout` | 整数 | 导出超时时间（秒），默认1200秒（20分钟） | ❌ |
| `pause_between` | 浮点数 | 任务间隔时间（秒），默认10.0秒 | ❌ |

## 模块结构

```
src/jianying_export/
├── __init__.py              # 模块初始化，平台检查
├── _version.py              # 版本信息
├── controller.py            # 剪映控制器核心
├── exceptions.py            # 异常定义
├── export_draft.py          # 批量导出脚本（主入口）
├── config.example.json      # 配置文件示例
├── README.md                # 本文件
└── test_import.py           # 导入测试脚本
```

## API参考

### JianyingController 类

核心控制器类，提供剪映自动化控制功能。

```python
from src.jianying_export import JianyingController, ExportResolution, ExportFramerate

# 初始化控制器（剪映需要在主页）
controller = JianyingController()

# 导出单个草稿
controller.export_draft(
    draft_name="我的草稿",
    output_path="D:\\output\\video.mp4",
    resolution=ExportResolution.RES_1080P,
    framerate=ExportFramerate.FR_30,
    timeout=1800
)
```

### 异常类

- `DraftNotFound`：未找到指定名称的草稿
- `AutomationError`：自动化操作失败
- `ExportTimeout`：导出超时
- 其他异常请参考 `exceptions.py`

## 使用前准备

1. **打开剪映**：确保剪映专业版已打开
2. **切换到主页**：剪映需要处于草稿目录页面
3. **草稿目录设置**：确保剪映的草稿目录已正确设置（通常是 `D:\VedioRecords\剪辑草稿\剪映草稿\JianyingPro Drafts`）
4. **权限检查**：确认有导出草稿的权限（不使用VIP功能或已开通VIP）

## 注意事项

1. **仅支持Windows**：由于依赖 `uiautomation` 库，仅支持Windows平台
2. **剪映版本限制**：仅测试支持剪映6及以下版本，新版剪映可能不兼容
3. **窗口前置**：剪映窗口需要保持在前台，不要最小化
4. **导出权限**：需要确认有导出草稿的权限，否则可能陷入死循环
5. **等待时间**：脚本中包含等待时间（60秒等），确保剪映界面完全加载

## 故障排除

### 常见问题

1. **剪映窗口未找到**
   - 确保剪映已打开且未最小化
   - 检查剪映窗口标题是否为"剪映专业版"

2. **草稿未找到**
   - 检查草稿名称是否正确
   - 确保剪映处于草稿目录页面
   - 确认草稿目录设置正确

3. **导出按钮未找到**
   - 确保已进入草稿编辑页面
   - 检查剪映版本是否兼容

4. **导出超时**
   - 增加 `timeout` 参数值
   - 检查剪映导出是否卡住
   - 确认有足够的磁盘空间

### 调试模式

如需调试，可修改 `controller.py` 中的等待时间或添加更多日志。

## 测试

运行导入测试（不实际调用剪映）：
```bash
python -m src.jianying_export.test_import
```

## 迁移说明

本模块从 `pyJianYingDraft` 项目迁移而来，主要改动：

1. **平台检查**：添加了Windows平台检查，非Windows平台给出清晰错误
2. **配置管理**：增加了JSON配置文件支持
3. **项目集成**：适配到当前项目的模块结构
4. **错误修复**：修复了循环中的CPU使用率问题

## 许可证

基于原 `pyJianYingDraft` 项目的许可证。