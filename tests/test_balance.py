# -*- coding: utf-8 -*-
"""
balance.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

特点：
    - 不需要 ffmpeg：时长探测通过 env.probe 注入假函数
    - 不需要 conf/本机.yaml：Env 直接接收配置字典
    - 不碰真实视频：全部在临时目录里造占位文件
    - 不走 main()：直接调 cmd_check / cmd_move，避免重新加载真实配置
      （CLI 参数契约单独用 build_parser 测）
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from util import balance  # noqa: E402


# ─────────────────────────── 测试脚手架 ───────────────────────────

class BatchFixture:
    """在临时目录里造一个批次，可指定每个合集的文件与时长"""

    def __init__(self, tmp: Path, target: int = 480, tol: float = 3):
        self.root = tmp
        self.target = target
        self.tol = tol
        self.batch = tmp / "我的世界-2026-11"
        (self.batch / "合集").mkdir(parents=True)
        (self.batch / "game.yaml").write_text(
            "game: 我的世界\nbatch: 2026-11\n"
            f"duration:\n  material_per_collection: {target}\n"
            f"  segment_tolerance: {tol}\n",
            encoding="utf-8",
        )
        self.local = {"workspace": {"root": str(tmp)},
                      "tool": {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}}
        self.durations: dict[str, float] = {}       # 绝对路径字符串 -> 秒

    # --- 造数据 ---
    def add_collection(self, name: str) -> Path:
        col = self.batch / "合集" / name
        (col / "素材").mkdir(parents=True, exist_ok=True)
        return col

    def add_file(self, collection: str, filename: str, seconds: float) -> Path:
        col = self.batch / "合集" / collection
        (col / "素材").mkdir(parents=True, exist_ok=True)
        p = col / "素材" / filename
        p.write_bytes(b"x")          # 占位内容，测试不真的解码
        self.durations[str(p)] = seconds
        return p

    def env(self) -> "balance.Env":
        e = balance.Env("我的世界", "2026-11", self.local)
        e.probe = lambda p: self.durations.get(str(Path(p)), -1.0)
        return e

    def files_of(self, collection: str) -> list[str]:
        d = self.batch / "合集" / collection / "素材"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fx = BatchFixture(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def capture(fn, *a, **kw):
        """跑一个函数，返回 (返回值, stdout, stderr)"""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rv = fn(*a, **kw)
        return rv, out.getvalue(), err.getvalue()


# ─────────────────────────── find_cut ───────────────────────────

class TestFindCut(unittest.TestCase):
    @staticmethod
    def f(name, sec):
        return (Path(name), sec)

    def test_cut_inside_second_file(self):
        pairs = [self.f("a.mkv", 250), self.f("b.mkv", 250)]
        f, at = balance.find_cut(pairs, 480)
        self.assertEqual(f.name, "b.mkv")
        self.assertAlmostEqual(at, 230.0)

    def test_cut_inside_first_file(self):
        pairs = [self.f("a.mkv", 600), self.f("b.mkv", 100)]
        f, at = balance.find_cut(pairs, 480)
        self.assertEqual(f.name, "a.mkv")
        self.assertAlmostEqual(at, 480.0)

    def test_exact_boundary_cuts_at_next_file_start(self):
        # 目标恰好等于第一个文件长度 → 切在第二个文件开头，避免零长度尾段
        pairs = [self.f("a.mkv", 480), self.f("b.mkv", 100)]
        f, at = balance.find_cut(pairs, 480)
        self.assertEqual(f.name, "b.mkv")
        self.assertAlmostEqual(at, 0.0)

    def test_target_beyond_all_files(self):
        pairs = [self.f("a.mkv", 100), self.f("b.mkv", 100)]
        self.assertEqual(balance.find_cut(pairs, 480), (None, None))

    def test_skips_unknown_durations(self):
        pairs = [self.f("bad.mkv", -1), self.f("a.mkv", 300), self.f("b.mkv", 300)]
        f, at = balance.find_cut(pairs, 400)
        self.assertEqual(f.name, "b.mkv")
        self.assertAlmostEqual(at, 100.0)

    def test_empty(self):
        self.assertEqual(balance.find_cut([], 480), (None, None))


# ─────────────────────────── 其他纯函数 ───────────────────────────

class TestHelpers(unittest.TestCase):
    def test_cn_index(self):
        self.assertEqual(balance.cn_index("合集一"), 1)
        self.assertEqual(balance.cn_index("合集十"), 10)
        self.assertEqual(balance.cn_index("合集十二"), 12)
        self.assertEqual(balance.cn_index("合集九十九"), 99)
        self.assertEqual(balance.cn_index("不是合集"), 0)

    def test_hhmmss(self):
        self.assertEqual(balance.hhmmss(0), "0:00")
        self.assertEqual(balance.hhmmss(59), "0:59")
        self.assertEqual(balance.hhmmss(60), "1:00")
        self.assertEqual(balance.hhmmss(3599), "59:59")
        self.assertEqual(balance.hhmmss(3600), "60:00")

    def test_hhmmss_rounds(self):
        self.assertEqual(balance.hhmmss(59.6), "1:00")


# ─────────────────────────── 文件扫描 ───────────────────────────

class TestMaterialFiles(Base):
    def test_filters_extensions_and_sorts(self):
        self.fx.add_collection("合集一")
        for n in ("b.mkv", "a.mp4", "note.txt", "c.mov"):
            (self.fx.batch / "合集" / "合集一" / "素材" / n).write_bytes(b"")
        got = [p.name for p in balance.material_files(self.fx.batch / "合集" / "合集一")]
        self.assertEqual(got, ["a.mp4", "b.mkv", "c.mov"])

    def test_missing_dir_returns_empty(self):
        self.assertEqual(balance.material_files(self.tmp / "不存在"), [])

    def test_ignores_subdirectories(self):
        col = self.fx.add_collection("合集一")
        (col / "素材" / "子目录").mkdir()
        self.assertEqual(balance.material_files(col), [])


# ─────────────────────────── Env ───────────────────────────

class TestEnv(Base):
    def test_target_and_limit(self):
        env = self.fx.env()
        self.assertEqual(env.target, 480)
        self.assertEqual(env.tol, 3)
        self.assertEqual(env.limit, 483)

    def test_missing_batch_dir_exits(self):
        with self.assertRaises(SystemExit):
            balance.Env("不存在", "2026-01", {"workspace": {"root": str(self.tmp)}})

    def test_missing_target_exits(self):
        (self.fx.batch / "game.yaml").write_text("game: x\nduration: {}\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.fx.env()

    def test_missing_workspace_root_exits(self):
        with self.assertRaises(SystemExit):
            balance.Env("我的世界", "2026-11", {})

    def test_defaults_for_tools(self):
        env = self.fx.env()
        self.assertEqual(env.ffmpeg, "ffmpeg")
        self.assertEqual(env.ffprobe, "ffprobe")


# ─────────────────────────── check ───────────────────────────

class TestCheck(Base):
    def test_rows_report_facts(self):
        self.fx.add_collection("合集一")
        self.fx.add_collection("合集二")
        self.fx.add_file("合集一", "a.mkv", 250)
        self.fx.add_file("合集一", "b.mkv", 250)

        rows = balance.collect_rows(self.fx.env())
        self.assertEqual([r["collection"] for r in rows], ["合集一", "合集二"])

        r0 = rows[0]
        self.assertAlmostEqual(r0["total"], 500.0)
        self.assertAlmostEqual(r0["over"], 20.0)
        self.assertTrue(r0["over_limit"])
        self.assertEqual(r0["cut_file"], "b.mkv")
        self.assertAlmostEqual(r0["cut_at"], 230.0)

        self.assertFalse(rows[1]["over_limit"])
        self.assertIsNone(rows[1]["cut_file"])

    def test_within_tolerance_not_over_limit(self):
        self.fx.add_collection("合集一")
        self.fx.add_file("合集一", "a.mkv", 480)
        self.fx.add_file("合集一", "b.mkv", 2.9)   # 482.9 <= 483
        self.assertFalse(balance.collect_rows(self.fx.env())[0]["over_limit"])

    def test_beyond_tolerance_over_limit(self):
        self.fx.add_collection("合集一")
        self.fx.add_file("合集一", "a.mkv", 480)
        self.fx.add_file("合集一", "b.mkv", 4)     # 484 > 483
        self.assertTrue(balance.collect_rows(self.fx.env())[0]["over_limit"])

    def test_collections_sorted_by_chinese_numeral(self):
        for n in ("合集十", "合集二", "合集一"):
            self.fx.add_collection(n)
        rows = balance.collect_rows(self.fx.env())
        self.assertEqual([r["collection"] for r in rows], ["合集一", "合集二", "合集十"])

    def test_json_shape(self):
        self.fx.add_collection("合集一")
        self.fx.add_file("合集一", "a.mkv", 600)
        code, out, _ = self.capture(balance.cmd_check, self.fx.env(), True)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["target"], 480)
        self.assertEqual(data["tolerance"], 3.0)
        self.assertEqual(data["collections"][0]["collection"], "合集一")
        self.assertEqual(data["collections"][0]["cut_file"], "a.mkv")

    def test_text_output_has_no_advice(self):
        """check 只报事实，不得包含建议性措辞"""
        self.fx.add_collection("合集一")
        self.fx.add_collection("合集二")
        self.fx.add_file("合集一", "a.mkv", 600)
        _, out, _ = self.capture(balance.cmd_check, self.fx.env(), False)
        for banned in ("建议", "要不要", "没地方匀", "无法"):
            self.assertNotIn(banned, out)


# ─────────────────────────── move ───────────────────────────

class TestMove(Base):
    def setUp(self):
        super().setUp()
        self.fx.add_collection("合集一")
        self.fx.add_collection("合集二")
        self.fx.add_file("合集一", "a.mkv", 250)
        self.fx.add_file("合集一", "b.mkv", 250)
        self._real_split = balance.split_copy
        balance.split_copy = self._fake_split

    def tearDown(self):
        balance.split_copy = self._real_split
        super().tearDown()

    @staticmethod
    def _fake_split(ffmpeg, src, cut_at, head, tail):
        Path(tail).write_bytes(b"tail")
        return True

    def move(self, src="合集一", dst="合集二", apply=False):
        return self.capture(balance.cmd_move, self.fx.env(), src, dst, apply)

    # --- 错误路径 ---
    def test_missing_target_collection_returns_2(self):
        code, _, err = self.move(dst="合集九")
        self.assertEqual(code, 2)
        self.assertIn("目标合集不存在", err)

    def test_missing_source_collection_returns_2(self):
        code, _, err = self.move(src="合集九")
        self.assertEqual(code, 2)
        self.assertIn("源合集不存在", err)

    # --- 安全 ---
    def test_dry_run_does_not_touch_files(self):
        before = self.fx.files_of("合集一")
        code, out, _ = self.move()
        self.assertEqual(code, 0)
        self.assertEqual(self.fx.files_of("合集一"), before)
        self.assertEqual(self.fx.files_of("合集二"), [])
        self.assertIn("未执行", out)

    def test_split_failure_keeps_source_untouched(self):
        balance.split_copy = lambda *a, **k: False
        code, _, err = self.move(apply=True)
        self.assertEqual(code, 1)
        self.assertIn("源合集未改动", err)
        self.assertEqual(self.fx.files_of("合集一"), ["a.mkv", "b.mkv"])
        self.assertEqual(self.fx.files_of("合集二"), [])

    # --- 正常路径 ---
    def test_apply_creates_overflow_file_named_by_dst_index(self):
        code, _, _ = self.move(apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.fx.files_of("合集二"), ["2-0.mkv"])

    def test_apply_keeps_head_in_source(self):
        self.move(apply=True)
        self.assertEqual(self.fx.files_of("合集一"), ["a.mkv", "b.mkv"])

    def test_apply_moves_whole_files_after_cut_point(self):
        self.fx.add_file("合集一", "c.mkv", 100)     # 排在 b.mkv 之后
        code, _, _ = self.move(apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.fx.files_of("合集一"), ["a.mkv", "b.mkv"])
        self.assertEqual(self.fx.files_of("合集二"), ["2-0.mkv", "c.mkv"])

    def test_within_target_reports_nothing_to_do(self):
        (self.fx.batch / "合集" / "合集一" / "素材" / "b.mkv").unlink()
        del self.fx.durations[str(self.fx.batch / "合集" / "合集一" / "素材" / "b.mkv")]
        code, out, _ = self.move()
        self.assertEqual(code, 0)
        self.assertIn("无需处理", out)
        self.assertEqual(self.fx.files_of("合集二"), [])

    def test_within_tolerance_not_cut(self):
        (self.fx.batch / "合集" / "合集一" / "素材" / "b.mkv").unlink()
        self.fx.add_file("合集一", "b.mkv", 232)     # 482 <= 483
        code, out, _ = self.move()
        self.assertEqual(code, 0)
        self.assertIn("无需处理", out)

    def test_overflow_suffix_follows_source_extension(self):
        (self.fx.batch / "合集" / "合集一" / "素材" / "b.mkv").unlink()
        self.fx.add_file("合集一", "b.mp4", 250)
        self.move(apply=True)
        self.assertEqual(self.fx.files_of("合集二"), ["2-0.mp4"])


# ─────────────────────────── CLI 契约 ───────────────────────────

class TestCli(unittest.TestCase):
    def test_move_rejects_json_flag(self):
        with self.assertRaises(SystemExit) as cm:
            balance.build_parser().parse_args(
                ["move", "--game", "g", "--batch", "b", "--from", "a", "--to", "b", "--json"])
        self.assertEqual(cm.exception.code, 2)

    def test_move_requires_from_and_to(self):
        for omit in ("from", "to"):
            argv = ["move", "--game", "g", "--batch", "b"]
            if omit != "from":
                argv += ["--from", "合集一"]
            if omit != "to":
                argv += ["--to", "合集二"]
            with self.assertRaises(SystemExit) as cm:
                balance.build_parser().parse_args(argv)
            self.assertEqual(cm.exception.code, 2)

    def test_check_accepts_json(self):
        ns = balance.build_parser().parse_args(
            ["check", "--game", "g", "--batch", "b", "--json"])
        self.assertTrue(ns.json)

    def test_workspace_override_accepted(self):
        ns = balance.build_parser().parse_args(
            ["check", "--game", "g", "--batch", "b", "--workspace", "D:/x"])
        self.assertEqual(ns.workspace, "D:/x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
