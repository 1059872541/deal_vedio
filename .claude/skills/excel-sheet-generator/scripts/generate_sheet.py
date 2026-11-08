# -*- coding: utf-8 -*-
"""
Excel片单生成协调脚本
扫描视频目录并生成Excel片单

功能：
1. 调用 get_videos_duration.py 扫描视频目录
2. 调用 generate_excel_from_json.py 生成Excel
3. 自动生成AI提示词

使用方式：
    python generate_sheet.py <目录1,目录2,...> [选项]
    
示例：
    python generate_sheet.py "D:\视频1,D:\视频2"
    python generate_sheet.py "D:\视频1" --host "波波" --category "端游"
"""

import os
import sys
import json
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 中间产物（扫描 JSON / 提示词）放仓库根的 prompts/ —— 跟着代码走，不写死本机路径
PROMPT_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "..", "..", "prompts"))

# 导入子模块
sys.path.insert(0, SCRIPT_DIR)
from get_videos_duration import scan_directories, find_video_directory
from generate_excel_from_json import generate_excel_from_json

def ensure_dir(path):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)

def generate_prompt_from_json(json_file):
    """根据JSON文件生成AI提示词"""
    with open(json_file, 'r', encoding='utf-8') as f:
        collections_data = json.load(f)
    
    video_titles_text = ""
    for col in collections_data:
        video_titles_text += f"\n### {col['series_title']}\n"
        for video in col['videos']:
            video_titles_text += f"- {video['filename']}\n"
    
    current_month = datetime.now().month
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    prompt_file = os.path.join(PROMPT_DIR, f"{timestamp}_content_prompt.md")
    ensure_dir(PROMPT_DIR)
    
    prompt_content = f"""# 内容生成提示词

## 任务

根据提供的视频标题信息，为每个合集生成内容介绍和关键字。

## 当前月份

{current_month}月

---

{video_titles_text}

---

## 输出要求

为**每个合集**生成以下内容：

### 1. 内容介绍
- 字数：20-40字
- 内容：描述合集的主题、剧情或主要内容
- 格式：中文标点，句号结尾

### 2. 关键字
- 数量：4-6个
- 分隔符：使用顿号（、）
- 要求：无违禁词

---

## 示例（从片单模板提取）

### 合集示例1

**合集名称**：波波之我的世界 通关极光堡垒

**生成结果**：

```
内容介绍：波波勇闯极光堡垒，挑战冰雪女王与高塔，历经二十关完成冒险。
关键字：极光堡垒、冰雪女王、高塔冒险、钻石套装、暮色之地
```

### 合集示例2

**合集名称**：波波之我的世界 征服沼泽强敌-上篇

**生成结果**：

```
内容介绍：波波深入沼泽迷宫，挑战牛头人与米诺陶，搜集宝藏升级装备。
关键字：沼泽迷宫、牛头人、迷宫宝藏、装备升级、钻石战斧
```

---

## 输出格式

请按以下格式输出每个合集的结果：

```
=== 合集名称 ===

内容介绍：xxx

关键字：xxx

---
```

生成 {len(collections_data)} 个合集的内容。
"""
    
    with open(prompt_file, 'w', encoding='utf-8') as f:
        f.write(prompt_content)
    
    print(f"提示词文件已生成: {prompt_file}")
    return prompt_file

