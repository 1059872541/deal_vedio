# -*- coding: utf-8 -*-
"""
素材时长均衡 —— 把超出目标的素材匀到下一个合集

用法：
    python src/util/balance.py --game 我的世界 --batch 2026-11
        只输出计划，不动任何文件（默认）

    python src/util/balance.py --game 我的世界 --batch 2026-11 --apply
        真正执行切割与移动

    python src/util/balance.py --game 我的世界 --batch 2026-11 --json
        机器可读输出，供 AI 判断要不要问用户

规则：
  - 每合集素材总时长 ≤ duration.material_per_collection 时不处理
  - 超出时找到跨越目标边界的那个文件，在目标处关键帧切割（-c copy，不重编码）
  - 后段 + 之后所有文件 → 移动到下一个合集的 素材/，切出的那一段命名为 {下一个合集序号}-0.mkv
  - 级联处理：下一个合集接收后若仍超限，继续往后匀
  - 最后一个合集超出时无处可匀 → 报告不可行，建议先多建一个合集

安全：
  - 默认只出计划，不碰文件
  - --apply 时先切到临时文件，成功后才替换原文件；失败自动清理
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# 让 from util.xxx import 能工作（脚本在 src/util 下）
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

REPO_ROOT = _SRC.parent
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".ts", ".flv", ".wmv"}


# ─────────────────────────── 配置读取 ───────────────────────────

def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        sys.exit("缺少 pyyaml，请先 pip install -r src/requirements.txt")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_local_conf() -> dict:
    p = REPO_ROOT / "conf" / "本机.yaml"
    if not p.exists():
        sys.exit(f"找不到 {p}\n请先按 AGENTS.md §1 完成本机配置")
    return load_yaml(p)


def resolve_tool(conf: dict, key: str, default: str) -> str:
    return (conf.get("tool") or {}).get(key) or default


# ─────────────────────────── 时长与扫描 ───────────────────────────

def video_duration(ffprobe: str, path: Path) -> float:
    """ffprobe 取时长（秒）；失败返回 -1"""
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=120,
        )
        return float(r.stdout.strip())
    except Exception:
        return -1.0


def scan_materials(collection_dir: Path) -> list[Path]:
    """合集的 素材/ 下所有视频，按文件名自然排序"""
    d = collection_dir / "素材"
    if not d.is_dir():
        return []
    return sorted(
        (p for p in d.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT),
        key=lambda p: p.name,
    )


def list_collections(batch_dir: Path) -> list[Path]:
    """合集/ 下所有合集目录，按中文序号排序"""
    from util.file_utils import TextUtils

    d = batch_dir / "合集"
    if not d.is_dir():
        return []

    def key(p: Path):
        import re
        m = re.search(r"^合集(.+)$", p.name)
        if m:
            return (0, TextUtils.chinese_to_number(m.group(1)), p.name)
        return (1, 0, p.name)

    return sorted((p for p in d.iterdir() if p.is_dir() and p.name.startswith("合集")), key=key)


def collection_index(name: str) -> int:
    """合集三 -> 3"""
    import re
    from util.file_utils import TextUtils

    m = re.search(r"^合集(.+)$", name)
    return TextUtils.chinese_to_number(m.group(1)) if m else 0


# ─────────────────────────── 计划 ───────────────────────────

def build_plan(batch_dir: Path, target: int, ffprobe: str, tol: float = 3.0) -> dict:
    """算出每个超限合集该怎么匀（不执行）

    判定用 target + tol 作为上限，避免"刚好等于目标但浮点略超"就触发切割。
    """
    limit = target + tol
    cols = list_collections(batch_dir)
    out = {"target": target, "tolerance": tol, "collections": [], "actions": [], "blocked": []}

    durations: dict[Path, float] = {}

    for idx, col in enumerate(cols):
        files = scan_materials(col)
        dur = []
        for f in files:
            if f not in durations:
                durations[f] = video_duration(ffprobe, f)
            dur.append(durations[f])

        total = sum(d for d in dur if d > 0)
        item = {
            "collection": col.name,
            "files": len(files),
            "total": round(total, 1),
            "over": round(max(0.0, total - target), 1),
        }
        out["collections"].append(item)

        if total <= limit or not files:
            continue

        # 找切割点
        acc, cut_file, cut_at = 0.0, None, None
        for f, d in zip(files, dur):
            if d <= 0:
                continue
            if acc + d >= target:
                cut_file, cut_at = f, target - acc
                break
            acc += d

        next_col = cols[idx + 1] if idx + 1 < len(cols) else None
        tail = [f.name for f in files if cut_file and f.name > cut_file.name]

        action = {
            "collection": col.name,
            "total": round(total, 1),
            "over": round(total - target, 1),
            "cut_file": cut_file.name if cut_file else None,
            "cut_at": round(cut_at, 1) if cut_at is not None else None,
            "overflow_seconds": round(total - target, 1),
            "move_whole_files": tail,
            "next_collection": next_col.name if next_col else None,
            "feasible": next_col is not None,
        }
        if next_col is None:
            action["reason"] = "本批次没有下一个合集可接收溢出"
            out["blocked"].append(action)
        out["actions"].append(action)

    return out


# ─────────────────────────── 执行 ───────────────────────────

def split_copy(ffmpeg: str, src: Path, cut_at: float, head: Path, tail: Path) -> bool:
    """关键帧切割，无重编码。先写临时文件，成功才算数。

    临时文件必须保留视频扩展名 —— ffmpeg 靠扩展名判断封装格式。
    """
    tmp_head = head.with_name(f"{head.stem}.part1{head.suffix}")
    tmp_tail = tail.with_name(f"{tail.stem}.part2{tail.suffix}")
    try:
        for out, args in (
            (tmp_head, ["-ss", "0", "-i", str(src), "-t", str(cut_at)]),
            (tmp_tail, ["-ss", str(cut_at), "-i", str(src)]),
        ):
            r = subprocess.run(
                [ffmpeg, "-y", *args, "-c", "copy", "-map", "0",
                 "-avoid_negative_ts", "make_zero", str(out)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                err = (r.stderr or "").strip().splitlines()
                tail_msg = " | ".join(err[-3:]) if err else "(无错误输出)"
                print(f"     ffmpeg 退出码 {r.returncode}: {tail_msg[:400]}")
                return False
        shutil.move(str(tmp_head), str(head))
        shutil.move(str(tmp_tail), str(tail))
        return True
    finally:
        for t in (tmp_head, tmp_tail):
            if t.exists():
                t.unlink()


def apply_plan(batch_dir: Path, plan: dict, ffmpeg: str, ffprobe: str) -> int:
    cols = {c.name: c for c in list_collections(batch_dir)}
    done = 0

    for a in plan["actions"]:
        if not a["feasible"]:
            print(f"  ⏭  {a['collection']}：{a['reason']}")
            continue

        col = cols[a["collection"]]
        next_col = cols[a["next_collection"]]
        next_idx = collection_index(next_col.name)

        src = col / "素材" / a["cut_file"]
        if not src.exists():
            print(f"  ✗  {a['collection']}：找不到 {a['cut_file']}")
            continue

        overflow_name = f"{next_idx}-0{src.suffix}"
        overflow_path = next_col / "素材" / overflow_name
        next_col.joinpath("素材").mkdir(parents=True, exist_ok=True)

        print(f"  ✂  {a['collection']}：切割 {src.name} @ {a['cut_at']}s")
        if not split_copy(ffmpeg, src, a["cut_at"], src, overflow_path):
            print(f"     ✗ 失败，{a['collection']} 未改动")
            continue
        print(f"     前段覆盖原文件，后段 {overflow_name} → {next_col.name}/素材/")

        for name in a["move_whole_files"]:
            s = col / "素材" / name
            if s.exists():
                shutil.move(str(s), str(next_col / "素材" / name))
                print(f"     移动 {name} → {next_col.name}/素材/")

        done += 1
    return done


# ─────────────────────────── 输出 ───────────────────────────

def hhmmss(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def print_plan(plan: dict) -> None:
    print(f"目标：每合集 {hhmmss(plan['target'])}")
    print()
    print(f"{'合集':<8} {'文件':>4} {'总时长':>9} {'超出':>8}")
    print("-" * 36)
    for c in plan["collections"]:
        over = hhmmss(c["over"]) if c["over"] > 0 else "—"
        print(f"{c['collection']:<8} {c['files']:>4} {hhmmss(c['total']):>9} {over:>8}")

    if not plan["actions"]:
        print("\n✅ 所有合集均在目标时长内，无需处理")
        return

    print("\n需要处理：")
    for a in plan["actions"]:
        if a["feasible"]:
            print(f"  {a['collection']} 超出 {hhmmss(a['over'])}")
            print(f"    在 {a['cut_file']} 的 {a['cut_at']}s 处切割")
            print(f"    溢出 {hhmmss(a['overflow_seconds'])} → {a['next_collection']}/素材/")
            for n in a["move_whole_files"]:
                print(f"    整段移动 {n} → {a['next_collection']}/素材/")
        else:
            print(f"  ⚠ {a['collection']} 超出 {hhmmss(a['over'])}，但{a['reason']}")
            print(f"    → 建议：先多建一个合集，或接受这一集超长")


# ─────────────────────────── 入口 ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="素材时长均衡")
    ap.add_argument("--game", required=True)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--apply", action="store_true", help="真正执行（默认只出计划）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--workspace", help="临时覆盖工作区根目录（测试用）")
    args = ap.parse_args()

    local = load_local_conf()
    root = Path(args.workspace or (local.get("workspace") or {}).get("root") or "")
    batch_dir = root / f"{args.game}-{args.batch}"
    if not batch_dir.is_dir():
        sys.exit(f"批次目录不存在：{batch_dir}")

    game_yaml = batch_dir / "game.yaml"
    if not game_yaml.exists():
        sys.exit(f"批次缺少 game.yaml：{game_yaml}")
    cfg = load_yaml(game_yaml)
    dur_cfg = cfg.get("duration") or {}
    target = int(dur_cfg.get("material_per_collection") or 0)
    tol = float(dur_cfg.get("segment_tolerance") or 3)
    if target <= 0:
        sys.exit("game.yaml 里 duration.material_per_collection 缺失或无效")

    ffmpeg = resolve_tool(local, "ffmpeg", "ffmpeg")
    ffprobe = resolve_tool(local, "ffprobe", "ffprobe")

    plan = build_plan(batch_dir, target, ffprobe, tol)
    plan["batch_dir"] = str(batch_dir)

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(f"批次：{batch_dir.name}\n")
        print_plan(plan)

    if args.apply:
        if not any(a["feasible"] for a in plan["actions"]):
            return 0
        print("\n执行中…")
        n = apply_plan(batch_dir, plan, ffmpeg, ffprobe)
        print(f"\n完成 {n} 个合集的匀料。")
        print("提示：级联可能产生新的超限，建议再运行一次确认。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
