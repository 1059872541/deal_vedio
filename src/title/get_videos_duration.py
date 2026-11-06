import os
import re
import subprocess
import sys
import argparse

default_directory = r"D:\VedioRecords\工作区\我的世界\合集\合集六\成片\波波之我的世界 通关极光堡垒"

def chinese_number_to_int(chinese_num):
    """将中文数字转换为整数"""
    chinese_digits = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, 
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '百': 100, '千': 1000, '万': 10000
    }
    
    # 处理简单的数字(一到九十九)
    if chinese_num in ['十']:
        return 10
    
    if len(chinese_num) == 1:
        return chinese_digits.get(chinese_num, 0)
    
    if len(chinese_num) == 2 and chinese_num[0] == '十':
        return 10 + chinese_digits.get(chinese_num[1], 0)
    
    if len(chinese_num) == 2 and chinese_num[1] == '十':
        return chinese_digits.get(chinese_num[0], 0) * 10
    
    # 对于更复杂的数字，使用简单映射
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
    # 匹配 "第X集" 格式，其中X是中文数字
    pattern = r'第([零一二三四五六七八九十百千万]+)集'
    match = re.search(pattern, filename)
    
    if match:
        chinese_num = match.group(1)
        return chinese_number_to_int(chinese_num)
    return None

def get_video_duration_ffprobe(file_path):
    """使用ffprobe获取视频时长(秒)"""
    try:
        # 构建ffprobe命令
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        
        # 运行命令并捕获输出
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        
        # 解析输出
        duration_str = result.stdout.strip()
        if duration_str:
            duration_float = float(duration_str)
            return int(duration_float)  # 返回整数秒
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

def main(directory=None):
    if directory is None:
        directory = default_directory
    
    try:
        files = os.listdir(directory)
    except FileNotFoundError:
        print(f"目录不存在: {directory}", file=sys.stderr)
        return
    except PermissionError:
        print(f"没有权限访问目录: {directory}", file=sys.stderr)
        return
    
    episode_files = []
    
    for file in files:
        if file.lower().endswith('.mp4'):
            episode_num = extract_episode_number(file)
            if episode_num is not None:
                display_name = remove_extension(file)
                series_title, video_title = split_title(display_name)
                episode_files.append({
                    'filename': file,
                    'series_title': series_title,
                    'video_title': video_title,
                    'episode_num': episode_num,
                    'full_path': os.path.join(directory, file)
                })
    
    episode_files.sort(key=lambda x: x['episode_num'])
    
    if not episode_files:
        print("未找到以'第X集'开头的MP4文件")
        return
    
    print("合集标题:")
    print(episode_files[0]['series_title'])
    
    print("\n视频标题:")
    for episode in episode_files:
        print(episode['video_title'])
    
    print("\n视频时长(秒):")
    for episode in episode_files:
        duration = get_video_duration_ffprobe(episode['full_path'])
        print(duration)

if __name__ == "__main__":
    directory = input("请输入视频目录路径: ").strip()
    if not directory:
        print("未输入路径，程序退出", file=sys.stderr)
        sys.exit(1)
    main(directory)