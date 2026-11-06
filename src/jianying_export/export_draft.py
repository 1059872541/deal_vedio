"""
剪映批量导出脚本（放在项目根目录运行）

从pyJianYingDraft项目迁移而来，适配到当前项目架构。

支持两种配置方式：
1. 直接修改脚本中的 EXPORT_JOBS 配置
2. 使用配置文件 config.json（将 config.example.json 复制为 config.json 并修改）

要求：
 - 激活 venv 并安装依赖（uiautomation）
 - 打开剪映并切到草稿目录页（草稿目录已设置为 D:\\VedioRecords\\剪辑草稿\\剪映草稿\\JianyingPro Drafts）
 - 仅支持Windows平台

使用方式：
python -m src.jianying_export.export_draft
或
python -m src.jianying_export.export_draft --config path/to/config.json
或
cd 到项目根目录后运行: python src/jianying_export/export_draft.py
"""

import os
import time
import json
import argparse
from pathlib import Path
import sys

# 平台检查
IS_WINDOWS = sys.platform == "win32"
if not IS_WINDOWS:
    print("错误：剪映自动化导出仅支持Windows平台")
    sys.exit(1)

# 解决导入问题 - 让脚本既可以直接运行，也可以作为模块运行
# 添加项目根目录到sys.path，这样可以直接导入src.jianying_export
import sys
current_file = Path(__file__)
# 获取项目根目录：当前文件 -> jianying_export -> src -> 项目根目录
project_root = current_file.parent.parent.parent  # src/jianying_export/export_draft.py -> src -> 项目根目录
sys.path.insert(0, str(project_root))

# 现在可以像原项目一样导入
try:
    from src.jianying_export.controller import JianyingController
    from src.jianying_export import ExportResolution, ExportFramerate
    from src.jianying_export.exceptions import DraftNotFound, AutomationError, ExportTimeout
except ImportError as e:
    print(f"[错误] 导入剪映导出模块失败: {e}")
    print("可能的解决方案：")
    print("  1. 确保在项目目录结构中运行")
    print("  2. 检查 src/jianying_export/ 目录是否存在")
    sys.exit(1)

# 默认配置（硬编码）
EXPORT_JOBS = [
    {
        "draft_name": "2026-06-mc-合集八",  # 草稿名称（剪映中显示的名称）
        "output_path": r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集八\剪辑",
        "resolution": ExportResolution.RES_1080P,
        "framerate": ExportFramerate.FR_25,
        "timeout": 10800,  # 导出超时（秒）  3h
    },
    {
        "draft_name": "2026-06-mc-合集九",  # 草稿名称（剪映中显示的名称）
        "output_path": r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集九\剪辑",
        "resolution": ExportResolution.RES_1080P,
        "framerate": ExportFramerate.FR_25,
        "timeout": 10800,  # 导出超时（秒）  3h
    }
]

# 导出间隔（秒），建议留出足够时间让剪映刷新/稳定
PAUSE_BETWEEN = 10.0

def parse_resolution(res_str: str):
    """将字符串解析为ExportResolution枚举"""
    resolution_map = {
        "8K": ExportResolution.RES_8K,
        "4K": ExportResolution.RES_4K,
        "2K": ExportResolution.RES_2K,
        "1080P": ExportResolution.RES_1080P,
        "720P": ExportResolution.RES_720P,
        "480P": ExportResolution.RES_480P,
    }
    if res_str.upper() not in resolution_map:
        raise ValueError(f"不支持的分辨率: {res_str}，支持的选项: {list(resolution_map.keys())}")
    return resolution_map[res_str.upper()]

def parse_framerate(fr_str: str):
    """将字符串解析为ExportFramerate枚举"""
    framerate_map = {
        "24fps": ExportFramerate.FR_24,
        "25fps": ExportFramerate.FR_25,
        "30fps": ExportFramerate.FR_30,
        "50fps": ExportFramerate.FR_50,
        "60fps": ExportFramerate.FR_60,
    }
    if fr_str not in framerate_map:
        raise ValueError(f"不支持的帧率: {fr_str}，支持的选项: {list(framerate_map.keys())}")
    return framerate_map[fr_str]

