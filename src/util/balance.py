# -*- coding: utf-8 -*-
"""
素材时长均衡 —— 只提供原子能力，不做决策

两个子命令：

    # 1. 只报事实：每个合集的素材总时长 / 目标 / 超出
    python src/util/balance.py check --game 我的世界 --batch 2026-11

    # 2. 原子操作：把「合集一」超出目标的部分切出来，移到「合集二」
    python src/util/balance.py move  --game 我的世界 --batch 2026-11 \
                                     --from 合集一 --to 合集二
    # 加 --apply 才真正执行；不加只打印将要做什么

设计原则：
    脚本不判断"该不该匀"、"有没有下一个合集"、"要不要级联"。
    这些是决策，属于调用方（AI / 人）。脚本只做被明确要求的那一件事。

    后果：--to 指定的合集不存在时，脚本直接报错退出（不猜、不建议）。

可测性：
    配置加载（load_local_conf / Env 构造）与时长探测（Env.probe）都可注入，
    单元测试不需要 ffmpeg，也不需要真实的 conf/本机.yaml。
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


# ─────────────────────────── 配置加载 ───────────────────────────

def _yaml():
    try:
        import yaml
    except ImportError:
        sys.exit("缺少 pyyaml，请先 pip install -r src/requirements.txt")
    return yaml


def load_yaml(path: Path) -> dict:
    return _yaml().safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_local_conf(path: Path | None = None) -> dict:
    """读 conf/本机.yaml（机器相关配置）"""
    p = Path(path) if path else REPO_ROOT / "conf" / "本机.yaml"
    if not p.exists():
        sys.exit(f"缺少 {p}（见 AGENTS.md §1）")
    return load_yaml(p)


# ─────────────────────────── 时长探测 ───────────────────────────

def duration(ffprobe: str, path: Path) -> float:
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


# ─────────────────────────── 批次上下文 ───────────────────────────

class Env:
    """批次上下文：路径 + 配置 + 时长探测（probe 可替换，便于测试）"""

    def __init__(self, game: str, batch: str, local: dict,
                 workspace_override: str | None = None):
        root = Path(workspace_override or (local.get("workspace") or {}).get("root") or "")
        if not str(root):
            sys.exit("conf/本机.yaml 缺少 workspace.root")

        self.batch_dir = root / f"{game}-{batch}"
        if not self.batch_dir.is_dir():
            sys.exit(f"批次目录不存在：{self.batch_dir}")

        gy = self.batch_dir / "game.yaml"
        if not gy.exists():
            sys.exit(f"批次缺少 game.yaml：{gy}")
        cfg = load_yaml(gy)

        dur = cfg.get("duration") or {}
        self.target = int(dur.get("material_per_collection") or 0)
        self.tol = float(dur.get("segment_tolerance") or 3)
        if self.target <= 0:
            sys.exit("game.yaml 缺少 duration.material_per_collection")

        tool = local.get("tool") or {}
        self.ffmpeg = tool.get("ffmpeg") or "ffmpeg"
        self.ffprobe = tool.get("ffprobe") or "ffprobe"

        # 时长探测：默认走 ffprobe，测试可替换为假函数
        self.probe = lambda p: duration(self.ffprobe, p)

    @property
    def limit(self) -> float:
        return self.target + self.tol


# ─────────────────────────── 文件与计算 ───────────────────────────

def material_files(collection_dir: Path) -> list[Path]:
    """合集的 素材/ 下所有视频，按文件名排序"""
    d = Path(collection_dir) / "素材"
    if not d.is_dir():
        return []
    return sorted(
        (p for p in d.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT),
        key=lambda p: p.name,
    )


def material_total(env: "Env", collection_dir: Path) -> tuple[float, list[tuple[Path, float]]]:
    pairs = [(f, env.probe(f)) for f in material_files(collection_dir)]
    return sum(d for _, d in pairs if d > 0), pairs


def find_cut(pairs: list[tuple[Path, float]], target: float):
    """返回 (跨越目标的那个文件, 在该文件内的切割秒数)

    用 `>` 而不是 `>=`：目标刚好等于某文件结尾时，应切在**下一个文件的开头**，
    否则会切出零长度的尾段。目标落在所有文件之外时返回 (None, None)。
    """
    acc = 0.0
    for f, d in pairs:
        if d <= 0:
            continue
        if acc + d > target:
            return f, target - acc
        acc += d
    return None, None


def cn_index(name: str) -> int:
    """合集三 -> 3"""
    import re
    from util.file_utils import TextUtils

    m = re.search(r"^合集(.+)$", name)
    return TextUtils.chinese_to_number(m.group(1)) if m else 0


def hhmmss(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def list_collections(batch_dir: Path) -> list[Path]:
    d = Path(batch_dir) / "合集"
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if p.is_dir() and p.name.startswith("合集")),
                  key=lambda p: cn_index(p.name))


# ─────────────────────────── 切割 ───────────────────────────

def split_copy(ffmpeg: str, src: Path, cut_at: float, head: Path, tail: Path) -> bool:
    """关键帧切割，无重编码。临时文件必须保留视频扩展名（ffmpeg 靠扩展名判断封装）。"""
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
                print(f"ffmpeg 退出码 {r.returncode}: " + (" | ".join(err[-3:])[:400] or "(无输出)"))
                return False
        shutil.move(str(tmp_head), str(head))
        shutil.move(str(tmp_tail), str(tail))
        return True
    finally:
        for t in (tmp_head, tmp_tail):
            if t.exists():
                t.unlink()


# ─────────────────────────── 子命令 ───────────────────────────

def collect_rows(env: "Env") -> list[dict]:
    """纯数据：每个合集的事实（供 check 输出 / 测试断言）"""
    rows = []
    for d in list_collections(env.batch_dir):
        total, pairs = material_total(env, d)
        over = round(max(0.0, total - env.target), 1)
        cut_file, cut_at = find_cut(pairs, env.target) if over > 0 else (None, None)
        rows.append({
            "collection": d.name,
            "files": len(pairs),
            "total": round(total, 1),
            "target": env.target,
            "over": over,
            "over_limit": total > env.limit,
            "cut_file": cut_file.name if cut_file else None,
            "cut_at": round(cut_at, 1) if cut_at is not None else None,
        })
    return rows


def cmd_check(env: "Env", as_json: bool) -> int:
    rows = collect_rows(env)

    if as_json:
        print(json.dumps({"batch": env.batch_dir.name, "target": env.target,
                          "tolerance": env.tol, "collections": rows},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"批次 {env.batch_dir.name}   目标 {hhmmss(env.target)}（容差 {env.tol:g}s）\n")
    print(f"{'合集':<8}{'文件':>5}{'总时长':>10}{'超出':>9}")
    print("-" * 34)
    for r in rows:
        over = hhmmss(r["over"]) if r["over"] > 0 else "—"
        print(f"{r['collection']:<8}{r['files']:>5}{hhmmss(r['total']):>10}{over:>9}")
    return 0


def cmd_move(env: "Env", src_name: str, dst_name: str, apply: bool) -> int:
    src_dir = env.batch_dir / "合集" / src_name
    if not src_dir.is_dir():
        print(f"错误：源合集不存在 {src_dir}", file=sys.stderr)
        return 2
    if not (env.batch_dir / "合集" / dst_name).is_dir():
        print(f"错误：目标合集不存在 {env.batch_dir / '合集' / dst_name}", file=sys.stderr)
        return 2

    total, pairs = material_total(env, src_dir)
    if total <= env.limit:
        print(f"{src_name} 总时长 {hhmmss(total)}，未超出 {hhmmss(env.target)}，无需处理")
        return 0

    cut_file, cut_at = find_cut(pairs, env.target)
    if cut_file is None:
        print(f"错误：{src_name} 找不到切割点", file=sys.stderr)
        return 2

    names = [f for f, _ in pairs]
    # 只保留文件名：pairs 里是绝对路径，直接用会把 dst_dir/"素材" 覆盖掉
    whole = [p.name for p in names[names.index(cut_file) + 1:]]
    overflow = round(total - env.target, 1)
    dst_file = f"{cn_index(dst_name)}-0{cut_file.suffix}"
    dst_dir = env.batch_dir / "合集" / dst_name

    print(f"{src_name}  总时长 {hhmmss(total)}  超出 {hhmmss(overflow)}")
    print(f"  切割 {cut_file.name} @ {cut_at:.1f}s")
    print(f"  溢出段 → {dst_name}/素材/{dst_file}")
    for n in whole:
        print(f"  整段移动 {n} → {dst_name}/素材/")

    if not apply:
        print("\n（未执行。加 --apply 才真正切割与移动）")
        return 0

    print("\n执行中…")
    (dst_dir / "素材").mkdir(parents=True, exist_ok=True)
    if not split_copy(env.ffmpeg, cut_file, cut_at, cut_file, dst_dir / "素材" / dst_file):
        print("失败：源合集未改动", file=sys.stderr)
        return 1
    print(f"  ✓ 前段覆盖原文件，后段 → {dst_file}")

    for n in whole:
        s = src_dir / "素材" / n
        if s.exists():
            shutil.move(str(s), str(dst_dir / "素材" / n))
            print(f"  ✓ 移动 {n}")

    print("完成。建议重新 check 一次确认结果。")
    return 0


# ─────────────────────────── 入口 ───────────────────────────

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="素材时长均衡（原子能力）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, hlp in (("check", "只报事实"), ("move", "切走指定合集超出目标的部分")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--game", required=True)
        p.add_argument("--batch", required=True)
        p.add_argument("--workspace", help="临时覆盖工作区根目录（测试用）")
        if name == "check":
            p.add_argument("--json", action="store_true", help="机器可读输出")
        else:
            p.add_argument("--from", dest="src", required=True, help="源合集，如 合集一")
            p.add_argument("--to", dest="dst", required=True, help="接收溢出的合集，如 合集二")
            p.add_argument("--apply", action="store_true", help="真正执行")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = Env(args.game, args.batch, load_local_conf(), args.workspace)

    if args.cmd == "check":
        return cmd_check(env, args.json)
    return cmd_move(env, args.src, args.dst, args.apply)


if __name__ == "__main__":
    sys.exit(main())
