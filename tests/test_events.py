# -*- coding: utf-8 -*-
"""vedio/events.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - 用可注入的 clock 控制时间，不 sleep
    - 人读日志与 JSONL 两条线都验
    - 坏行、写不进去的历史目录等边界都覆盖
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


# ─────────────────────────── 输出落盘（capture） ───────────────────────────

class TestCapture(TempCase):
    """旧代码（剪映控制器 / LangGraph agent / 流式模型回复）只会 print。
    这些输出不落盘就找不回来了，所以要在这一层整段 tee 到文件。"""

    def setUp(self):
        super().setUp()
        # capture 是往"真流"里写的，不关起来这些测试会把内容喷到控制台
        self._old_streams = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
        self.addCleanup(self._restore_streams)

    def _restore_streams(self):
        sys.stdout, sys.stderr = self._old_streams

    def test_captures_stdout(self):
        log = self.make()
        with log.capture("agent-subtitle", "合集一") as path:
            print("解析出的主题是：愚者整合包")
        self.assertIn("解析出的主题是", path.read_text(encoding="utf-8"))

    def test_captures_stderr(self):
        log = self.make()
        with log.capture("export") as path:
            print("这行去 stderr", file=sys.stderr)
        self.assertIn("这行去 stderr", path.read_text(encoding="utf-8"))

    def test_captures_streamed_chunks(self):
        """模型是逐字打印的，不能因为没换行就丢"""
        log = self.make()
        with log.capture("agent") as path:
            for chunk in ["第", "一", "集"]:
                print(chunk, end="", flush=True)
        self.assertIn("第一集", path.read_text(encoding="utf-8"))

    def test_strips_ansi_colors(self):
        """structlog 的 ConsoleRenderer 会带颜色，写进文件是乱码"""
        log = self.make()
        with log.capture("agent") as path:
            print("\x1b[32m绿色\x1b[0m 和 \x1b[1m粗体\x1b[0m")
        text = path.read_text(encoding="utf-8")
        self.assertIn("绿色", text)
        self.assertNotIn("\x1b", text)

    def test_filename_has_name_and_collection(self):
        log = self.make()
        with log.capture("agent-subtitle", "合集一") as path:
            pass
        self.assertTrue(path.name.startswith("agent-subtitle-合集一-"))
        self.assertEqual(path.suffix, ".log")
        self.assertEqual(path.parent, self.log_dir)

    def test_streams_restored_after_normal_exit(self):
        log = self.make()
        old_out, old_err = sys.stdout, sys.stderr
        with log.capture("x"):
            pass
        self.assertIs(sys.stdout, old_out)
        self.assertIs(sys.stderr, old_err)

    def test_streams_restored_after_exception(self):
        """崩了也要还原，否则后面所有输出都写进死文件"""
        log = self.make()
        old_out, old_err = sys.stdout, sys.stderr
        with self.assertRaises(RuntimeError):
            with log.capture("x"):
                raise RuntimeError("boom")
        self.assertIs(sys.stdout, old_out)
        self.assertIs(sys.stderr, old_err)

    def test_output_survives_exception(self):
        """崩之前的输出必须留下 —— 那正是要查的东西"""
        log = self.make()
        with self.assertRaises(RuntimeError):
            with log.capture("x") as path:
                print("崩之前最后一句")
                raise RuntimeError("boom")
        self.assertIn("崩之前最后一句", path.read_text(encoding="utf-8"))

    def test_echo_false_writes_file_but_not_console(self):
        """`--quiet` 的实现：只写文件，控制台一个字节都不出。

        不能用"改道到 stderr"来假装安静 —— 调用方的工具结果同时收 stdout 和 stderr。
        """
        log = self.make()
        console = io.StringIO()
        with redirect_stdout(console):
            with log.capture("x", echo=False) as path:
                print("这段只该进文件")
        self.assertEqual(console.getvalue(), "")                       # 控制台空
        self.assertIn("这段只该进文件", path.read_text(encoding="utf-8"))  # 文件有

    def test_echo_false_also_silences_stderr(self):
        log = self.make()
        console = io.StringIO()
        with redirect_stderr(console):
            with log.capture("x", echo=False) as path:
                print("错误流也静音", file=sys.stderr)
        self.assertEqual(console.getvalue(), "")
        self.assertIn("错误流也静音", path.read_text(encoding="utf-8"))

    def test_write_to_captures_reaches_open_log(self):
        """安静模式下结果绕过了 tee，靠这个补进日志"""
        log = self.make()
        with log.capture("x", echo=False) as path:
            E.write_to_captures("结果补写\n")
        self.assertIn("结果补写", path.read_text(encoding="utf-8"))

    def test_write_to_captures_without_open_log(self):
        self.assertFalse(E.write_to_captures("没人收\n"))

    def test_nested_captures_both_get_content(self):
        """外层 run 日志 + 内层合集日志都要有"""
        log = self.make()
        with log.capture("run", echo=False) as outer:
            with log.capture("agent", "合集一", echo=False) as inner:
                print("嵌套输出")
        self.assertIn("嵌套输出", outer.read_text(encoding="utf-8"))
        self.assertIn("嵌套输出", inner.read_text(encoding="utf-8"))

    def test_works_inside_redirect(self):
        """CLI 的 --json 模式会先把 stdout 指向 stderr，capture 要能套在里面"""
        log = self.make()
        buf = io.StringIO()
        with redirect_stdout(buf):
            with log.capture("x") as path:
                print("hello")
        self.assertEqual(buf.getvalue(), "hello\n")             # 外层照常收到
        self.assertIn("hello", path.read_text(encoding="utf-8"))  # 文件也收到

    def test_tee_delegates_attributes(self):
        """encoding / isatty 这类属性要转给真流，免得子进程或库拿到会崩"""
        log = self.make()
        with log.capture("x"):
            self.assertIsInstance(sys.stdout.isatty(), bool)
            # 值本身取决于被包的流（StringIO 的 encoding 就是 None），
            # 关键是**能取到**而不是抛 AttributeError
            self.assertIn(sys.stdout.encoding, (None, "utf-8", "cp936", "UTF-8", "gbk"))


# ─────────────────────────── 日志文件列表 ───────────────────────────

class TestListLogs(TempCase):
    def write(self, name: str, text: str = "x") -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        p = self.log_dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_empty_when_missing_dir(self):
        self.assertEqual(E.list_logs(self.tmp / "没有这个目录"), [])

    def test_lists_newest_first(self):
        import os
        import time
        old = self.write("agent-subtitle-合集一-20260101-000000.log")
        new = self.write("agent-subtitle-合集二-20260102-000000.log")
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_800_000_000, 1_800_000_000))
        files = E.list_logs(self.log_dir)
        self.assertEqual(files[0].path.name, "agent-subtitle-合集二-20260102-000000.log")

    def test_keyword_filter(self):
        self.write("agent-subtitle-合集一-20260101-000000.log")
        self.write("agent-subtitle-合集二-20260101-000000.log")
        files = E.list_logs(self.log_dir, "合集一")
        self.assertEqual([f.path.name for f in files],
                         ["agent-subtitle-合集一-20260101-000000.log"])

    def test_size_and_modified_present(self):
        self.write("a.log", "12345")
        f = E.list_logs(self.log_dir)[0]
        self.assertEqual(f.size, 5)
        self.assertRegex(f.modified, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(f.as_dict()["name"], "a.log")

    def test_dirs_are_skipped(self):
        (self.log_dir / "子目录").mkdir(parents=True)
        self.write("a.log")
        self.assertEqual(len(E.list_logs(self.log_dir)), 1)


class TestTailLog(TempCase):
    def test_returns_last_lines(self):
        self.log_dir.mkdir(parents=True)
        p = self.log_dir / "a.log"
        p.write_text("\n".join(f"第{i}行" for i in range(1, 11)), encoding="utf-8")
        text = E.tail_log(p, 3)
        self.assertEqual(text.splitlines(), ["第8行", "第9行", "第10行"])

    def test_zero_means_nothing(self):
        self.log_dir.mkdir(parents=True)
        p = self.log_dir / "a.log"
        p.write_text("x\ny\n", encoding="utf-8")
        self.assertEqual(E.tail_log(p, 0), "")

    def test_missing_file(self):
        self.assertEqual(E.tail_log(self.tmp / "没有.log"), "")

    def test_broken_bytes_do_not_crash(self):
        """日志里可能混进编码错乱的字节，看日志本身不能失败"""
        self.log_dir.mkdir(parents=True)
        p = self.log_dir / "a.log"
        p.write_bytes(b"\xff\xfe normal line\n ok\n")
        self.assertIn("normal line", E.tail_log(p, 5))


if __name__ == "__main__":
    unittest.main()