def resolve_output_path(output_path):
    """
    处理输出文件路径，如果文件存在则添加递增后缀
    
    参数:
        output_path: 原始输出路径
    
    返回:
        不冲突的输出路径
    """
    if not os.path.exists(output_path):
        return output_path
    
    dir_name = os.path.dirname(output_path)
    base_name = os.path.basename(output_path)
    name, ext = os.path.splitext(base_name)
    
    counter = 1
    while True:
        new_name = f"{name}_{counter}{ext}"
        new_path = os.path.join(dir_name, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python generate_sheet.py <目录1,目录2,...> [选项]")
        print("  python generate_sheet.py --base-dir <基准目录> --collections <合集列表> [选项]")
        print("")
        print("示例（直接路径模式）:")
        print('  python generate_sheet.py "D:\\视频1,D:\\视频2"')
        print('  python generate_sheet.py "D:\\视频1" --output "D:\\output.xlsx"')
        print("")
        print("示例（基准目录模式）:")
        print('  python generate_sheet.py --base-dir "D:\\VedioRecords\\工作区\\我的世界_202604\\合集" --collections "合集九,合集十"')
        print("")
        print("选项:")
        print("  --base-dir 基准目录路径")
        print("  --collections 目标合集列表（逗号分隔，如 合集九,合集十）")
        print("  --host 主播名称（默认: 波波）")
        print("  --category 类别（默认: 端游）")
        print("  --year 年份（默认: 2026）")
        print("  --intro 片头时长秒（默认: 600）")
        print("  --output 输出Excel路径")
        print("  --no-prompt 跳过提示词生成")
        return
    
    base_dir = None
    collections = None
    directories = None
    output_file = None
    host = "波波"
    category = "端游"
    year = 2026
    intro_duration = 600
    generate_prompt = True
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--base-dir" and i + 1 < len(args):
            base_dir = args[i + 1]
            i += 2
        elif arg == "--collections" and i + 1 < len(args):
            collections = args[i + 1]
            i += 2
        elif arg == "--output" and i + 1 < len(args):
            output_file = args[i + 1]
            i += 2
        elif arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif arg == "--category" and i + 1 < len(args):
            category = args[i + 1]
            i += 2
        elif arg == "--year" and i + 1 < len(args):
            year = int(args[i + 1])
            i += 2
        elif arg == "--intro" and i + 1 < len(args):
            intro_duration = int(args[i + 1])
            i += 2
        elif arg == "--no-prompt":
            generate_prompt = False
            i += 1
        else:
            directories = arg
            i += 1
    
    if base_dir and collections:
        print(f"基准目录: {base_dir}")
        print(f"目标合集: {collections}")
        
        collection_list = [c.strip() for c in collections.split(',')]
        resolved_dirs = []
        
        for col in collection_list:
            collection_path = os.path.join(base_dir, col)
            video_dir = find_video_directory(collection_path)
            if video_dir:
                resolved_dirs.append(video_dir)
                print(f"  {col} -> {video_dir}")
            else:
                print(f"  警告: {col} 未找到视频目录")
        
        if not resolved_dirs:
            print("错误: 未找到任何视频目录")
            return
        
        directories = ','.join(resolved_dirs)
    elif directories:
        pass
    else:
        print("错误: 请提供 --base-dir 和 --collections，或直接输入目录路径")
        return
    
    print(f"主播: {host}, 类别: {category}, 年份: {year}")
    
    # 步骤1: 扫描视频
    print("\n步骤1: 扫描视频目录...")
    collections_data = scan_directories(directories)
    
    if not collections_data:
        print("错误: 未找到任何视频")
        return
    
    # 保存JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_file = os.path.join(PROMPT_DIR, f"{timestamp}_videos.json")
    ensure_dir(PROMPT_DIR)
    
    # 转换为简化格式
    simplified_data = []
    for col in collections_data:
        simplified_data.append({
            'series_title': col['series_title'],
            'video_count': col['video_count'],
            'total_duration': col['total_duration'],
            'videos': [
                {'filename': v['filename'], 'episode_num': v['episode_num'], 'duration': v['duration']}
                for v in col['videos']
            ]
        })
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(simplified_data, f, ensure_ascii=False, indent=2)
    
    print(f"JSON已保存: {json_file}")
    
    # 步骤2: 生成Excel
    print("\n步骤2: 生成Excel...")
    
    final_output_path = output_file
    if output_file is None:
        # 没给 --output：写到扫描 JSON 同目录，文件名按交付习惯拼。
        # 不写死本机目录 —— 换机器、换批次都不用改代码。
        current_month = datetime.now().month
        default_output = os.path.join(
            os.path.dirname(os.path.abspath(json_file)),
            f"{year % 100}年{host}{current_month}月第一批片单.xlsx",
        )
        final_output_path = resolve_output_path(default_output)
    else:
        final_output_path = resolve_output_path(output_file)
    
    generate_excel_from_json(json_file, final_output_path, host, category, year, intro_duration)
    
    # 步骤3: 生成提示词
    if generate_prompt:
        print("\n步骤3: 生成AI提示词...")
        generate_prompt_from_json(json_file)
    
    print("\n" + "="*50)
    print("完成！")
    print("="*50)

if __name__ == "__main__":
    main()