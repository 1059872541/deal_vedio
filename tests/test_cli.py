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


# ─────────────────────────── 其余动词的接线 ───────────────────────────

class TestVerbDispatch(CliCase):
    """每个动词至少过一遍 CLI 分发层。

    阶段函数自己的行为由各自的测试覆盖；这里只验**接线**：
    参数名对不对、退出码对不对、错误码能不能取到。
    接线错了（比如 argparse 属性名拼错）阶段测试是抓不到的。
    """

    def setUp(self):
        super().setUp()
        # 给 series / rename 一个可用的标题文件
        (self.root / "标题.md").write_text(
            "# 我的世界系列视频标题列表\n公共前缀:波波之我的世界\n", encoding="utf-8")
        # 默认不登记草稿：让 export 的行为确定（不去碰剪映）
        (self.root / "合集清单.yaml").write_text(
            "drafts: {}\ntemplates:\n  intro_mapping: {}\n  outro: null\n", encoding="utf-8")

    def base(self):
        return ["--game", "我的世界", "--batch", "2026-12"]

    def test_init_dry_run(self):
        code, out, err = self.run_cli("init", "--game", "我的世界", "--batch", "2026-13",
                                      "--collections", "2", "--host", "波波", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("将要创建", out)
        self.assertIn("我的世界-2026-13", out)
        self.assertFalse((self.tmp / "我的世界-2026-13").exists(), "dry-run 不能写盘")

    def test_init_creates_and_reports(self):
        code, out, err = self.run_cli("init", "--game", "我的世界", "--batch", "2026-13",
                                      "--collections", "1", "--host", "波波", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["collections"], 1)
        self.assertTrue((self.tmp / "我的世界-2026-13" / "game.yaml").is_file())

    def test_init_existing_batch_reports_error(self):
        code, out, err = self.run_cli("init", *self.base(), "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(err)["error"], "batch_exists")

    def test_init_bad_set(self):
        code, out, err = self.run_cli("init", "--game", "我的世界", "--batch", "2026-14",
                                      "--set", "没有等号", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(err)["error"], "bad_override")

    def test_export_without_draft_registration(self):
        """草稿没登记 → 直接报错，不该去碰剪映"""
        code, out, err = self.run_cli("export", *self.base(), "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual({r["error"] for r in payload["results"]}, {"draft_not_found"})

    def test_subtitle_without_files(self):
        code, out, err = self.run_cli("subtitle", *self.base(), "--collections", "合集一", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        payload = json.loads(out)
        self.assertEqual(payload["results"][0]["step"], "number")
        self.assertEqual(payload["results"][0]["error"], "source_txt_missing")

    def test_splice_without_long_video(self):
        code, out, err = self.run_cli("splice", *self.base(), "--collections", "合集一", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(out)["results"][0]["error"], "template_missing")

    def test_rename_without_titles_section(self):
        code, out, err = self.run_cli("rename", *self.base(), "--collections", "合集一", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(out)["results"][0]["error"], "titles_missing")

    def test_ledger_without_final_video(self):
        code, out, err = self.run_cli("ledger", *self.base(), "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(out)["error"], "no_data")

    def test_series_writes_subtitle(self):
        code, out, err = self.run_cli("series", *self.base(),
                                      "--groups", "合集一=测试篇", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["assignments"], {"合集一": "测试篇"})
        text = (self.root / "标题.md").read_text(encoding="utf-8")
        self.assertIn("#### 合集一:测试篇", text)

    def test_series_bad_groups(self):
        code, out, err = self.run_cli("series", *self.base(), "--groups", "缺等号", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(out)["error"], "bad_spec")

    def test_run_with_unknown_step(self):
        code, out, err = self.run_cli("run", *self.base(), "--steps", "乱写", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        self.assertEqual(json.loads(err)["error"], "bad_step")

    def test_run_reports_failure_per_collection(self):
        code, out, err = self.run_cli("run", *self.base(), "--steps", "number", "--json")
        self.assertEqual(code, cli.EXIT_FAIL)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual(len(payload["failed"]), 2)     # 两个合集都失败

    def test_json_stays_parseable_when_stage_prints(self):
        """阶段内部 print 进度（旧控制器/旧 agent 都这么干）时，stdout 必须还是纯 JSON"""
        from unittest import mock
        from vedio.stages import ledger as L

        class FakeResult:
            ok = True
            status = "done"
            path = None

            def as_dict(self):
                return {"status": "done", "path": None, "message": "ok", "rows": 3}

        def noisy(*args, **kwargs):
            print("这行是阶段内部的进度输出，不该进 stdout")
            return FakeResult()

        with mock.patch.object(L, "build_ledger", noisy):
            code, out, err = self.run_cli("ledger", *self.base(), "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)                     # 能解析才算合格
        self.assertEqual(payload["status"], "done")
        self.assertIn("进度输出", err)                 # 被赶到 stderr 了

    def test_logs_empty(self):
        code, out, err = self.run_cli("logs", *self.base(), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 0)
        self.assertIn("log_dir", payload)

    def test_logs_lists_and_tails(self):
        log_dir = self.root / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "agent-subtitle-合集一-20260101-000000.log").write_text(
            "第一行\n最后一行\n", encoding="utf-8")
        code, out, err = self.run_cli("logs", *self.base(), "--tail", "1", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["tail"]["content"], "最后一行")

    def test_logs_human_readable(self):
        log_dir = self.root / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "export-合集一-20260101-000000.log").write_text("x", encoding="utf-8")
        code, out, err = self.run_cli("logs", *self.base(), "--collection", "合集一")
        self.assertEqual(code, 0)
        self.assertIn("export-合集一", out)
        self.assertIn("最新在前", out)

    def test_log_hint_shown_after_write_verbs(self):
        """人原来会去翻 deal_vedio/logs（空目录），必须主动告诉他日志在哪"""
        code, out, err = self.run_cli("subtitle", *self.base(), "--collections", "合集一")
        self.assertEqual(code, cli.EXIT_FAIL)          # 没有 .txt，必然失败
        self.assertIn("日志：", out)
        self.assertIn("log", out)
        self.assertIn("vedio logs", out)

    def test_log_hint_lists_newest_file(self):
        log_dir = self.root / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "agent-subtitle-合集一-20260101-000000.log").write_text("x", encoding="utf-8")
        code, out, err = self.run_cli("splice", *self.base(), "--collections", "合集一")
        self.assertIn("agent-subtitle-合集一-20260101-000000.log", out)

    def test_all_verbs_have_help(self):
        """十一个动词都要能加载（防 import 错误）"""
        for verb in ("paths", "status", "init", "subtitle", "export",
                     "splice", "rename", "ledger", "run", "series", "logs"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    cli.main([verb, "--help"])
            self.assertEqual(ctx.exception.code, 0, f"{verb} --help 失败：{err.getvalue()}")


if __name__ == "__main__":
    unittest.main()
