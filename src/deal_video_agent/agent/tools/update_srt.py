# -*- coding: utf-8 -*-
"""
字幕更新工具
将 corrected.txt 的纠正内容回写到 SRT
"""
import os
import re
from pathlib import Path
from typing import Optional


class UpdateSRT_tool:
    """字幕SRT更新工具"""
    
    def __init__(self):
        """初始化工具"""
        pass
    
    def run(self, subtitle_dir: str) -> str:
        """
        运行脚本更新SRT字幕
        
        Args:
            subtitle_dir: 字幕所在目录
            
        Returns:
            输出的 corrected.srt 文件路径
        """
        # 自动查找 .srt 文件
        srt_files = [f for f in os.listdir(subtitle_dir) if f.lower().endswith('.srt')]
        if not srt_files:
            raise FileNotFoundError(f"在目录 {subtitle_dir} 中未找到 .srt 文件")
        
        # 按修改时间排序，选取最早的一个
        srt_files_with_mtime = [
            (f, os.path.getmtime(os.path.join(subtitle_dir, f))) 
            for f in srt_files
        ]
        srt_files_sorted = sorted(srt_files_with_mtime, key=lambda x: x[1])
        srt_file = os.path.join(subtitle_dir, srt_files_sorted[0][0])
        
        # corrected.txt 固定文件名
        corrected_file = os.path.join(subtitle_dir, "corrected.txt")
        if not os.path.exists(corrected_file):
            raise FileNotFoundError(f"未找到纠正文件: {corrected_file}")
        
        # 输出文件路径
        srt_name = Path(srt_file).stem
        output_file = os.path.join(subtitle_dir, f"{srt_name}_corrected.srt")
        
        # 执行更新
        self._update_srt(srt_file, corrected_file, output_file)
        
        return output_file
    
    def _update_srt(self, srt_file: str, corrected_file: str, output_file: str):
        """更新SRT字幕文件"""
        # 读取原始SRT文件
        with open(srt_file, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        
        # 使用正则表达式匹配SRT块
        pattern = r'(\d+)\s*\n\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*\n\s*([\s\S]*?)(?=\n\d+\s*\n|\Z)'
        blocks = re.findall(pattern, content)
        
        # 解析修正内容
        corrections = {}
        with open(corrected_file, 'r', encoding='utf-8-sig') as f:
            current_num = None
            current_text = []
            
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # 检查是否是序号行 (格式: "序号:")
                if re.match(r'^\d+[:|]', line):
                    if current_num is not None:
                        corrections[current_num] = '\n'.join(current_text)
                    
                    parts = re.split(r'[:|]', line, 1)
                    current_num = parts[0].strip()
                    current_text = [parts[1].strip()] if len(parts) > 1 else []
                elif current_num is not None:
                    current_text.append(line)
            
            if current_num is not None and current_text:
                corrections[current_num] = '\n'.join(current_text)
        
        # 重新构建SRT内容
        output_lines = []
        for i, (num, time_line, text) in enumerate(blocks, 1):
            if num in corrections:
                new_text = corrections[num]
            else:
                new_text = text.strip()
            
            text_lines = [line.strip() for line in new_text.split('\n') if line.strip()]
            formatted_text = '\n'.join(text_lines)
            
            output_lines.append(str(i))
            output_lines.append(time_line.strip())
            output_lines.append(formatted_text)
            output_lines.append('')
        
        # 移除末尾多余空行
        while output_lines and output_lines[-1] == '':
            output_lines.pop()
        
        # 写入输出文件：UTF-8 无 BOM + CRLF，对齐剪映自己导出的 srt。
        # （旧版写 utf-8-sig 带 BOM，是"剪映要求 BOM"的猜测，实测剪映自己导出的没 BOM）
        with open(output_file, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write('\n'.join(output_lines))


if __name__ == "__main__":
    # 测试代码
    tool = UpdateSRT_tool()
    result = tool.run(r"D:\VedioRecords\剪辑草稿\初稿\我的世界\合集三")
    print(f"输出文件: {result}")