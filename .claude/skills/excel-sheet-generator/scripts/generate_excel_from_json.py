# -*- coding: utf-8 -*-
"""
根据JSON文件生成Excel片单
读取get_videos_duration.py生成的JSON文件，生成带格式的Excel
"""

import os
import sys
import json
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

# 样式定义（固定格式）
red_font = Font(color='FFFF0000', size=11, bold=False)
red_font_bold = Font(color='FFFF0000', size=11, bold=True)
black_font_bold = Font(color='FF000000', size=11, bold=True)
black_font = Font(color='FF000000', size=11)

center_align = Alignment(horizontal='left', vertical='center')
black_fill = PatternFill(fill_type='solid', fgColor='FF333333', bgColor='FF333333')

thin_border = Border(
    left=Side(style='thin', color='FF000000'),
    right=Side(style='thin', color='FF000000'),
    top=Side(style='thin', color='FF000000'),
    bottom=Side(style='thin', color='FF000000')
)

def apply_border_to_cell(cell):
    cell.border = thin_border

def apply_border_to_range(ws, start_row, end_row, cols):
    """为合并范围内的所有单元格添加边框"""
    for row in range(start_row, end_row + 1):
        for col in cols:
            cell = ws.cell(row, col)
            apply_border_to_cell(cell)

