#!/usr/bin/env python3
"""
文本工具类
路径: src/util/text_utils.py
职责: 中文数字转换、字符串处理、文本格式化、视频文件排序
"""

import re
import sys
import io
from pathlib import Path
from typing import List, Tuple, Optional, Callable


class TextUtils:
    """文本处理工具类（静态方法，无需实例化）"""
    
    # 中文数字映射
    _CN_NUMS = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '百': 100, '千': 1000, '万': 10000
    }
    
    _CN_NUMS_REVERSE = {v: k for k, v in _CN_NUMS.items()}
    
    # 中文数字正则（支持一-九十九）
    _CN_NUMBER_PATTERN = re.compile(
        r'[一二三四五六七八九十百]+'
    )
    
    @staticmethod
    def number_to_chinese(num: int) -> str:
        """
        阿拉伯数字转中文（1-9999）
        
        Args:
            num: 数字（1-9999）
        
        Returns:
            中文数字字符串
        
        Examples:
            1 -> "一"
            10 -> "十"
            23 -> "二十三"
            100 -> "一百"
        """
        if not 1 <= num <= 9999:
            return str(num)
        
        if num <= 10:
            return TextUtils._CN_NUMS_REVERSE[num]
        
        if num < 20:
            # 11-19: 十一、十二...
            return "十" + (TextUtils._CN_NUMS_REVERSE[num - 10] if num > 10 else "")
        
        if num < 100:
            # 21-99
            tens = num // 10
            ones = num % 10
            if ones == 0:
                return TextUtils._CN_NUMS_REVERSE[tens] + "十"
            else:
                return TextUtils._CN_NUMS_REVERSE[tens] + "十" + TextUtils._CN_NUMS_REVERSE[ones]
        
        if num < 1000:
            # 100-999
            hundreds = num // 100
            remainder = num % 100
            result = TextUtils._CN_NUMS_REVERSE[hundreds] + "百"
            if remainder > 0:
                if remainder < 10:
                    result += "零" + TextUtils._CN_NUMS_REVERSE[remainder]
                else:
                    result += TextUtils.number_to_chinese(remainder)
            return result
        
        # 1000-9999
        thousands = num // 1000
        remainder = num % 1000
        result = TextUtils._CN_NUMS_REVERSE[thousands] + "千"
        if remainder > 0:
            if remainder < 100:
                result += "零" + TextUtils.number_to_chinese(remainder)
            else:
                result += TextUtils.number_to_chinese(remainder)
        return result
    
    @staticmethod
    def chinese_to_number(cn: str) -> int:
        """
        中文数字转阿拉伯数字（支持一-九十九，简化版）
        
        Args:
            cn: 中文数字字符串（如"二十三"）
        
        Returns:
            阿拉伯数字
        
        Examples:
            "一" -> 1
            "十" -> 10
            "二十三" -> 23
            "九十九" -> 99
        """
        if not cn:
            return 0
        
        # 简单情况：单个数字
        if len(cn) == 1 and cn in TextUtils._CN_NUMS:
            return TextUtils._CN_NUMS[cn]
        
        # 处理"十"开头（十一-十九）
        if cn.startswith('十'):
            if len(cn) == 1:
                return 10
            # 十一、十二...
            return 10 + TextUtils._CN_NUMS.get(cn[1], 0)
        
        # 处理"十"结尾（二十、三十...）
        if cn.endswith('十'):
            if len(cn) == 2:
                return TextUtils._CN_NUMS.get(cn[0], 0) * 10
        
        # 处理中间带"十"（二十一-九十九）
        if '十' in cn:
            parts = cn.split('十')
            if len(parts) == 2:
                tens = TextUtils._CN_NUMS.get(parts[0], 0) * 10
                ones = TextUtils._CN_NUMS.get(parts[1], 0) if parts[1] else 0
                return tens + ones
        
        # 处理"百"（一百-九百九十九）
        if '百' in cn:
            parts = cn.split('百')
            hundreds = TextUtils._CN_NUMS.get(parts[0], 0) * 100
            if len(parts) > 1 and parts[1]:
                # 有十位和个位
                remainder = TextUtils.chinese_to_number(parts[1])
                return hundreds + remainder
            return hundreds
        
        # 纯数字累加（如"一二三"这种不规范写法）
        result = 0
        for char in cn:
            if char in TextUtils._CN_NUMS:
                result = result * 10 + TextUtils._CN_NUMS[char]
        return result
    
    @staticmethod
    def extract_chinese_number(text: str) -> Optional[Tuple[str, int]]:
        """
        从文本中提取第一个中文数字及其数值
        
        Args:
            text: 原始文本（如"3-1 试炼密室初见.mkv"）
        
        Returns:
            (中文数字, 阿拉伯数字) 或 None
        
        Examples:
            "合集三" -> ("三", 3)
            "3-1 试炼密室初见" -> None（无中文数字）
            "第二十集" -> ("二十", 20)
        """
        match = TextUtils._CN_NUMBER_PATTERN.search(text)
        if not match:
            return None
        
        cn_num = match.group()
        arabic_num = TextUtils.chinese_to_number(cn_num)
        return (cn_num, arabic_num)
    
    @staticmethod
    def sort_by_chinese_number(
        items: List[str],
        reverse: bool = False,
        default_key: Callable[[str], str] = lambda x: x
    ) -> List[str]:
        """
        根据中文数字排序字符串列表
        
        Args:
            items: 字符串列表
            reverse: 是否降序（默认升序）
            default_key: 无中文数字时的排序键
        
        Returns:
            排序后的列表
        
        Examples:
            ["合集三", "合集一", "合集十"] -> ["合集一", "合集三", "合集十"]
            ["第一集", "第二集", "第十集"] -> ["第一集", "第二集", "第十集"]
        """
        def sort_key(item: str) -> Tuple[int, int, str]:
            extracted = TextUtils.extract_chinese_number(item)
            if extracted:
                # 有中文数字：按数值排序，其次按原字符串
                return (0, extracted[1], item)
            else:
                # 无中文数字：排在最后，按默认键排序
                return (1, 0, default_key(item))
        
        return sorted(items, key=sort_key, reverse=reverse)
    
    @staticmethod
    def sort_video_files(
        files: List[Path],
        reverse: bool = False
    ) -> List[Path]:
        """
        视频文件中文排序（核心功能）
        
        根据文件名中的中文数字（一-九十九）进行排序
        
        Args:
            files: 视频文件路径列表
            reverse: 是否降序（默认升序）
        
        Returns:
            排序后的路径列表
        
        Examples:
            [3-1.mkv, 3-2.mkv, 3-十.mkv] -> 按中文数字排序
            [合集三/素材.mp4, 合集一/素材.mp4] -> [合集一..., 合集三...]
        """
        # 转换为 (路径, 文件名) 元组列表
        file_tuples = [(f, f.name) for f in files]
        
        # 按文件名中的中文数字排序
        sorted_names = TextUtils.sort_by_chinese_number(
            [t[1] for t in file_tuples],
            reverse=reverse
        )
        
        # 构建文件名到路径的映射（处理同名情况）
        name_to_paths: dict = {}
        for path, name in file_tuples:
            if name not in name_to_paths:
                name_to_paths[name] = []
            name_to_paths[name].append(path)
        
        # 按排序后的名称重新组装
        result = []
        for name in sorted_names:
            result.extend(name_to_paths[name])
        
        return result
    
    @staticmethod
    def sort_video_files_by_parent(
        files: List[Path],
        reverse: bool = False
    ) -> List[Path]:
        """
        按父目录名中的中文数字排序视频文件
        
        用于：合集一/素材.mp4, 合集二/素材.mp4 这种结构
        
        Args:
            files: 视频文件路径列表
            reverse: 是否降序
        
        Returns:
            排序后的路径列表
        """
        def sort_key(path: Path) -> Tuple[int, int, str]:
            # 优先使用父目录名中的中文数字
            parent_name = path.parent.name
            extracted = TextUtils.extract_chinese_number(parent_name)
            
            if extracted:
                return (0, extracted[1], path.name)
            else:
                # 其次使用文件名中的中文数字
                file_extracted = TextUtils.extract_chinese_number(path.name)
                if file_extracted:
                    return (1, file_extracted[1], path.name)
                else:
                    return (2, 0, path.name)
        
        return sorted(files, key=sort_key, reverse=reverse)
    
    @staticmethod
    def add_line_numbers(text: str, start: int = 1, separator: str = ":") -> str:
        """
        为文本添加行号
        
        Args:
            text: 原始文本
            start: 起始行号
            separator: 分隔符（默认":"）
        
        Returns:
            带行号的文本
        
        Examples:
            "第一行\n第二行" -> "1:第一行\n2:第二行"
        """
        lines = text.strip().split('\n')
        numbered_lines = []
        
        for i, line in enumerate(lines, start=start):
            # 跳过空行，但保留行号连续性
            numbered_lines.append(f"{i}{separator}{line}")
        
        return '\n'.join(numbered_lines)
    
    @staticmethod
    def remove_line_numbers(text: str, separator: str = ":") -> str:
        """
        移除行号，还原原始文本
        
        Args:
            text: 带行号的文本
            separator: 分隔符
        
        Returns:
            原始文本
        """
        lines = text.strip().split('\n')
        result_lines = []
        
        for line in lines:
            # 匹配行号格式：数字:内容
            match = re.match(r'^\d+\\' + separator + r'(.*)$', line)
            if match:
                result_lines.append(match.group(1))
            else:
                # 不匹配则保留原样
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @staticmethod
    def generate_collection_names(count: int, start: int = 1) -> List[str]:
        """
        批量生成合集名称列表
        
        Args:
            count: 数量
            start: 起始序号
        
        Returns:
            合集名称列表（如["合集一", "合集二", "合集三"]）
        """
        return [
            f"合集{TextUtils.number_to_chinese(i)}"
            for i in range(start, start + count)
        ]
    
    @staticmethod
    def safe_filename(text: str) -> str:
        """
        生成安全的文件名（移除非法字符）
        
        Args:
            text: 原始文本
        
        Returns:
            安全的文件名
        """
        # Windows 非法字符: < > : " / \ | ? *
        illegal_chars = '<>:"/\\|?*'
        for char in illegal_chars:
            text = text.replace(char, '_')
        return text.strip()
    
    @staticmethod
    def truncate(text: str, max_length: int, suffix: str = "...") -> str:
        """
        截断文本
        
        Args:
            text: 原始文本
            max_length: 最大长度
            suffix: 截断后缀
        
        Returns:
            截断后的文本
        """
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix


