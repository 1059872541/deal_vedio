# -*- coding: utf-8 -*-
"""vedio/stages/run.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

只验编排逻辑，各阶段自己的行为由各自的测试覆盖：
    - 未知步骤要报错
    - 一个合集的某步失败 → 停这个合集，继续下一个
    - 批次级步骤（ledger）只在最后跑一次
    - ffmpeg / 剪映都不真调（用测试内的假实现替换阶段函数）
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import context  # noqa: E402
from vedio.events import EventLog  # noqa: E402
from vedio.stages import run as RUN  # noqa: E402


RULES = """\
game: 我的世界
batch: 2026-12
collections: 2
duration:
  material_per_collection: 1200
  episode_body: 60
  episode_count: 3
  segment_tolerance: 3
meta:
  host: 波波
"""


def build(tmp: Path) -> None:
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text("drafts: {}\ntemplates:\n  intro_mapping: {}\n  outro: null\n",
                                        encoding="utf-8")
    (root / "标题.md").write_text("# x\n公共前缀:波波之我的世界\n", encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in ("合集一", "合集二"):
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)


class FakeResult:
    def __init__(self, ok=True, status="done", message="", error=None):
        self.ok = ok
        self.status = status
        self.message = message
        self.error = error


class RunCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        build(self.tmp)
        self.p = context.Project.open("我的世界", "2026-12",
                                      local={"workspace": {"root": str(self.tmp)}})
        self.log = EventLog(self.p.log_dir)

    def patch_steps(self, number=None, splice=None, rename=None, ledger=None):
        """替换阶段函数，记录调用"""
        calls = []

        def make(name, result):
            def fn(project, collection, log=None, **kw):
                calls.append((name, collection.name))
                return result
            return fn

        patchers = [
            mock.patch.object(RUN, "_call_collection_step",
                              side_effect=self._dispatcher(calls, number, splice, rename)),
            mock.patch("vedio.stages.ledger.build_ledger",
                       side_effect=lambda project, collections=None, log=None, **kw: (
                           calls.append(("ledger", "(批次)")),
                           ledger or FakeResult())[1]),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        return calls

    def _dispatcher(self, calls, number, splice, rename):
        table = {"number": number, "splice": splice, "rename": rename}

        def dispatch(project, collection, step, *, log=None, state=None):
            calls.append((step, collection.name))
            result = table.get(step)
            if isinstance(result, Exception):
                raise result
            return result or FakeResult()
        return dispatch


class TestRun(RunCase):
    def test_unknown_step_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            RUN.run(self.p, ["不存在的步骤"], log=self.log)
        self.assertIn("未知步骤", str(ctx.exception))

    def test_collection_step_runs_per_collection(self):
        calls = self.patch_steps()
        report = RUN.run(self.p, ["number", "rename"], log=self.log)
        self.assertTrue(report.ok)
        self.assertEqual(calls, [("number", "合集一"), ("rename", "合集一"),
                                 ("number", "合集二"), ("rename", "合集二")])

    def test_failure_stops_that_collection_only(self):
        calls = self.patch_steps(number=FakeResult(ok=False, status="fail", error="boom"))
        report = RUN.run(self.p, ["number", "rename"], log=self.log)
        self.assertFalse(report.ok)
        # 两个合集都试了 number，但都没继续到 rename
        self.assertEqual([c for c in calls if c[0] == "number"], [("number", "合集一"),
                                                                 ("number", "合集二")])
        self.assertEqual([c for c in calls if c[0] == "rename"], [])

    def test_exception_is_recorded_not_raised(self):
        calls = self.patch_steps(splice=RuntimeError("ffmpeg 挂了"))
        report = RUN.run(self.p, ["splice"], log=self.log)
        self.assertFalse(report.ok)
        self.assertEqual(report.results[0].error, "RuntimeError")
        self.assertIn("ffmpeg 挂了", report.results[0].message)

    def test_batch_step_runs_once_at_end(self):
        calls = self.patch_steps()
        report = RUN.run(self.p, ["number", "ledger"], log=self.log)
        self.assertTrue(report.ok)
        self.assertEqual(calls[-1], ("ledger", "(批次)"))
        self.assertEqual(len([c for c in calls if c[0] == "ledger"]), 1)

    def test_subset_of_collections(self):
        calls = self.patch_steps()
        report = RUN.run(self.p, ["number"], ["合集二"], log=self.log)
        self.assertEqual(report.collections, ["合集二"])
        self.assertEqual(calls, [("number", "合集二")])

    def test_default_steps_cover_all(self):
        report = RUN.run(self.p, ["number"], log=self.log)
        self.assertEqual(report.steps, ["number"])

    def test_event_recorded(self):
        self.patch_steps()
        RUN.run(self.p, ["number"], log=self.log)
        last = self.log.last(verb="run")
        self.assertIsNotNone(last)
        self.assertEqual(last.fields["steps"], ["number"])

    def test_skip_result_counts_as_ok(self):
        self.patch_steps(number=FakeResult(ok=True, status="skip"))
        report = RUN.run(self.p, ["number"], log=self.log)
        self.assertTrue(report.ok)
        self.assertEqual(report.results[0].status, "skip")


if __name__ == "__main__":
    unittest.main()
