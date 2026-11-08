# -*- coding: utf-8 -*-
"""
视频时长获取脚本
支持一次性扫描多个目录，获取视频标题和时长
"""

import os
import re
import subprocess
import sys
import json
from datetime import datetime

def chinese_number_to_int(chinese_num):
    """将中文数字转换为整数"""
    chinese_digits = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, 
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '百': 100, '千': 1000, '万': 10000
    }
    
    if chinese_num in ['十']:
        return 10
    
    if len(chinese_num) == 1:
        return chinese_digits.get(chinese_num, 0)
    
    if len(chinese_num) == 2 and chinese_num[0] == '十':
        return 10 + chinese_digits.get(chinese_num[1], 0)
    
    if len(chinese_num) == 2 and chinese_num[1] == '十':
        return chinese_digits.get(chinese_num[0], 0) * 10
    
    simple_map = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
        '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20,
        '二十一': 21, '二十二': 22, '二十三': 23, '二十四': 24, '二十五': 25,
        '二十六': 26, '二十七': 27, '二十八': 28, '二十九': 29, '三十': 30
    }
    
    return simple_map.get(chinese_num, 0)

def extract_episode_number(filename):
    """从文件名中提取集数"""
    pattern = r'第([零一二三四五六七八九十百千万]+)集'
    match = re.search(pattern, filename)
    
    if match:
        chinese_num = match.group(1)
        return chinese_number_to_int(chinese_num)
    return None

def get_video_duration_ffprobe(file_path):
    """使用ffprobe获取视频时长(秒)"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        
        duration_str = result.stdout.strip()
        if duration_str:
            duration_float = float(duration_str)
            return int(duration_float)
        else:
            print(f"无法解析视频时长: {file_path}", file=sys.stderr)
            return 0
    except subprocess.CalledProcessError as e:
        print(f"ffprobe执行出错 {file_path}: {e}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"获取视频时长时出错 {file_path}: {e}", file=sys.stderr)
        return 0

def remove_extension(filename):
    """去除文件扩展名"""
    return os.path.splitext(filename)[0]

def split_title(display_name):
    """按'第'字分割标题，返回(合集标题, 视频标题)"""
    if '第' in display_name:
        parts = display_name.split('第', 1)
        return parts[0], '第' + parts[1]
    return display_name, display_name

def find_video_directory(collection_dir, max_depth=3):
    """
    在合集目录下递归查找视频目录
    找到包含 "第X集*.mp4" 文件的子目录并返回
    
    参数:
        collection_dir: 合集目录路径
        max_depth: 最大递归深度，默认3层
    
    返回:
        找到的视频目录路径，未找到返回None
    """
    if not os.path.exists(collection_dir):
        print(f"  目录不存在: {collection_dir}")
        return None
    
    skip_dirs = {'图片', '素材', '素材包', '缓存', '.thumbnails', 'thumbnails', '表情包', '封面', '其他'}
    
    for root, dirs, files in os.walk(collection_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        depth = root.replace(collection_dir, '').count(os.sep)
        
        video_files = [f for f in files if f.lower().endswith('.mp4') and re.search(r'第[零一二三四五六七八九十百千万]+集', f)]
        if video_files:
            print(f"  找到视频目录: {root}")
            return root
        
        if depth >= max_depth:
            dirs[:] = []
    
    return None

def check_missing_episodes(videos):
    """
    检查视频集数是否连续，报告缺失的集数
    
    参数:
        videos: 视频列表
    
    返回:
        缺失的集数列表
    """
    if not videos:
        return []
    
    episode_nums = sorted([v['episode_num'] for v in videos])
    expected = range(episode_nums[0], episode_nums[-1] + 1)
    missing = [e for e in expected if e not in episode_nums]
    return missing

def scan_directory(directory):
    """扫描单个目录，返回视频列表"""
    if not os.path.exists(directory):
        print(f"目录不存在: {directory}", file=sys.stderr)
        return []
    
    try:
        files = os.listdir(directory)
    except PermissionError:
        print(f"没有权限访问目录: {directory}", file=sys.stderr)
        return []
    
    episode_files = []
    
    for file in files:
        if file.lower().endswith('.mp4'):
            episode_num = extract_episode_number(file)
            if episode_num is not None:
                display_name = remove_extension(file)
                series_title, video_title = split_title(display_name)
                full_path = os.path.join(directory, file)
                duration = get_video_duration_ffprobe(full_path)
                
                episode_files.append({
                    'filename': file,
                    'series_title': series_title,
                    'video_title': video_title,
                    'episode_num': episode_num,
                    'duration': duration,
                    'full_path': full_path
                })
    
    episode_files.sort(key=lambda x: x['episode_num'])
    return episode_files

def scan_directories(directories, output_json=None):
    """
    扫描多个目录
    
    参数:
        directories: 目录列表 或 逗号分隔的字符串
        output_json: 可选，输出JSON文件路径
    
    返回:
        包含所有目录扫描结果的列表
    """
    if isinstance(directories, str):
        directories = [d.strip() for d in directories.split(',')]
    
    all_results = []
    
    for directory in directories:
        directory = directory.strip()
        if not directory:
            continue
            
        print(f"\n扫描目录: {directory}")
        
        videos = scan_directory(directory)
        
        if videos:
            result = {
                'series_title': videos[0]['series_title'].strip(),
                'video_count': len(videos),
                'total_duration': sum(v['duration'] for v in videos),
                'videos': [
                    {
                        'filename': video['video_title'],
                        'episode_num': video['episode_num'],
                        'duration': video['duration']
                    }
                    for video in videos
                ]
            }
            
            missing = check_missing_episodes(videos)
            if missing:
                print(f"  警告: 缺少第 {', '.join(map(str, missing))} 集")
                result['missing_episodes'] = missing
            
            all_results.append(result)
            print(f"  找到 {len(videos)} 个视频，总时长 {result['total_duration']} 秒")
        else:
            print(f"  未找到以'第X集'开头的MP4文件")
    
    if output_json:
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_json}")
    
    return all_results

def print_results(results):
    """打印扫描结果"""
    for result in results:
        print(f"\n{'='*50}")
        print(f"合集标题: {result['series_title']}")
        print(f"视频数量: {result['video_count']}")
        print(f"总时长: {result['total_duration']} 秒")
        print(f"\n视频列表:")
        print(f"{'集数':<6} {'标题':<30} {'时长(秒)':<10}")
        print("-" * 50)
        for video in result['videos']:
            print(f"{video['episode_num']:<6} {video['filename']:<30} {video['duration']:<10}")

def main():
    """主函数"""
    if len(sys.argv) > 1:
        directories = sys.argv[1]
        output_json = sys.argv[2] if len(sys.argv) > 2 else None
        results = scan_directories(directories, output_json)
        if results:
            print_results(results)
    else:
        print("用法:")
        print("  python get_videos_duration.py <目录1,目录2,...> [输出JSON文件]")
        print("")
        print("示例:")
        print('  python get_videos_duration.py "D:\\视频1,D:\\视频2"')
        print('  python get_videos_duration.py "D:\\视频1" "D:\\output.json"')
        print("")
        print("或运行交互模式:")
        directory = input("请输入视频目录路径（多个目录用逗号分隔）: ").strip()
        if directory:
            results = scan_directories(directory)
            if results:
                print_results(results)

if __name__ == "__main__":
    main()