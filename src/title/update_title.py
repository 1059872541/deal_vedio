import os
import re
import logging
from pathlib import Path

# ==================== 配置区域 ====================
# 请在这里修改目标目录路径
TARGET_DIRECTORY = r"D:\VedioRecords\剪辑草稿\初剪辑\星露谷物语\合集五\波波之星露谷物语 夏季经营"

# 批量处理的基目录（如果需要批量处理多个目录，请设置此项）
# BASE_DIRECTORY = r"D:\VedioRecords\剪辑草稿"

# 视频文件扩展名
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
# =================================================

# ===== 中文数字映射（1~30）=====
ARABIC_TO_CHINESE = {
    1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
    6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
    11: "十一", 12: "十二", 13: "十三", 14: "十四", 15: "十五",
    16: "十六", 17: "十七", 18: "十八", 19: "十九", 20: "二十",
    21: "二十一", 22: "二十二", 23: "二十三", 24: "二十四", 25: "二十五",
    26: "二十六", 27: "二十七", 28: "二十八", 29: "二十九", 30: "三十"
}

def setup_logging():
    """设置日志记录"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def get_video_files(directory):
    """获取目录中的所有视频文件"""
    video_files = []
    
    try:
        for file in os.listdir(directory):
            file_path = Path(directory) / file
            if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(file_path)
        logging.info(f"找到 {len(video_files)} 个视频文件")
        return video_files
    except Exception as e:
        logging.error(f"读取目录失败: {e}")
        return []

def natural_sort_key(filename):
    """自然排序键函数，用于处理数字排序"""
    def convert(text):
        return int(text) if text.isdigit() else text.lower()
    
    return [convert(c) for c in re.split('([0-9]+)', str(filename))]

def number_to_chinese(num):
    """将 1~30 的阿拉伯数字转为中文数字，超出范围返回原数字字符串"""
    if 1 <= num <= 30:
        return ARABIC_TO_CHINESE[num]
    else:
        # 超出范围：可选择返回原数字或报错
        logging.warning(f"序号 {num} 超出中文映射范围（1~30），将使用阿拉伯数字")
        return str(num)

def extract_prefix_from_path(directory_path):
    """从目录路径中提取前缀名称 - 修复版本"""
    path_obj = Path(directory_path)
    
    # 获取目录的名称（最后一级文件夹名）
    directory_name = path_obj.name
    
    # 如果目录名不为空且不是常见的分类文件夹，则使用目录名
    common_folders = {'剪辑草稿', '初剪辑', '合集', 'target', '视频', '素材', '成品', 
                     '集', '第', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十'}
    
    # 检查目录名是否包含有意义的内容
    if directory_name and directory_name not in common_folders and not directory_name.startswith('1.'):
        # 清理前缀中的特殊字符和数字前缀（如 "1.初剪辑" 中的 "1."）
        cleaned_prefix = re.sub(r'^\d+\.\s*', '', directory_name)
        return cleaned_prefix
    
    # 如果目录名是常见分类文件夹，则向上一级查找
    parent_path = path_obj.parent
    if parent_path.name and parent_path.name not in common_folders:
        parent_prefix = re.sub(r'^\d+\.\s*', '', parent_path.name)
        return parent_prefix
    
    # 如果还是没有找到有意义的名称，返回"视频"
    return "视频"

def rename_video_files(directory):
    """重命名视频文件为 '前缀 第X集' 格式（X 为中文数字）"""
    # 获取视频文件
    video_files = get_video_files(directory)
    
    if not video_files:
        logging.warning("未找到视频文件")
        return False
    
    # 按自然顺序排序
    video_files.sort(key=natural_sort_key)
    
    # 提取目录前缀
    prefix = extract_prefix_from_path(directory)
    logging.info(f"提取的目录前缀: {prefix}")
    
    logging.info("文件排序结果:")
    for i, file_path in enumerate(video_files, 1):
        logging.info(f"{i:2d}. {file_path.name}")
    
    # 显示预览重命名结果
    print(f"\n预览重命名结果:")
    for i, file_path in enumerate(video_files, 1):
        chinese_num = number_to_chinese(i)
        new_name = f"{prefix} 第{chinese_num}集{file_path.suffix}"
        print(f"  {file_path.name} -> {new_name}")
    
    # 确认操作
    confirm = input(f"\n确定要将这 {len(video_files)} 个文件重命名为 '{prefix} 第X集' 格式吗? (y/N): ")
    if confirm.lower() != 'y':
        logging.info("操作已取消")
        return False
    
    # 执行重命名
    success_count = 0
    for i, file_path in enumerate(video_files, 1):
        try:
            chinese_num = number_to_chinese(i)
            new_name = f"{prefix} 第{chinese_num}集{file_path.suffix}"
            new_path = file_path.parent / new_name
            
            # 检查新文件名是否与原文件名相同
            if file_path.name == new_name:
                logging.info(f"文件名已正确，跳过: {file_path.name}")
                success_count += 1
                continue
            
            # 处理目标文件已存在的情况（先临时重命名）
            if new_path.exists():
                temp_name = f"temp_rename_{i}{file_path.suffix}"
                temp_path = file_path.parent / temp_name
                file_path.rename(temp_path)
                file_path = temp_path
            
            file_path.rename(new_path)
            logging.info(f"重命名成功: {file_path.name} -> {new_name}")
            success_count += 1
            
        except Exception as e:
            logging.error(f"重命名失败 {file_path.name}: {e}")
    
    logging.info(f"重命名完成! 成功: {success_count}/{len(video_files)}")
    return success_count == len(video_files)

def batch_rename_directories(base_directory):
    """批量处理基目录下的所有子目录"""
    setup_logging()
    
    base_path = Path(base_directory)
    if not base_path.exists():
        logging.error(f"基目录不存在: {base_directory}")
        return
    
    # 查找所有包含视频文件的目录
    video_dirs = []
    for root, dirs, files in os.walk(base_directory):
        if any(Path(f).suffix.lower() in VIDEO_EXTENSIONS for f in files):
            video_dirs.append(Path(root))
    
    print(f"找到 {len(video_dirs)} 个包含视频的目录")
    
    for i, directory in enumerate(video_dirs, 1):
        print(f"\n[{i}/{len(video_dirs)}] 处理目录: {directory}")
        rename_video_files(directory)

def main():
    """主函数 - 单目录处理"""
    setup_logging()
    
    target_directory = TARGET_DIRECTORY
    
    if not os.path.exists(target_directory):
        logging.error(f"目录不存在: {target_directory}")
        return
    
    if not os.path.isdir(target_directory):
        logging.error(f"路径不是目录: {target_directory}")
        return
    
    print("视频文件重命名工具（带目录前缀）")
    print("=" * 50)
    print(f"目标目录: {target_directory}")
    print(f"目录名称: {Path(target_directory).name}")
    print("格式: 前缀 第X集.mp4")
    print("支持范围: 第1集 ~ 第30集（超出将保留数字）")
    print("=" * 50)
    
    rename_video_files(target_directory)

if __name__ == "__main__":
    # 模式1：处理单个目录（默认）
    main()
    
    # 模式2：批量处理多个目录（取消注释下面的行）
    # batch_rename_directories(BASE_DIRECTORY)