#将srt字幕文件，按照时间长度 分割成多个子文件,并去除时间戳和多余空行,输出成txt纯文本
import os
import re
import shutil
from pathlib import Path

def parse_srt_time(time_str):
    """将 SRT 时间格式 '00:00:00,000' 转换为总秒数（浮点）"""
    h, m, rest = time_str.split(':')
    s, ms = rest.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def format_chinese_episode(index):
    """将数字转换为中文集数名称，如 1 -> 第一集"""
    chinese_nums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
    if 1 <= index <= 10:
        return f"第{chinese_nums[index]}集"
    elif 11 <= index <= 19:
        return f"第十一集" if index == 11 else f"第{chinese_nums[10]}{chinese_nums[index % 10]}集"
    elif 20 <= index <= 99:
        tens = index // 10
        units = index % 10
        if units == 0:
            return f"第{chinese_nums[tens]}十集"
        else:
            return f"第{chinese_nums[tens]}十{chinese_nums[units]}集"
    else:
        # 对于大于99的情况，回退为数字（实际很少超过）
        return f"第{index}集"

def split_srt_by_duration(srt_path, segment_duration_minutes=6):
    srt_path = Path(srt_path)
    if not srt_path.exists() or srt_path.suffix.lower() != '.srt':
        raise ValueError("请提供有效的 .srt 文件路径")

    output_dir = srt_path.parent / "words"
    if output_dir.exists():
        shutil.rmtree(output_dir)  # 清空旧内容
    output_dir.mkdir()

    segment_duration_seconds = segment_duration_minutes * 60

    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 使用正则匹配字幕块：序号 + 时间戳 + 多行文本
    subtitle_blocks = re.split(r'\n\s*\n', content.strip())
    subtitles = []

    for block in subtitle_blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 3:
            continue  # 跳过无效块

        # 尝试解析时间戳行（通常是第二行）
        time_line = lines[1]
        time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', time_line)
        if not time_match:
            continue

        start_time_str, end_time_str = time_match.groups()
        start_sec = parse_srt_time(start_time_str)
        end_sec = parse_srt_time(end_time_str)

        # 合并文本行（跳过序号和时间戳）
        text_lines = lines[2:]
        text = ' '.join(text_lines).replace('\n', ' ').strip()
        if not text:
            continue

        subtitles.append({
            'start': start_sec,
            'end': end_sec,
            'text': text
        })

    if not subtitles:
        print("未找到有效字幕内容。")
        return

    total_duration = subtitles[-1]['end']
    num_segments = int(total_duration // segment_duration_seconds) + 1

    current_segment = 0
    current_output_lines = []
    segment_end_time = segment_duration_seconds

    for sub in subtitles:
        if sub['start'] < segment_end_time:
            current_output_lines.append(sub['text'])
        else:
            # 写出当前段
            if current_output_lines:
                episode_name = format_chinese_episode(current_segment + 1)
                output_file = output_dir / f"{episode_name}.txt"
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(current_output_lines))
                print(f"已生成: {output_file.name}")

            # 进入下一段
            current_segment += 1
            segment_end_time = (current_segment + 1) * segment_duration_seconds
            current_output_lines = [sub['text']]

    # 写出最后一段
    if current_output_lines:
        episode_name = format_chinese_episode(current_segment + 1)
        output_file = output_dir / f"{episode_name}.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(current_output_lines))
        print(f"已生成: {output_file.name}")

    print(f"\n共生成 {current_segment + 1} 个文件，保存在: {output_dir}")


# ==============================
# 配置区：直接在这里修改路径和分割时长
# ==============================
srt_file = r"D:\VedioRecords\剪辑草稿\初剪辑\星露谷物语\合集二\星露谷物语-合集-2_corrected.srt"
duration = 6  # 单位：分钟

# ==============================
# 主程序执行
# ==============================
if __name__ == "__main__":
    try:
        split_srt_by_duration(srt_file, duration)
    except Exception as e:
        print(f"错误: {e}")
        input("按回车键退出...")  # 方便在 Windows 双击运行时查看错误