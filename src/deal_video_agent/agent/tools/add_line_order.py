# -*- coding: utf-8 -*-
"""
字幕添加行号工具
"""
import os
from pathlib import Path


class AddLineOrderTool:
    """字幕添加行号工具"""
    
    def run(self, input_file: str) -> str:
        """
        运行脚本添加行号
        
        Args:
            input_file: 输入的字幕文件路径
            
        Returns:
            输出文件路径（带行号的文件）
        """
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"输入文件不存在: {input_file}")
        
        # 构建输出文件路径
        file_path = Path(input_file)
        file_name_no_ext = file_path.stem
        output_file = file_path.parent / f"{file_name_no_ext}_ordered.txt"
        
        encodings = ['utf-8', 'gbk', 'utf-16']
        
        for encoding in encodings:
            try:
                with open(input_file, 'r', encoding=encoding) as f:
                    lines = f.readlines()
                
                # 添加行号
                with open(output_file, 'w', encoding=encoding) as f:
                    for i, line in enumerate(lines, 1):
                        f.write(f"{i}:{line.rstrip()}\n")
                
                return str(output_file)
            
            except UnicodeDecodeError:
                continue
            except Exception as e:
                raise RuntimeError(f"处理失败: {e}")
        
        raise RuntimeError("无法用常见编码读取文件")


if __name__ == "__main__":
    # 测试代码
    tool = AddLineOrderTool()
    result = tool.run(r"D:\VedioRecords\剪辑草稿\初稿\我的世界\合集三\MC-合集3.txt")
    print(f"输出文件: {result}")