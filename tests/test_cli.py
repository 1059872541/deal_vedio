# -*- coding: utf-8 -*-
"""vedio/cli.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - 用 `main(argv)` 直接驱动，不启子进程
    - 捕获 stdout / stderr 断言
    - 重点守两条不变量：① 动词不收路径 ② 错误带 code 方便 agent 分支
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import cli, context  # noqa: E402


RULES = """\
game: 我的世界
batch: 2026-12
collections: 2
duration:
  material_per_collection: 1200
  episode_body: 60
  episode_count: 20
  segment_tolerance: 3
meta:
  host: 波波
"""

MANIFEST = """\
drafts:
  合集一: "MC-合集一"
templates:
  intro_mapping: {}
  outro: null
"""


def build(tmp: Path) -> Path:
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text(MANIFEST, encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in ("合集一", "合集二"):
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)
    return root


class CliCase(unittest.TestCase):
    """用临时工作区跑 CLI。

    CLI 内部走 `Project.open(...)` 读 conf/本机.yaml —— 为了让测试不依赖
    真实机器配置，这里直接改 module 级函数的行为不现实，所以改成
    monkeypatch `context.Project.open` 的 workspace。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.root = build(self.tmp)

        # 把 workspace.root 指向临时目录：构造一个 LocalConfig 直接喂给 Project
        self._orig_local_load = context.LocalConfig.load
        context.LocalConfig.load = classmethod(   # type: ignore[assignment]
            lambda cls, path=None: cls.from_dict({"workspace": {"root": str(self.tmp)}})
        )
        self.addCleanup(lambda: setattr(context.LocalConfig, "load", self._orig_local_load))

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()


# ─────────────────────────── 用法与错误 ───────────────────────────

class TestUsage(CliCase):
    def test_no_verb_exits_usage(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_game_exits_usage(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["paths", "--batch", "2026-12"])
        self.assertEqual(ctx.exception.code, 2)

    def test_parser_has_no_path_argument(self):
        """不变量：任何动词都不接受路径参数"""
        parser = cli.build_parser()
        text = parser.format_help()
        self.assertNotIn("--path", text)
        self.assertNotIn("--dir", text)

    def test_unknown_batch_returns_error_with_code(self):
        code, out, err = self.run_cli("paths", "--game", "我的世界", "--batch", "2099-01", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "batch_not_found")
        self.assertIn("hint", payload)

    def test_collection_not_found_has_available(self):
        code, out, err = self.run_cli(
            "paths", "--game", "我的世界", "--batch", "2026-12",
            "--collection", "合集九", "--json",
        )
        self.assertEqual(code, cli.EXIT_FAIL)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "collection_not_found")
        self.assertEqual(payload["available"], ["合集一", "合集二"])


# ─────────────────────────── paths ───────────────────────────

class TestPaths(CliCase):
    def test_batch_json(self):
        code, out, err = self.run_cli("paths", "--game", "我的世界", "--batch", "2026-12", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["game"], "我的世界")
        self.assertEqual(payload["collections"], ["合集一", "合集二"])
        self.assertTrue(payload["batch_dir"].endswith("我的世界-2026-12"))
        self.assertEqual(len(payload["collections_detail"]), 2)

    def test_collection_json(self):
        code, out, err = self.run_cli(
            "paths", "--game", "我的世界", "--batch", "2026-12",
            "--collection", "合集一", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["collection"], "合集一")
        self.assertEqual(payload["draft"], "MC-合集一")
        self.assertTrue(payload["material"].endswith("素材"))

    def test_batch_human_readable(self):
        code, out, err = self.run_cli("paths", "--game", "我的世界", "--batch", "2026-12")
        self.assertEqual(code, 0)
        self.assertIn("我的世界-2026-12", out)
        self.assertIn("合集一、合集二", out)
        self.assertIn("intro_dir", out)

    def test_collection_human_readable(self):
        code, out, err = self.run_cli(
            "paths", "--game", "我的世界", "--batch", "2026-12", "--collection", "合集一")
        self.assertEqual(code, 0)
        self.assertIn("合集一", out)
        self.assertIn("MC-合集一", out)


# ─────────────────────────── status ───────────────────────────

class TestStatus(CliCase):
    def test_json_shape(self):
        code, out, err = self.run_cli("status", "--game", "我的世界", "--batch", "2026-12", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["collection_count"], 2)
        self.assertEqual(payload["episode_total"], 40)
        self.assertEqual(payload["done"], 0)
        self.assertIn("stage", payload["collections"][0])

    def test_human_table(self):
        code, out, err = self.run_cli("status", "--game", "我的世界", "--batch", "2026-12")
        self.assertEqual(code, 0)
        self.assertIn("📊", out)
        for col in ("素材", "剪辑", "字幕", "导出", "拼接", "命名", "台账"):
            self.assertIn(col, out)
        self.assertIn("下一步", out)

    def test_collections_filter(self):
        code, out, err = self.run_cli(
            "status", "--game", "我的世界", "--batch", "2026-12",
            "--collections", "合集二", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual([c["collection"] for c in payload["collections"]], ["合集二"])

    def test_bad_collection_in_filter(self):
        code, out, err = self.run_cli(
            "status", "--game", "我的世界", "--batch", "2026-12",
            "--collections", "合集九", "--json",
        )
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(err)["error"], "collection_not_found")


class TestHelpers(unittest.TestCase):
    def test_split_list(self):
        self.assertIsNone(cli._split_list(None))
        self.assertIsNone(cli._split_list(""))
        self.assertEqual(cli._split_list("合集一"), ["合集一"])
        self.assertEqual(cli._split_list(" 合集一 , 合集二 "), ["合集一", "合集二"])
        self.assertEqual(cli._split_list("合集一,, "), ["合集一"])


if __name__ == "__main__":
    unittest.main()
