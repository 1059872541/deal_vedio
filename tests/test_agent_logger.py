# -*- coding: utf-8 -*-
"""旧 agent logger 的落盘测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

背景：`AgentLogger` 一直有两个问题
  1. structlog 只配了 `PrintLoggerFactory()`，所以它**建目录但从不写文件**
  2. 目录在 `__init__` 里 mkdir，位置是 `src/logs`（代码仓库里）

结果：用户打开 `deal_vedio/logs` 或 `src/logs` 只看到空目录，以为"没有日志"。
现在改成：数据落 `{log_dir}/agent-{run_id}.jsonl`，目录按需创建。
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from deal_video_agent.agent import logger as L  # noqa: E402


class LoggerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name) / "log"
        self.addCleanup(self._tmp.cleanup)
        L.reset_logger()
        L.set_default_log_dir(None)
        self.addCleanup(L.reset_logger)
        self.addCleanup(L.set_default_log_dir, None)

    def make(self) -> L.AgentLogger:
        return L.AgentLogger(str(self.log_dir))

    def records(self, log_dir: Path) -> list[dict]:
        files = sorted(Path(log_dir).glob("agent-*.jsonl"))
        out = []
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out


class TestWritesFile(LoggerCase):
    def test_no_dir_created_until_first_write(self):
        """构造对象不该留下空目录 —— 那正是"以为没日志"的来源"""
        log = self.make()
        self.assertFalse(self.log_dir.exists(), "不该在构造时就建目录")
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/剪辑", "提示词")
        self.assertTrue(self.log_dir.is_dir())

    def test_start_writes_jsonl(self):
        log = self.make()
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/剪辑", "本次视频是【愚者整合包】")
        records = self.records(self.log_dir)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event"], "agent_start")
        self.assertEqual(records[0]["level"], "info")
        self.assertIn("愚者整合包", records[0]["user_prompt"])
        self.assertTrue(records[0]["ts"])

    def test_all_log_methods_land_in_file(self):
        log = self.make()
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/x", "p")
            log.log_parse_result("我的世界", "愚者整合包", "实况解说", "a.txt")
            log.log_knowledge_base_check("愚者整合包", True, "kb.md")
            log.log_add_line_order("a.txt", "a_ordered.txt")
            log.log_correct_subtitle_start("a_ordered.txt", "kb.md")
            log.log_correct_subtitle_complete("corrected.txt", 7)
            log.log_title_generation_start("a_ordered.txt")
            log.log_title_generation_complete(20, 0)
            log.log_update_srt("corrected.txt", "a_corrected.srt")
            log.log_api_call("correct_subtitle", 1)
            log.log_result("completed", "完成", 1)
        names = [r["event"] for r in self.records(self.log_dir)]
        for expected in ("agent_start", "parse_complete", "knowledge_base_check",
                         "add_line_order", "correct_subtitle_start",
                         "correct_subtitle_complete", "title_generation_start",
                         "title_generation_complete", "update_srt", "api_call",
                         "agent_complete"):
            self.assertIn(expected, names)

    def test_error_goes_to_file(self):
        log = self.make()
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/x", "p")
            log.log_error("correct_subtitle", "API 限流")
        errors = [r for r in self.records(self.log_dir) if r["level"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error"], "API 限流")

    def test_filename_uses_run_id(self):
        log = self.make()
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/x", "p")
        files = list(self.log_dir.glob("agent-*.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertIn(log._run_id, files[0].name)

    def test_append_across_two_runs(self):
        log = self.make()
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/x", "p")
            log.log_result("completed", "ok", 1)
        records = self.records(self.log_dir)
        self.assertEqual([r["event"] for r in records], ["agent_start", "agent_complete"])

    def test_unicode_is_not_escaped(self):
        """日志是给人看的，别把中文写成 \\uXXXX"""
        log = self.make()
        with redirect_stdout(io.StringIO()):
            log.log_error("parse_input", "未找到字幕文件")
        raw = next(self.log_dir.glob("agent-*.jsonl")).read_text(encoding="utf-8")
        self.assertIn("未找到字幕文件", raw)
        self.assertNotIn("\\u672a", raw)

    def test_write_failure_does_not_break_run(self):
        """写日志失败绝不能影响纠错本身"""
        blocker = Path(self._tmp.name) / "blocked"
        blocker.write_text("i am a file", encoding="utf-8")
        log = L.AgentLogger(str(blocker))
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/x", "p")      # 不该抛
            log.log_result("completed", "ok", 1)


class TestSingleton(LoggerCase):
    def test_get_logger_uses_given_dir(self):
        with redirect_stdout(io.StringIO()):
            got = L.get_logger(str(self.log_dir))
            got.start("/tmp/x", "p")
        self.assertTrue(list(self.log_dir.glob("agent-*.jsonl")))

    def test_reset_gives_fresh_instance(self):
        first = L.get_logger(str(self.log_dir))
        L.reset_logger()
        second = L.get_logger(str(self.log_dir))
        self.assertIsNot(first, second)

    def test_default_dir_is_inside_src(self):
        """没设进程级默认目录时才回落到 src/logs —— 所以 vedio 必须先设好"""
        default = L.AgentLogger()
        self.assertEqual(default.log_dir.name, "logs")
        self.assertEqual(default.log_dir.parent.name, "src")


class TestDefaultDir(LoggerCase):
    """`nodes.py` 每次运行都会 reset_logger() 再 get_logger()（不带参数）。
    所以光传参没用，必须设进程级默认目录，否则日志又跑回 src/logs。"""

    def test_set_default_changes_where_no_arg_goes(self):
        L.set_default_log_dir(self.log_dir)
        self.assertEqual(L.get_logger().log_dir, self.log_dir)

    def test_reset_keeps_default(self):
        L.set_default_log_dir(self.log_dir)
        L.get_logger()
        L.reset_logger()                     # nodes.py 里就是这么干的
        self.assertEqual(L.get_logger().log_dir, self.log_dir)

    def test_default_can_be_cleared(self):
        L.set_default_log_dir(self.log_dir)
        L.set_default_log_dir(None)
        self.assertEqual(L.get_default_log_dir().name, "logs")

    def test_write_after_reset_lands_in_default(self):
        """模拟真实顺序：设默认 → reset → 无参 get_logger → 写日志"""
        L.set_default_log_dir(self.log_dir)
        L.reset_logger()
        log = L.get_logger()
        with redirect_stdout(io.StringIO()):
            log.start("/tmp/x", "p")
        self.assertTrue(list(self.log_dir.glob("agent-*.jsonl")))
        self.assertFalse((L.get_default_log_dir().parent / "logs").exists()
                         and L.get_default_log_dir().parent.name == "src")


if __name__ == "__main__":
    unittest.main()
