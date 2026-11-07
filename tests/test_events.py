# -*- coding: utf-8 -*-
"""vedio/events.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - 用可注入的 clock 控制时间，不 sleep
    - 人读日志与 JSONL 两条线都验
    - 坏行、写不进去的历史目录等边界都覆盖
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import events as E  # noqa: E402


class FakeClock:
    """可控时钟：每次调用前进固定秒数"""

    def __init__(self, start: float = 1794000000.0, step: float = 0.0):
        self.now = start
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.log_dir = self.tmp / "log"

    def make(self, history=None, clock=None) -> E.EventLog:
        return E.EventLog(self.log_dir, history, clock or FakeClock())


# ─────────────────────────── 基本写入 ───────────────────────────

class TestEmit(TempCase):
    def test_jsonl_written(self):
        log = self.make()
        log.emit("export", E.START, "合集一")
        lines = log.events_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["verb"], "export")
        self.assertEqual(data["event"], "start")
        self.assertEqual(data["collection"], "合集一")
        self.assertIn("ts", data)

    def test_human_log_written_and_appends(self):
        """旧实现用覆盖模式，跨运行没法对比；这里必须是追加"""
        log = self.make()
        log.emit("export", E.START, "合集一")
        log.emit("export", E.DONE, "合集一", seconds=12.5)
        path = log.human_path()
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("开始", lines[0])
        self.assertIn("完成", lines[1])
        self.assertIn("12.5s", lines[1])

    def test_extra_fields_kept(self):
        log = self.make()
        log.emit("splice", E.DONE, "合集一", seconds=42.0, mode="copy", outputs=20)
        ev = log.read()[0]
        self.assertEqual(ev.fields["mode"], "copy")
        self.assertEqual(ev.fields["outputs"], 20)

    def test_creates_log_dir(self):
        log = self.make()
        self.assertFalse(self.log_dir.exists())
        log.emit("x", E.INFO)
        self.assertTrue(self.log_dir.is_dir())


# ─────────────────────────── step 上下文 ───────────────────────────

class TestStep(TempCase):
    def test_success_records_start_then_done(self):
        clock = FakeClock(step=7.0)
        log = self.make(clock=clock)
        with log.step("export", "合集一"):
            pass
        kinds = [e.event for e in log.read()]
        self.assertEqual(kinds, [E.START, E.DONE])
        done = log.read()[-1]
        self.assertEqual(done.fields["seconds"], 7.0)

    def test_failure_records_fail_and_reraises(self):
        clock = FakeClock(step=1.0)
        log = self.make(clock=clock)
        with self.assertRaises(ValueError):
            with log.step("export", "合集二"):
                raise ValueError("剪映没响应")
        events = log.read()
        self.assertEqual([e.event for e in events], [E.START, E.FAIL])
        fail = events[-1]
        self.assertEqual(fail.fields["message"], "剪映没响应")
        self.assertEqual(fail.fields["error"], "ValueError")

    def test_step_carries_fields_on_both_events(self):
        log = self.make()
        with log.step("splice", "合集一", mode="copy"):
            pass
        events = log.read()
        self.assertEqual(events[0].fields["mode"], "copy")
        self.assertEqual(events[1].fields["mode"], "copy")


# ─────────────────────────── 读取 ───────────────────────────

class TestRead(TempCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(E.read_events(self.tmp / "nope.jsonl"), [])

    def test_broken_lines_are_skipped(self):
        """写到一半被断电也不能让 status 崩掉"""
        self.log_dir.mkdir(parents=True)
        (self.log_dir / E.EVENTS_FILE).write_text(
            '{"verb":"a","event":"start"}\n'
            'not json at all\n'
            '{"verb":"b","event":"done"}\n',
            encoding="utf-8",
        )
        events = E.read_events(self.log_dir / E.EVENTS_FILE)
        self.assertEqual([e.verb for e in events], ["a", "b"])

    def test_last_with_filters(self):
        clock = FakeClock(step=10.0)
        log = self.make(clock=clock)
        log.emit("export", E.START, "合集一")
        log.emit("export", E.DONE, "合集一")
        log.emit("export", E.START, "合集二")

        self.assertEqual(log.last(verb="export", collection="合集一", event=E.DONE).collection, "合集一")
        self.assertEqual(log.last(verb="export").collection, "合集二")
        self.assertIsNone(log.last(verb="splice"))

    def test_failed(self):
        log = self.make()
        log.emit("export", E.FAIL, "合集一", error="DraftNotFound")
        log.emit("export", E.DONE, "合集二")
        fails = log.failed()
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0].collection, "合集一")


# ─────────────────────────── 汇总 ───────────────────────────

class TestSummarize(TempCase):
    def test_counts_and_average(self):
        log = self.make()
        log.emit("export", E.DONE, "合集一", seconds=10)
        log.emit("export", E.DONE, "合集二", seconds=20)
        log.emit("export", E.FAIL, "合集三", error="x", seconds=99)
        log.emit("splice", E.DONE, "合集一", seconds=5)

        stats = E.summarize(log.read())
        self.assertEqual(stats["export"]["done"], 2)
        self.assertEqual(stats["export"]["fail"], 1)
        self.assertEqual(stats["export"]["seconds"], 30)      # fail 的 99 秒不算
        self.assertEqual(stats["export"]["avg_seconds"], 15.0)
        self.assertEqual(stats["splice"]["avg_seconds"], 5.0)

    def test_verb_without_duration(self):
        log = self.make()
        log.emit("status", E.INFO)
        stats = E.summarize(log.read())
        self.assertIsNone(stats["status"]["avg_seconds"])


# ─────────────────────────── 跨批次历史 ───────────────────────────

class TestHistory(TempCase):
    def test_slim_record_appended(self):
        history = self.tmp / ".vedio" / "history"
        log = self.make(history=history)
        log.emit("splice", E.DONE, "合集一", seconds=42.0, mode="copy", verbose="不该进历史")

        lines = (history / E.EVENTS_FILE).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["verb"], "splice")
        self.assertEqual(data["seconds"], 42.0)
        self.assertEqual(data["mode"], "copy")
        self.assertNotIn("verbose", data)

    def test_history_write_failure_is_silent(self):
        """历史目录写不进去不该影响主流程"""
        blocker = self.tmp / "blocked"
        blocker.write_text("i am a file, not a dir", encoding="utf-8")
        log = E.EventLog(self.log_dir, blocker / "history", FakeClock())
        log.emit("export", E.START, "合集一")      # should not raise
        self.assertEqual(len(log.read()), 1)

    def test_no_history_dir_means_no_history_file(self):
        log = self.make(history=None)
        log.emit("export", E.START)
        self.assertFalse((self.tmp / ".vedio").exists())


# ─────────────────────────── 显示 ───────────────────────────

class TestRender(unittest.TestCase):
    def test_event_str_is_readable(self):
        ev = E.Event(verb="splice", event="done", collection="合集一",
                     fields={"seconds": 42.06, "mode": "copy"})
        text = str(ev)
        self.assertIn("[splice]", text)
        self.assertIn("合集一", text)
        self.assertIn("42.1s", text)

    def test_fail_str_shows_error(self):
        ev = E.Event(verb="export", event="fail", collection="合集二",
                     fields={"error": "DraftNotFound"})
        self.assertIn("DraftNotFound", str(ev))


if __name__ == "__main__":
    unittest.main()