def generate_excel_from_json(json_file, output_file=None, host="波波", category="端游", year=2026, intro_duration=600):
    """
    根据JSON文件生成Excel
    
    参数:
        json_file: 输入的JSON文件路径
        output_file: 输出的Excel文件路径（可选，默认生成）
        host: 主播名称（默认"波波"）
        category: 类别（默认"端游"）
        year: 出品年份（默认2026）
        intro_duration: 片头时长（默认600秒）
    
    JSON输入格式:
    [
      {
        "series_title": "波波之我的世界 xxx",
        "video_count": 20,
        "total_duration": 8640,
        "videos": [
          {"filename": "第一集 标题", "episode_num": 1, "duration": 432},
          ...
        ]
      }
    ]
    """
    # 读取JSON数据
    with open(json_file, 'r', encoding='utf-8') as f:
        collections_data = json.load(f)
    
    # 计算汇总数据
    total_videos = sum(c['video_count'] for c in collections_data)
    total_seconds = sum(c['total_duration'] for c in collections_data)
    total_no_intro = total_seconds - intro_duration * len(collections_data)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    hours_no_intro = total_no_intro // 3600
    minutes_no_intro = (total_no_intro % 3600) // 60
    seconds_no_intro = total_no_intro % 60
    
    # 输出路径：**以调用方传进来的为准**。
    # 没传就写在 JSON 同目录 —— 输入在哪，产物就在哪；本脚本不再写死任何本机目录，
    # 换台机器、换个批次都不用改代码。
    if output_file is None:
        current_month = datetime.now().month
        output_file = os.path.join(
            os.path.dirname(os.path.abspath(json_file)),
            f"{year % 100}年{host}{current_month}月第一批片单.xlsx",
        )

    out_dir = os.path.dirname(os.path.abspath(output_file))
    os.makedirs(out_dir, exist_ok=True)
    
    # 创建工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    
    # 第1行：汇总标题 (A1-G1)
    ws['A1'] = '合集数'
    ws['B1'] = '总条数'
    ws['C1'] = '总时长(秒)'
    ws['D1'] = '总合集时长（秒）'
    ws['E1'] = '总时长(时)'
    ws['F1'] = '减完片头总合集时长（秒）'
    ws['G1'] = '减完片头总时长(时)'
    
    for col in ['A1','B1','C1','D1','E1','F1','G1','H1','I1','J1','K1','L1']:
        ws[col].font = black_font
        ws[col].alignment = center_align
        apply_border_to_cell(ws[col])
    
    # 第2行：汇总数据
    ws['A2'] = len(collections_data)
    ws['B2'] = total_videos
    ws['C2'] = total_seconds
    ws['D2'] = total_seconds
    ws['E2'] = f'{hours}:{minutes:02d}:{seconds:02d}'
    ws['F2'] = total_no_intro
    ws['G2'] = f'{hours_no_intro}:{minutes_no_intro:02d}:{seconds_no_intro:02d}'
    
    for col in ['A2','B2','C2','D2','E2','F2','G2','H2','I2','J2','K2','L2']:
        ws[col].font = black_font
        ws[col].alignment = center_align
        apply_border_to_cell(ws[col])
    
    # 第3行：空行，黑色填充，合并A3-L3
    ws.merge_cells('A3:L3')
    ws['A3'].fill = black_fill
    apply_border_to_cell(ws['A3'])
    
    # 第4行：列标题
    ws['A4'] = '合集名'
    ws['B4'] = '精彩看点'
    ws['C4'] = '时长（秒）'
    ws['D4'] = '合集时长（秒）'
    ws['E4'] = '片头时长（秒）'
    ws['F4'] = '减完片头合集时长（秒）'
    ws['G4'] = '主播'
    ws['H4'] = '类别'
    ws['I4'] = '集数'
    ws['J4'] = '出品年份'
    ws['K4'] = '内容介绍'
    ws['L4'] = '关键字'
    
    for col in ['A4','B4','C4','D4','E4','F4','G4','H4','K4','L4']:
        ws[col].font = red_font_bold
        ws[col].alignment = center_align
        apply_border_to_cell(ws[col])
    for col in ['I4','J4']:
        ws[col].font = black_font_bold
        ws[col].alignment = center_align
        apply_border_to_cell(ws[col])
    
    # 写入数据
    current_row = 5
    for col_data in collections_data:
        col_seconds = col_data['total_duration']
        col_count = col_data['video_count']
        intro_seconds = col_seconds - intro_duration
        
        start_row = current_row
        end_row = current_row + col_count - 1
        
        videos = col_data['videos']
        first_video = videos[0]
        
        # 写入第一行数据
        ws[f'A{current_row}'] = col_data['series_title']
        ws[f'B{current_row}'] = first_video['filename']
        ws[f'C{current_row}'] = first_video['duration']
        ws[f'D{current_row}'] = col_seconds
        ws[f'E{current_row}'] = intro_duration
        ws[f'F{current_row}'] = intro_seconds
        ws[f'G{current_row}'] = host
        ws[f'H{current_row}'] = category
        ws[f'I{current_row}'] = col_count
        ws[f'J{current_row}'] = year
        ws[f'K{current_row}'] = ''  # 待AI填充
        ws[f'L{current_row}'] = ''  # 待AI填充
        
        print(f'写入合集: {col_data["series_title"]}, 首集: {first_video["filename"]}')
        
        # 合并列并设置样式
        merge_cols = ['A', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']
        for mcol in merge_cols:
            ws.merge_cells(f'{mcol}{start_row}:{mcol}{end_row}')
            cell = ws[f'{mcol}{start_row}']
            cell.font = red_font
            cell.alignment = center_align
        
        # 边框
        col_map = {'A':1, 'B':2, 'C':3, 'D':4, 'E':5, 'F':6, 'G':7, 'H':8, 'I':9, 'J':10, 'K':11, 'L':12}
        for mcol in merge_cols:
            col_idx = col_map[mcol]
            apply_border_to_range(ws, start_row, end_row, [col_idx])
        
        # B,C列样式
        ws[f'B{current_row}'].font = red_font
        ws[f'B{current_row}'].alignment = center_align
        apply_border_to_cell(ws[f'B{current_row}'])
        ws[f'C{current_row}'].font = red_font
        ws[f'C{current_row}'].alignment = center_align
        apply_border_to_cell(ws[f'C{current_row}'])
        
        apply_border_to_range(ws, start_row, end_row, [2, 3])
        
        current_row += 1
        
        # 写入子视频
        for video in videos[1:]:
            ws[f'B{current_row}'] = video['filename']
            ws[f'C{current_row}'] = video['duration']
            
            ws[f'B{current_row}'].font = red_font
            ws[f'B{current_row}'].alignment = center_align
            apply_border_to_cell(ws[f'B{current_row}'])
            ws[f'C{current_row}'].font = red_font
            ws[f'C{current_row}'].alignment = center_align
            apply_border_to_cell(ws[f'C{current_row}'])
            
            current_row += 1
    
    # 保存
    wb.save(output_file)
    print(f'\nExcel已生成: {output_file}')
    print(f'总计: {total_videos}个视频, {total_seconds}秒 = {hours}小时{minutes}分')
    print(f'减片头: {total_no_intro}秒 = {hours_no_intro}小时{minutes_no_intro}分')
    
    return output_file

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python generate_excel_from_json.py <输入JSON文件> [输出Excel文件]")
        print("")
        print("示例:")
        print('  python generate_excel_from_json.py "D:\\videos.json"')
        print('  python generate_excel_from_json.py "D:\\videos.json" "D:\\output.xlsx"')
        print("")
        print("可选参数:")
        print("  --host 主播名称（默认: 波波）")
        print("  --category 类别（默认: 端游）")
        print("  --year 年份（默认: 2026）")
        print("  --intro 片头时长秒（默认: 600）")
        return
    
    json_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    # 解析可选参数
    host = "波波"
    category = "端游"
    year = 2026
    intro_duration = 600
    
    for i, arg in enumerate(sys.argv):
        if arg == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
        elif arg == "--category" and i + 1 < len(sys.argv):
            category = sys.argv[i + 1]
        elif arg == "--year" and i + 1 < len(sys.argv):
            year = int(sys.argv[i + 1])
        elif arg == "--intro" and i + 1 < len(sys.argv):
            intro_duration = int(sys.argv[i + 1])
    
    if not os.path.exists(json_file):
        print(f"JSON文件不存在: {json_file}")
        return
    
    generate_excel_from_json(json_file, output_file, host, category, year, intro_duration)

if __name__ == "__main__":
    main()