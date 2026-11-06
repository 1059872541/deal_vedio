# corrected.txt 中 字幕纠正后得内容,更新到指定对应 srt字幕文件中,替换错误的字幕。
# 生成一个 _corrected.srt 的新字幕文件,用于导入剪辑软件中,完成视频的字幕替换工作。 
import re
import os
import sys

def format_time(time_str):
    """确保时间轴格式符合剪映要求"""
    # 剪映通常期望时间格式为: 00:00:00,000 --> 00:00:00,000
    if '.' in time_str:
        time_str = time_str.replace('.', ',')
    
    # 确保毫秒部分有3位数字
    parts = time_str.split(' --> ')
    if len(parts) == 2:
        start, end = parts
        for i, part in enumerate([start, end]):
            if ',' in part:
                time, ms = part.split(',', 1)
                ms = ms.strip()
                if len(ms) < 3:
                    ms = ms.ljust(3, '0')
                elif len(ms) > 3:
                    ms = ms[:3]
                parts[i] = f"{time.strip()},{ms}"
            elif ':' in part and len(part.split(':')) == 4:
                # 处理没有逗号但有冒号分隔毫秒的情况
                h, m, s, ms = part.split(':')
                ms = ms.ljust(3, '0')[:3]
                parts[i] = f"{h}:{m}:{s},{ms}"
        time_str = ' --> '.join(parts)
    
    return time_str

def main(base_dir):
    if not base_dir:
        raise ValueError("请提供父目录路径作为参数")
    
    # 自动查找该目录下的 .srt 文件（按修改时间排序，选取最早的一个）
    srt_files = [f for f in os.listdir(base_dir) if f.lower().endswith('.srt')]
    if not srt_files:
        raise FileNotFoundError(f"在目录 {base_dir} 中未找到 .srt 文件")
    
    srt_files_with_mtime = [(f, os.path.getmtime(os.path.join(base_dir, f))) for f in srt_files]
    srt_files_sorted = sorted(srt_files_with_mtime, key=lambda x: x[1])
    srt_file = os.path.join(base_dir, srt_files_sorted[0][0])
    
    # corrected.txt 固定文件名
    corrected_file = os.path.join(base_dir, "corrected.txt")
    
    # 根据srt_file自动生成output_file路径
    srt_dir = os.path.dirname(srt_file)
    srt_filename = os.path.basename(srt_file)
    srt_name, srt_ext = os.path.splitext(srt_filename)
    output_file = os.path.join(srt_dir, f"{srt_name}_corrected{srt_ext}")
    
    try:
        # 读取原始SRT文件
        with open(srt_file, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        
        # 使用正则表达式匹配SRT块
        # 匹配模式: 数字行 + 时间轴行 + 文本内容(直到下一个数字块或文件结束)
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
                
                # 检查是否是序号行 (格式: "序号:" 或 "序号|")
                if re.match(r'^\d+[:|]', line):
                    # 保存前一个修正
                    if current_num is not None:
                        corrections[current_num] = '\n'.join(current_text)
                    
                    # 开始新的修正
                    parts = re.split(r'[:|]', line, 1)
                    current_num = parts[0].strip()
                    current_text = [parts[1].strip()] if len(parts) > 1 else []
                elif current_num is not None:
                    # 多行修正内容
                    current_text.append(line)
                else:
                    print(f"警告: 忽略格式不正确的行: {line}")
            
            # 保存最后一个修正
            if current_num is not None and current_text:
                corrections[current_num] = '\n'.join(current_text)
        
        print(f"找到 {len(blocks)} 个字幕块，{len(corrections)} 个修正")
        
        # 重新构建SRT内容
        output_lines = []
        for i, (num, time_line, text) in enumerate(blocks, 1):
            # 格式化时间轴
            formatted_time = format_time(time_line)
            
            # 应用修正（如果存在）
            if num in corrections:
                new_text = corrections[num]
                print(f"替换字幕 {num}: {text[:50]}... -> {new_text[:50]}...")
            else:
                new_text = text.strip()
            
            # 清理文本中的多余空格但保留换行
            text_lines = [line.strip() for line in new_text.split('\n') if line.strip()]
            formatted_text = '\n'.join(text_lines)
            
            # 添加块到输出
            output_lines.append(str(i))  # 使用连续序号
            output_lines.append(formatted_time)
            output_lines.append(formatted_text)
            output_lines.append('')  # 块间空行
        
        # 移除末尾多余空行
        if output_lines and output_lines[-1] == '':
            output_lines.pop()
        
        # 写入输出文件（使用剪映偏好的UTF-8带BOM编码）
        with open(output_file, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(output_lines))
        
        print(f"处理完成，输出文件: {output_file}")
        
        # 验证输出文件
        with open(output_file, 'r', encoding='utf-8-sig') as f:
            output_content = f.read()
            output_blocks = re.findall(pattern, output_content)
            print(f"输出文件包含 {len(output_blocks)} 个字幕块")
            
    except FileNotFoundError as e:
        print(f"错误: 文件未找到 - {e}")
        print("请检查文件路径是否正确")
    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python updateSRT.py <父目录路径>")
        print("示例: python updateSRT.py D:\\VedioRecords\\工作区\\我的世界\\合集\\合集一\\剪辑")
        sys.exit(1)
    main(sys.argv[1])