#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频批量重命名工具
支持中文字符，跨平台兼容

功能特性：
1. 自然排序（c1, c2, c10, c11）
2. UTF-8编码支持
3. 重复文本检测与移除
4. 预览模式与实际执行
5. 备份与恢复机制

使用示例：
python rename_videos.py --pattern "MC-合集-*_c*.mp4" \
  --prefix "波波之我的世界 培养制图师-上篇" \
  --titles "空村之谜,资源大收集,僵尸夜袭,钻石护体,农田丰收,村民失踪,海上漂流,漩涡惊魂,新大陆发现,铁傀儡护卫,陆地行舟,运河工程,夜宿村庄,村民运输,归家之路,圈养人类,制图师诞生,甘蔗王国,交易大师,村庄复兴" \
  --start 1 --execute
"""

import os
import sys
import re
import shutil
import argparse
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import json
from datetime import datetime

class VideoRenamer:
    """视频重命名器核心类"""
    
    def __init__(self, encoding='utf-8'):
        self.encoding = encoding
        self.chinese_numbers = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
        self.backup_dir = None
        self.operations_log = []
        
    def natural_sort_key(self, filename: str) -> List:
        """生成自然排序键（c1, c2, c10）"""
        # 提取数字部分
        def convert(text):
            return int(text) if text.isdigit() else text.lower()
        
        # 分割数字和非数字部分
        return [convert(c) for c in re.split(r'(\d+)', filename)]
    
    def sort_files_naturally(self, files: List[str]) -> List[str]:
        """自然排序文件列表"""
        return sorted(files, key=self.natural_sort_key)
    
    def remove_duplicate_text(self, prefix: str, title: str) -> str:
        """移除标题中与前缀重复的部分"""
        if not prefix or not title:
            return title
        
        # 将前缀拆分为词语
        prefix_words = set(prefix.split())
        
        # 检查标题是否包含前缀中的词语
        title_words = title.split()
        filtered_words = []
        
        for word in title_words:
            if word not in prefix_words:
                filtered_words.append(word)
        
        result = ' '.join(filtered_words).strip()
        
        # 如果结果为空，返回原始标题（避免删除所有内容）
        return result if result else title
    
    def number_to_chinese(self, number: int) -> str:
        """将数字转换为中文数字（1-20）"""
        if 1 <= number <= 10:
            return self.chinese_numbers[number-1]
        elif 11 <= number <= 20:
            if number == 10:
                return "十"
            elif number < 20:
                return f"十{self.chinese_numbers[number-11]}"
            else:
                return "二十"
        else:
            # 超过20的数字，使用阿拉伯数字
            return str(number)
    
    def generate_new_name(self, prefix: str, episode: int, title: str) -> str:
        """生成新文件名"""
        # 中文集数转换
        chinese_ep = f"第{self.number_to_chinese(episode)}集"
        
        # 清理标题（移除与前缀重复的部分）
        clean_title = self.remove_duplicate_text(prefix, title)
        
        # 构建新文件名
        new_name = f"{prefix} {chinese_ep} {clean_title}.mp4"
        
        # 移除多余空格
        new_name = re.sub(r'\s+', ' ', new_name).strip()
        
        return new_name
    
    def create_backup(self, files: List[str], backup_name: Optional[str] = None) -> bool:
        """创建文件备份"""
        if not backup_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"video_backup_{timestamp}"
        
        self.backup_dir = Path.cwd() / backup_name
        self.backup_dir.mkdir(exist_ok=True)
        
        print(f"[备份] 创建备份到: {self.backup_dir}")
        
        for file_path in files:
            src = Path(file_path)
            if src.exists():
                dst = self.backup_dir / src.name
                try:
                    shutil.copy2(src, dst)
                    print(f"  [成功] 备份: {src.name}")
                except Exception as e:
                    print(f"  [失败] 备份失败 {src.name}: {e}")
                    return False
        
        # 保存操作日志
        log_file = self.backup_dir / "rename_operations.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(self.operations_log, f, ensure_ascii=False, indent=2)
        
        return True
    
    def restore_from_backup(self) -> bool:
        """从备份恢复文件"""
        if not self.backup_dir or not self.backup_dir.exists():
            print("[错误] 备份目录不存在")
            return False
        
        print(f"[恢复] 从备份恢复: {self.backup_dir}")
        
        for file_path in self.backup_dir.glob("*.mp4"):
            src = file_path
            dst = Path.cwd() / src.name
            
            try:
                if dst.exists():
                    dst.unlink()  # 删除现有文件
                shutil.copy2(src, dst)
                print(f"  [成功] 恢复: {src.name}")
            except Exception as e:
                print(f"  [失败] 恢复失败 {src.name}: {e}")
                return False
        
        return True
    
    def rename_files(self, pattern: str, prefix: str, titles: List[str], 
                     start_ep: int = 1, dry_run: bool = True, 
                     create_backup: bool = False) -> bool:
        """主重命名函数"""
        print("=" * 60)
        print("视频批量重命名工具")
        print("=" * 60)
        
        # 查找文件
        files = sorted(Path('.').glob(pattern))
        if not files:
            print(f"[错误] 未找到匹配模式 '{pattern}' 的文件")
            return False
        
        # 转换为字符串路径并排序
        file_paths = [str(f) for f in files]
        file_paths = self.sort_files_naturally(file_paths)
        
        print(f"[文件] 找到 {len(file_paths)} 个文件:")
        for i, f in enumerate(file_paths, 1):
            print(f"  {i:2d}. {Path(f).name}")
        
        # 验证数量
        if len(file_paths) < len(titles):
            print(f"[错误] 错误: 文件数({len(file_paths)})少于标题数({len(titles)})")
            print(f"     文件: {len(file_paths)} 个, 标题: {len(titles)} 个")
            return False
        elif len(file_paths) > len(titles):
            print(f"[警告] 文件数({len(file_paths)})多于标题数({len(titles)})，将只处理前{len(titles)}个文件")
            file_paths = file_paths[:len(titles)]
        
        # 生成重命名操作列表
        self.operations_log = []
        operations = []
        
        print("\n[计划] 重命名计划:")
        for i, (file_path, title) in enumerate(zip(file_paths, titles), start=start_ep):
            old_name = str(file_path)
            new_name = self.generate_new_name(prefix, i, title)
            operations.append((old_name, new_name))
            self.operations_log.append({
                "old_name": old_name,
                "new_name": new_name,
                "episode": i,
                "title": title
            })
            
            # 显示预览
            old_display = Path(old_name).name
            print(f"{i:2d}. {old_display}")
            print(f"    → {new_name}")
            
            # 检查文件是否已存在
            if Path(new_name).exists():
                print(f"    [警告] 警告: 目标文件已存在!")
        
        print(f"\n[统计] 总计: {len(operations)} 个文件待重命名")
        
        # 如果是预览模式，直接返回
        if dry_run:
            print("\n[完成] 预览完成，如需实际执行请添加 --execute 参数")
            return True
        
        # 实际执行重命名
        print("\n[警告] 即将执行实际重命名操作!")
        
        # 确认操作
        confirm = input(f"确认重命名 {len(operations)} 个文件？(输入 'yes' 确认): ")
        if confirm.lower() != 'yes':
            print("[错误] 操作取消")
            return False
        
        # 创建备份
        if create_backup:
            if not self.create_backup(file_paths):
                print("[错误] 备份创建失败，操作中止")
                return False
        
        # 执行重命名
        print("\n[执行] 执行重命名:")
        success_count = 0
        failed_operations = []
        
        for old_name, new_name in operations:
            try:
                # 检查目标文件是否已存在
                if Path(new_name).exists():
                    print(f"  ⚠️  跳过: {Path(old_name).name} → {new_name} (目标已存在)")
                    failed_operations.append((old_name, new_name, "目标文件已存在"))
                    continue
                
                # 执行重命名
                os.rename(old_name, new_name)
                success_count += 1
                print(f"  [成功] 完成: {Path(old_name).name} → {new_name}")
                
            except Exception as e:
                print(f"  [失败] 失败: {Path(old_name).name} → {new_name}")
                print(f"     错误: {e}")
                failed_operations.append((old_name, new_name, str(e)))
        
        # 输出结果摘要
        print("\n" + "=" * 60)
        print("[摘要] 操作结果摘要:")
        print(f"  [成功] 成功: {success_count} 个文件")
        print(f"  [错误] 失败: {len(failed_operations)} 个文件")
        
        if failed_operations:
            print("\n失败的操作:")
            for old_name, new_name, error in failed_operations:
                print(f"  - {Path(old_name).name}: {error}")
        
        if self.backup_dir:
            print(f"\n[备份] 备份位置: {self.backup_dir}")
            print("   如需恢复，可运行: python rename_videos.py --restore")
        
        return len(failed_operations) == 0
    
    def interactive_mode(self):
        """交互式模式"""
        print("=" * 60)
        print("[交互] 交互式视频重命名模式")
        print("=" * 60)
        
        # 获取文件模式
        pattern = input("请输入文件匹配模式 (如 *.mp4): ").strip()
        if not pattern:
            pattern = "*.mp4"
        
        # 查找文件
        files = sorted(Path('.').glob(pattern))
        if not files:
            print(f"[错误] 未找到匹配模式 '{pattern}' 的文件")
            return False
        
        file_paths = [str(f) for f in files]
        file_paths = self.sort_files_naturally(file_paths)
        
        print(f"\n📁 找到 {len(file_paths)} 个文件:")
        for i, f in enumerate(file_paths, 1):
            print(f"  {i:2d}. {Path(f).name}")
        
        # 获取前缀
        prefix = input("\n请输入文件名前缀: ").strip()
        if not prefix:
            print("[错误] 前缀不能为空")
            return False
        
        # 获取标题
        print("\n请输入标题列表（每行一个标题，空行结束）:")
        titles = []
        i = 1
        while True:
            title = input(f"  第{i}集标题: ").strip()
            if not title:
                break
            titles.append(title)
            i += 1
        
        if len(titles) != len(file_paths):
            print(f"[错误] 标题数量({len(titles)})与文件数量({len(file_paths)})不匹配")
            return False
        
        # 获取起始集数
        start_input = input(f"\n起始集数 (默认为 1): ").strip()
        start_ep = int(start_input) if start_input.isdigit() else 1
        
        # 预览
        print("\n[预览] 重命名预览:")
        for i, (file_path, title) in enumerate(zip(file_paths, titles), start=start_ep):
            new_name = self.generate_new_name(prefix, i, title)
            print(f"{i:2d}. {Path(file_path).name}")
            print(f"    → {new_name}")
        
        # 确认执行
        execute = input("\n是否执行重命名？(y/N): ").strip().lower()
        if execute != 'y':
            print("[错误] 操作取消")
            return False
        
        # 执行重命名
        return self.rename_files(
            pattern=pattern,
            prefix=prefix,
            titles=titles,
            start_ep=start_ep,
            dry_run=False,
            create_backup=True
        )
    
    def auto_detect_mode(self, directory='.') -> bool:
        """自动检测模式"""
        print("=" * 60)
        print("[检测] 智能视频系列检测模式")
        print("=" * 60)
        
        # 创建检测器并运行检测
        detector = VideoSeriesDetector()
        series_list = detector.detect_series(directory)
        
        if not series_list:
            print("[错误] 未检测到明显的视频系列")
            print("建议：")
            print("1. 检查目录中是否有视频文件（.mp4, .mov, .avi, .mkv）")
            print("2. 文件名是否包含数字序列（如 c1, c2, episode_01）")
            print("3. 尝试手动模式：python rename_videos.py --interactive")
            return False
        
        # 显示检测结果
        print(f"[统计] 检测到 {len(series_list)} 个视频系列：")
        for i, series in enumerate(series_list, 1):
            print(f"\n{i}. {series['name']} ({series['count']}个文件, 置信度: {series['confidence']:.1%})")
            print(f"   模式: {series['suggested_pattern']}")
            print(f"   示例: {series['filenames'][0]} ... {series['filenames'][-1]}")
            if not series['is_continuous']:
                print(f"   [警告] 数字不连续: {series['numbers']}")
        
        # 用户选择系列
        print("\n" + "-" * 60)
        selection = input("请选择要处理的系列编号 (输入'all'全选，或'q'退出): ").strip().lower()
        
        if selection == 'q':
            print("[错误] 操作取消")
            return False
        
        selected_series = []
        if selection == 'all':
            selected_series = series_list
        elif selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(series_list):
                selected_series = [series_list[idx]]
            else:
                print(f"[错误] 无效的选择: {selection}")
                return False
        else:
            print(f"[错误] 无效的输入: {selection}")
            return False
        
        # 处理每个选中的系列
        for series in selected_series:
            print(f"\n[处理] 处理系列: {series['name']}")
            
            # 自动生成参数建议
            pattern = series['suggested_pattern']
            prefix_suggestion = series['prefix'] if series['prefix'] else "视频系列"
            
            print(f"   自动检测到的模式: {pattern}")
            print(f"   建议前缀: {prefix_suggestion}")
            
            # 询问用户确认
            use_suggestion = input(f"使用建议的前缀 '{prefix_suggestion}'？(y/N): ").strip().lower()
            if use_suggestion == 'y':
                prefix = prefix_suggestion
            else:
                prefix = input("请输入自定义前缀: ").strip()
                if not prefix:
                    prefix = prefix_suggestion
            
            # 获取标题列表
            print(f"\n[输入] 请为 {series['count']} 个文件输入标题（每行一个，空行结束）:")
            titles = []
            for i in range(1, series['count'] + 1):
                title = input(f"  第{i}集标题: ").strip()
                if not title:
                    print(f"[错误] 需要为所有文件提供标题")
                    return False
                titles.append(title)
            
            # 预览并执行
            print(f"\n[准备] 准备重命名 {series['count']} 个文件...")
            confirm = input("是否继续？(y/N): ").strip().lower()
            if confirm != 'y':
                print("[错误] 操作取消")
                return False
            
            # 执行重命名
            success = self.rename_files(
                pattern=pattern,
                prefix=prefix,
                titles=titles,
                start_ep=1,
                dry_run=False,
                create_backup=True
            )
            
            if not success:
                print(f"[错误] 系列 {series['name']} 重命名失败")
                return False
        
        print("\n[完成] 所有选中系列处理完成")
        return True

class VideoSeriesDetector:
    """视频系列检测器，自动识别目录中的相关视频文件组"""
    
    def __init__(self):
        self.common_patterns = [
            # 模式1: 前缀 + 分隔符 + 数字 + 扩展名 (如: prefix_001.mp4)
            r'^(.+?)[_\-\s\.]+(\d+)[^\d]*\.(mp4|mov|avi|mkv|MP4|MOV|AVI|MKV)$',
            # 模式2: 数字 + 分隔符 + 后缀 (如: 001_suffix.mp4)
            r'^(\d+)[_\-\s\.]+(.+?)\.(mp4|mov|avi|mkv|MP4|MOV|AVI|MKV)$',
            # 模式3: 前缀 + 字母 + 数字 (如: episode_c1.mp4)
            r'^(.+?)([a-zA-Z])(\d+)\.(mp4|mov|avi|mkv|MP4|MOV|AVI|MKV)$',
            # 模式4: 纯数字序列 (如: 001.mp4, 002.mp4)
            r'^(\d+)\.(mp4|mov|avi|mkv|MP4|MOV|AVI|MKV)$',
        ]
        self.supported_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.MP4', '.MOV', '.AVI', '.MKV']
    
    def detect_series(self, directory='.') -> List[Dict]:
        """检测目录中的视频系列"""
        import os
        from collections import defaultdict
        
        # 获取所有视频文件
        all_files = []
        for ext in self.supported_extensions:
            pattern = '*' + ext
            files = list(Path(directory).glob(pattern))
            all_files.extend([str(f) for f in files])
        
        if not all_files:
            return []
        
        # 按自然排序
        all_files = sorted(all_files, key=lambda x: [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', x)])
        
        # 分析每个文件的命名模式
        file_analysis = []
        for file_path in all_files:
            filename = Path(file_path).name
            analysis = self._analyze_filename(filename)
            if analysis:
                file_analysis.append((file_path, analysis))
        
        # 根据分析结果分组
        series_groups = defaultdict(list)
        for file_path, analysis in file_analysis:
            # 创建分组键：前缀 + 模式类型
            group_key = f"{analysis['prefix']}_{analysis['pattern_type']}"
            series_groups[group_key].append((file_path, analysis))
        
        # 构建系列信息
        series_list = []
        for group_key, files in series_groups.items():
            if len(files) >= 2:  # 至少2个文件才认为是系列
                files_sorted = sorted(files, key=lambda x: x[1]['number'])
                numbers = [f[1]['number'] for f in files_sorted]
                
                # 检查数字连续性
                is_continuous = self._check_continuity(numbers)
                
                series_info = {
                    'name': f"系列_{len(series_list)+1}",
                    'files': [f[0] for f in files_sorted],
                    'filenames': [Path(f[0]).name for f in files_sorted],
                    'count': len(files),
                    'prefix': files_sorted[0][1]['prefix'],
                    'pattern_type': files_sorted[0][1]['pattern_type'],
                    'numbers': numbers,
                    'is_continuous': is_continuous,
                    'confidence': 0.8 if is_continuous else 0.5,
                    'suggested_pattern': self._generate_pattern(files_sorted),
                }
                series_list.append(series_info)
        
        # 按置信度排序
        series_list.sort(key=lambda x: x['confidence'], reverse=True)
        return series_list
    
    def _analyze_filename(self, filename):
        """分析单个文件名，提取前缀、数字等信息"""
        for pattern_idx, pattern in enumerate(self.common_patterns):
            match = re.match(pattern, filename)
            if match:
                groups = match.groups()
                if pattern_idx == 0:  # 前缀+数字
                    return {
                        'prefix': groups[0],
                        'number': int(groups[1]),
                        'extension': groups[2],
                        'pattern_type': 'prefix_number'
                    }
                elif pattern_idx == 1:  # 数字+后缀
                    return {
                        'prefix': '',
                        'number': int(groups[0]),
                        'suffix': groups[1],
                        'extension': groups[2],
                        'pattern_type': 'number_suffix'
                    }
                elif pattern_idx == 2:  # 前缀+字母+数字
                    return {
                        'prefix': groups[0],
                        'letter': groups[1],
                        'number': int(groups[2]),
                        'extension': groups[3],
                        'pattern_type': 'prefix_letter_number'
                    }
                elif pattern_idx == 3:  # 纯数字
                    return {
                        'prefix': '',
                        'number': int(groups[0]),
                        'extension': groups[1],
                        'pattern_type': 'number_only'
                    }
        return None
    
    def _check_continuity(self, numbers):
        """检查数字是否连续"""
        if len(numbers) < 2:
            return True
        
        sorted_numbers = sorted(numbers)
        for i in range(1, len(sorted_numbers)):
            if sorted_numbers[i] != sorted_numbers[i-1] + 1:
                return False
        return True
    
    def _generate_pattern(self, files_analysis):
        """根据文件分析生成匹配模式"""
        if not files_analysis:
            return "*.mp4"
        
        first_file = files_analysis[0][1]
        first_filename = Path(files_analysis[0][0]).name
        
        if first_file['pattern_type'] == 'prefix_number':
            # 如: MC-合集-1_c1.mp4 -> MC-合集-*_c*.mp4
            prefix = first_file['prefix']
            # 提取数字前的部分
            import re
            match = re.match(r'^(.*?)(\D*)(\d+)$', prefix)
            if match:
                base_prefix = match.group(1)
                separator = match.group(2) if match.group(2) else ''
                return f"{base_prefix}{separator}*.mp4"
            return f"{first_file['prefix']}*.mp4"
        
        elif first_file['pattern_type'] == 'number_only':
            return "*.mp4"
        
        return "*.mp4"

def main():
    parser = argparse.ArgumentParser(
        description='批量重命名视频文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  1. 预览模式:
     python %(prog)s --pattern "MC-合集-*_c*.mp4" \\
       --prefix "波波之我的世界 培养制图师-上篇" \\
       --titles "标题1,标题2,标题3"
  
  2. 实际执行:
     python %(prog)s --pattern "MC-合集-*_c*.mp4" \\
       --prefix "波波之我的世界 培养制图师-上篇" \\
       --titles "标题1,标题2,标题3" --execute
  
   3. 交互模式:
      python %(prog)s --interactive
   
   4. 智能检测模式:
      python %(prog)s --auto-detect
   
   5. 从备份恢复:
      python %(prog)s --restore --backup-dir "video_backup_20250308_123456"
        """
    )
    
    # 主要参数
    parser.add_argument('--pattern', default='*.mp4', 
                       help='文件匹配模式 (默认: *.mp4)')
    parser.add_argument('--prefix', required=False,
                       help='文件名前缀 (如: "波波之我的世界 培养制图师-上篇")')
    parser.add_argument('--titles', required=False,
                       help='标题列表，用逗号分隔')
    parser.add_argument('--titles-file', required=False,
                       help='从文件读取标题列表 (每行一个标题)')
    parser.add_argument('--start', type=int, default=1,
                       help='起始集数 (默认: 1)')
    
    # 操作模式
    parser.add_argument('--execute', action='store_true',
                       help='实际执行重命名 (默认仅预览)')
    parser.add_argument('--interactive', action='store_true',
                       help='交互式模式')
    parser.add_argument('--auto-detect', action='store_true',
                       help='智能检测模式 (自动识别视频系列)')
    parser.add_argument('--restore', action='store_true',
                       help='从备份恢复文件')
    parser.add_argument('--backup-dir',
                       help='指定备份目录 (用于恢复)')
    parser.add_argument('--no-backup', action='store_true',
                       help='不创建备份 (谨慎使用)')
    
    args = parser.parse_args()
    
    # 创建重命名器实例
    renamer = VideoRenamer()
    
    # 处理恢复模式
    if args.restore:
        backup_dir = args.backup_dir
        if backup_dir:
            renamer.backup_dir = Path(backup_dir)
        success = renamer.restore_from_backup()
        sys.exit(0 if success else 1)
    
    # 处理交互模式
    if args.interactive:
        success = renamer.interactive_mode()
        sys.exit(0 if success else 1)
    
    # 处理智能检测模式
    if args.auto_detect:
        success = renamer.auto_detect_mode()
        sys.exit(0 if success else 1)
    
    # 验证必需参数
    if not args.prefix and not args.interactive and not args.auto_detect:
        print("[错误] 错误: 必须提供 --prefix 参数或使用 --interactive/--auto-detect 模式")
        parser.print_help()
        sys.exit(1)
    
    # 获取标题列表
    titles = []
    if args.titles:
        titles = [t.strip() for t in args.titles.split(',')]
    elif args.titles_file:
        try:
            with open(args.titles_file, 'r', encoding='utf-8') as f:
                titles = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"[错误] 读取标题文件失败: {e}")
            sys.exit(1)
    
    # 执行重命名
    success = renamer.rename_files(
        pattern=args.pattern,
        prefix=args.prefix,
        titles=titles,
        start_ep=args.start,
        dry_run=not args.execute,
        create_backup=not args.no_backup
    )
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[错误] 操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] 程序运行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)