# ============== 测试入口 ==============

if __name__ == "__main__":
    print("=== 数字转换测试 ===")
    test_nums = [1, 5, 10, 12, 20, 23, 30, 45, 99, 100, 101, 110, 123, 999, 1000, 9999]
    for n in test_nums:
        cn = TextUtils.number_to_chinese(n)
        back = TextUtils.chinese_to_number(cn)
        status = "✓" if back == n else "✗"
        print(f"{status} {n:4d} <-> {cn:8s} ({back})")
    
    print("\n=== 中文提取测试 ===")
    test_strings = [
        "合集三",
        "3-1 试炼密室初见.mkv",
        "第二十集",
        "培养制图师-下篇",
        "MC-合集5_c1.mp4",
        "合集十二"
    ]
    for s in test_strings:
        result = TextUtils.extract_chinese_number(s)
        print(f"'{s}' -> {result}")
    
    print("\n=== 字符串排序测试 ===")
    names = ["合集三", "合集一", "合集十", "合集二", "合集十二", "合集五"]
    sorted_asc = TextUtils.sort_by_chinese_number(names)
    sorted_desc = TextUtils.sort_by_chinese_number(names, reverse=True)
    print(f"原始: {names}")
    print(f"升序: {sorted_asc}")
    print(f"降序: {sorted_desc}")
    
    print("\n=== 视频文件排序测试 ===")
    # 模拟文件路径
    from pathlib import Path
    mock_files = [
        Path("合集三/素材.mp4"),
        Path("合集一/素材.mp4"),
        Path("合集十/素材.mp4"),
        Path("合集二/素材.mp4"),
        Path("无中文/素材.mp4"),
        Path("合集十二/素材.mp4"),
    ]
    sorted_files = TextUtils.sort_video_files_by_parent(mock_files)
    print("按父目录排序:")
    for f in sorted_files:
        print(f"  {f}")
    
    print("\n✓ 测试完成")


