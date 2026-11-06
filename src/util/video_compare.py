#!/usr/bin/env python3
"""
视频标题对比脚本 — Video Title Comparison Script

功能：将网盘视频文件名与片单 Excel 中的标题进行逐条精确匹配
      支持定制/非定制格式检测，支持预览抽样

用法：
  python video_compare.py --excel <片单路径> --data <输入JSON文件路径> [--format custom|default]

参数:
  --format custom   定制格式（默认）：文件名以合集名开头，如 "合集名 第一集 标题.mp4"
  --format default  非定制格式：文件名无合集前缀，如 "第一集 标题.mp4"

输入 JSON:
{
  "collections": [
    {
      "name": "波波之我的世界 收集强力变身-上篇",
      "netdisk_files": [
        "波波之我的世界 收集强力变身-上篇 第一集 林中小屋初探.mp4", ...
      ]
    }
  ]
}

输出 JSON:
{
  "summary": { "total_collections":1, "total_videos":20, "matched":20, "mismatched":0,
               "perfect":true, "format_global": { "mode":"custom", "passed":true, "issues":[] } },
  "results": [ { "collection":"...", "total":20, "matched":20, "mismatched":0,
                  "preview":[...3 items], "format_check":{...}, "details":[...] } ]
}
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print(json.dumps({"error": "缺少依赖: openpyxl，请执行 pip install openpyxl"}, ensure_ascii=False))
    sys.exit(1)


# ── 工具函数 ──────────────────────────────────────────────

def parse_episode_title(raw: str) -> dict | None:
    """从 '第X集 标题文字' 中提取集数和标题"""
    m = re.match(r'^(第[一二三四五六七八九十百千]+集)\s+(.+)$', raw)
    if m:
        return {"episode": m.group(1), "title": m.group(2)}
    m2 = re.match(r'^(第\d+集)\s+(.+)$', raw)
    if m2:
        return {"episode": m2.group(1), "title": m2.group(2)}
    return None


# ── Excel 读取 ────────────────────────────────────────────

def find_collection_row(ws, collection_name: str) -> int | None:
    """在 Excel A 列中查找合集名称，返回行号（1-based）"""
    for row in range(1, ws.max_row + 1):
        cell_val = ws.cell(row=row, column=1).value
        if cell_val is not None and str(cell_val).strip() == collection_name:
            return row
    return None


def extract_excel_titles(ws, start_row: int) -> list[dict]:
    """从指定行开始读取 B 列标题，直到下一个 A 列有值或 B 列空为止"""
    titles = []
    row = start_row
    while row <= ws.max_row:
        if row != start_row and ws.cell(row=row, column=1).value is not None:
            break
        b_val = ws.cell(row=row, column=2).value
        if b_val is None:
            break
        raw = str(b_val).strip()
        if not raw:
            row += 1
            continue
        parsed = parse_episode_title(raw)
        titles.append({
            "row": row,
            "raw": raw,
            "episode": parsed["episode"] if parsed else None,
            "title": parsed["title"] if parsed else raw,
        })
        row += 1
    return titles


# ── 网盘文件名解析 ────────────────────────────────────────

def extract_netdisk_titles_custom(collection_name: str, filenames: list[str]) -> list[dict]:
    """定制格式：文件名以合集名开头"""
    results = []
    prefix = collection_name + " "
    for fname in filenames:
        name = fname
        if "." in name:
            name = name[: name.rfind(".")]
        if name.startswith(prefix):
            ep_part = name[len(prefix):]
        elif name.startswith(collection_name):
            ep_part = name[len(collection_name):].lstrip()
        else:
            ep_part = name  # 无法剥离前缀，原样保留
        parsed = parse_episode_title(ep_part)
        results.append({
            "raw_filename": fname,
            "episode_part": ep_part,
            "episode": parsed["episode"] if parsed else None,
            "title": parsed["title"] if parsed else ep_part,
        })
    return results


def extract_netdisk_titles_default(filenames: list[str]) -> list[dict]:
    """非定制格式：文件名直接是 '第X集 标题.mp4'，无合集前缀"""
    results = []
    for fname in filenames:
        name = fname
        if "." in name:
            name = name[: name.rfind(".")]
        parsed = parse_episode_title(name)
        results.append({
            "raw_filename": fname,
            "episode_part": name,
            "episode": parsed["episode"] if parsed else None,
            "title": parsed["title"] if parsed else name,
        })
    return results


# ── 格式校验 ──────────────────────────────────────────────

def validate_format_custom(collection_name: str, nd_titles: list[dict]) -> dict:
    """校验定制格式：文件名是否以合集名开头、集数是否连续无跳缺"""
    prefix = collection_name + " "
    issues = []
    valid_count = 0
    for item in nd_titles:
        fn = item["raw_filename"]
        name = fn if "." not in fn else fn[: fn.rfind(".")]
        if not name.startswith(prefix) and not name.startswith(collection_name):
            issues.append(f"文件名不以合集名开头: {fn}")
        else:
            valid_count += 1
        if item["episode"] is None:
            issues.append(f"无法解析集数: {fn}")
    return {
        "mode": "custom",
        "total": len(nd_titles),
        "valid": valid_count,
        "invalid": len(nd_titles) - valid_count,
        "issues": issues,
        "passed": len(issues) == 0,
    }


def validate_format_default(nd_titles: list[dict]) -> dict:
    """校验非定制格式：文件名是否可解析为 '第X集 标题'"""
    issues = []
    valid_count = 0
    for item in nd_titles:
        if item["episode"] is None:
            issues.append(f"无法解析集数: {item['raw_filename']}")
        else:
            valid_count += 1
    return {
        "mode": "default",
        "total": len(nd_titles),
        "valid": valid_count,
        "invalid": len(nd_titles) - valid_count,
        "issues": issues,
        "passed": len(issues) == 0,
    }


# ── 对比逻辑 ──────────────────────────────────────────────

def compare_collection(
    collection_name: str,
    netdisk_files: list[str],
    excel_titles: list[dict],
    format_mode: str,
) -> dict:
    """对比一个合集，返回结果（含格式校验和预览抽样）"""

    # 根据格式模式解析网盘文件名
    if format_mode == "custom":
        nd_titles = extract_netdisk_titles_custom(collection_name, netdisk_files)
        format_check = validate_format_custom(collection_name, nd_titles)
    else:
        nd_titles = extract_netdisk_titles_default(netdisk_files)
        format_check = validate_format_default(nd_titles)

    # 逐条对比
    details = []
    max_count = max(len(nd_titles), len(excel_titles))
    matched = 0
    mismatched = 0

    for i in range(max_count):
        nd = nd_titles[i] if i < len(nd_titles) else None
        ex = excel_titles[i] if i < len(excel_titles) else None
        nd_val = nd["episode_part"] if nd else "(网盘缺失)"
        ex_val = ex["raw"] if ex else "(片单缺失)"
        is_match = nd_val == ex_val
        if is_match:
            matched += 1
        else:
            mismatched += 1
        details.append({
            "index": i + 1,
            "netdisk_episode_part": nd_val,
            "excel_title": ex_val,
            "match": is_match,
        })

    # 预览抽样：取前3条（含不匹配项，优先展示差异）
    preview_pool = [d for d in details if not d["match"]] + [d for d in details if d["match"]]
    preview = preview_pool[:3]

    return {
        "collection": collection_name,
        "total": max_count,
        "netdisk_count": len(nd_titles),
        "excel_count": len(excel_titles),
        "matched": matched,
        "mismatched": mismatched,
        "format_check": format_check,
        "preview": preview,
        "details": details,
    }


# ── 主入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="网盘视频 vs Excel 片单标题对比")
    parser.add_argument("--excel", required=True, help="片单 Excel 文件路径")
    parser.add_argument("--data", required=True, help="输入 JSON 数据文件路径")
    parser.add_argument("--format", choices=["custom", "default"], default="custom",
                        help="网盘文件命名格式: custom=定制(合集名前缀), default=非定制(无前缀)")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    data_path = Path(args.data)

    if not excel_path.exists():
        print(json.dumps({"error": f"Excel 文件不存在: {excel_path}"}, ensure_ascii=False))
        sys.exit(1)
    if not data_path.exists():
        print(json.dumps({"error": f"数据文件不存在: {data_path}"}, ensure_ascii=False))
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    collections_input = input_data.get("collections", [])
    if not collections_input:
        print(json.dumps({"error": "输入数据中 collections 为空"}, ensure_ascii=False))
        sys.exit(1)

    try:
        wb = openpyxl.load_workbook(excel_path)
        ws = wb.active
    except Exception as e:
        print(json.dumps({"error": f"无法打开 Excel 文件: {e}"}, ensure_ascii=False))
        sys.exit(1)

    results = []
    total_videos = 0
    total_matched = 0
    global_format_issues = []

    for col_data in collections_input:
        name = col_data["name"]
        nd_files = col_data.get("netdisk_files", [])

        start_row = find_collection_row(ws, name)
        if start_row is None:
            results.append({
                "collection": name,
                "error": f"在 Excel 中未找到合集 '{name}'",
                "total": len(nd_files),
                "matched": 0,
                "mismatched": len(nd_files),
                "format_check": {"mode": args.format, "error": "合集未找到，跳过格式校验"},
                "preview": [],
                "details": [{"index": i+1, "netdisk_episode_part": f, "excel_title": "(未找到合集)", "match": False}
                           for i, f in enumerate(nd_files)],
            })
            total_videos += len(nd_files)
            continue

        excel_titles_list = extract_excel_titles(ws, start_row)
        if not excel_titles_list:
            results.append({
                "collection": name,
                "error": f"在 Excel 行 {start_row} 未找到标题数据",
                "total": len(nd_files),
                "matched": 0,
                "mismatched": len(nd_files),
                "format_check": {"mode": args.format, "error": "Excel 无数据，跳过格式校验"},
                "preview": [],
                "details": [{"index": i+1, "netdisk_episode_part": f, "excel_title": "(无数据)", "match": False}
                           for i, f in enumerate(nd_files)],
            })
            total_videos += len(nd_files)
            continue

        result = compare_collection(name, nd_files, excel_titles_list, args.format)
        results.append(result)
        total_videos += result["total"]
        total_matched += result["matched"]
        if not result["format_check"].get("passed", True):
            global_format_issues.extend(result["format_check"].get("issues", []))

    wb.close()

    perfect = all(r.get("mismatched", 0) == 0 for r in results)
    format_all_passed = all(r.get("format_check", {}).get("passed", True) for r in results)

    output = {
        "summary": {
            "total_collections": len(collections_input),
            "total_videos": total_videos,
            "matched": total_matched,
            "mismatched": total_videos - total_matched,
            "perfect": perfect and format_all_passed and all("error" not in r for r in results),
            "format_global": {
                "mode": args.format,
                "passed": format_all_passed,
                "issue_count": len(global_format_issues),
            },
        },
        "results": results,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