def load_config(config_path: str = None):
    """加载配置文件，返回(jobs, pause_between)"""
    if config_path is None:
        # 尝试加载当前目录下的config.json
        script_dir = Path(__file__).parent
        config_path = script_dir / "config.json"

    if config_path and Path(config_path).exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            jobs = []
            for job in config.get("export_jobs", []):
                # 转换字符串值为枚举类型
                resolved_job = job.copy()
                if "resolution" in job and isinstance(job["resolution"], str):
                    resolved_job["resolution"] = parse_resolution(job["resolution"])
                if "framerate" in job and isinstance(job["framerate"], str):
                    resolved_job["framerate"] = parse_framerate(job["framerate"])
                jobs.append(resolved_job)

            pause_between = config.get("pause_between", PAUSE_BETWEEN)
            print(f"[配置] 从文件加载配置: {config_path}")
            return jobs, pause_between
        except Exception as e:
            print(f"[警告] 加载配置文件失败: {e}，使用默认配置")

    # 使用默认配置
    print("[配置] 使用默认配置")
    return EXPORT_JOBS, PAUSE_BETWEEN

def ensure_parent(path: str) -> None:
    """确保输出路径的父目录存在"""
    p = Path(path)
    if p.suffix:  # 看起来像文件（有后缀）
        p.parent.mkdir(parents=True, exist_ok=True)
    else:
        p.mkdir(parents=True, exist_ok=True)

def run_jobs(jobs, pause_between=PAUSE_BETWEEN):
    """执行批量导出任务"""
    if not jobs:
        print("[警告] 没有导出任务")
        return

    try:
        ctrl = JianyingController()
    except Exception as e:
        print(f"[错误] 初始化剪映控制器失败: {e}")
        return

    total = len(jobs)
    for i, job in enumerate(jobs, 1):
        name = job.get("draft_name")
        out = job.get("output_path")
        res = job.get("resolution")
        fr = job.get("framerate")
        to = job.get("timeout", 1200)

        if out:
            ensure_parent(out)

        print(f"[{i}/{total}] 导出草稿: {name} -> {out} (res={getattr(res,'value',None)} fr={getattr(fr,'value',None)})")
        try:
            ctrl.export_draft(name, out, resolution=res, framerate=fr, timeout=to)
            print(f"[完成] {name}")
        except DraftNotFound:
            print(f"[错误] 未找到草稿: {name}")
        except AutomationError as e:
            print(f"[自动化错误] 导出失败 {name}: {e}")
        except ExportTimeout:
            print(f"[超时] 导出超时 {name}")
        except Exception as e:
            print(f"[异常] 导出失败 {name}: {e}")

        if i < total:  # 不是最后一个任务
            print(f"[等待] 暂停 {pause_between} 秒...")
            time.sleep(pause_between)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="剪映批量导出脚本")
    parser.add_argument("--config", type=str, help="配置文件路径（默认为模块目录下的config.json）")
    parser.add_argument("--list-resolutions", action="store_true", help="列出支持的分辨率")
    parser.add_argument("--list-framerates", action="store_true", help="列出支持的帧率")
    args = parser.parse_args()

    if args.list_resolutions:
        print("支持的分辨率:")
        for res in ExportResolution:
            print(f"  - {res.value}")
        return

    if args.list_framerates:
        print("支持的帧率:")
        for fr in ExportFramerate:
            print(f"  - {fr.value}")
        return

    print("=== 剪映批量导出脚本 ===")
    print(f"平台: {'Windows' if IS_WINDOWS else '非Windows'}")

    # 加载配置
    jobs, pause_between = load_config(args.config)
    print(f"任务数: {len(jobs)}")
    print(f"任务间隔: {pause_between}秒")
    print("=" * 30)

    if jobs:
        run_jobs(jobs, pause_between)
    else:
        print("[提示] 没有导出任务，请检查配置")

    print("=" * 30)
    print("批量导出完成")

if __name__ == "__main__":
    main()