# ============== 视频工具函数（共享） ==============
# 以下函数供 redistribute_material.py 等脚本共用

def ensure_utf8_stdout():
    """修正 Windows 终端 Unicode 输出"""
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def extract_numeric_sort_key(filename: str) -> tuple:
    """从 X-Y 格式文件名提取排序键 (X, Y)"""
    match = re.match(r'^(\d+)-(\d+)', filename)
    if match:
        first = int(match.group(1))
        second = int(match.group(2))
        if first > 0 and second > 0:
            return (first, second)
    return (999999, filename)


def sort_videos_by_name(video_list: list, name_key: str = "filename") -> list:
    """按 X-Y 编号排序视频列表"""
    if video_list and isinstance(video_list[0], dict):
        return sorted(video_list, key=lambda x: extract_numeric_sort_key(x.get(name_key, "")))
    return sorted(video_list, key=lambda x: extract_numeric_sort_key(str(x)))


def format_duration(seconds: int, style: str = "short") -> str:
    """格式化时长

    style: "hms"  → 01:23:45
           "full" → 1h23m45s
           "short" → 1h23m45s | 23m45s | 45s
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if style == "hms":
        return f"{h:02d}:{m:02d}:{s:02d}"
    elif style == "full":
        return f"{h}h{m}m{s}s"
    else:
        if h > 0:
            return f"{h}h{m}m{s}s"
        elif m > 0:
            return f"{m}m{s}s"
        return f"{s}s"


def match_filename(filename: str, pattern: str) -> bool:
    """检查文件名是否匹配正则"""
    try:
        return re.match(pattern, filename) is not None
    except re.error:
        return False