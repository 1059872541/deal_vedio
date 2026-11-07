# -*- coding: utf-8 -*-
"""vedio/stages/subtitle.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - **不调 API、不跑 LangGraph**：runner 注入假函数，只写 corrected.txt
    - 标题搬运用 titles_writer 注入，不依赖旧 agent 的目录
    - 三步的幂等（已存在就跳过）与失败传播都要验
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import context, subtitles  # noqa: E402
from vedio.events import EventLog  # noqa: E402
from vedio.stages import subtitle as SUB  # noqa: E402


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

TITLES = """\
# 我的世界系列视频标题列表
公共前缀:波波之我的世界
"""

SRT = (
    "1\r\n00:00:04,433 --> 00:00:06,233\r\n一个崭新的世界\r\n\r\n"
    "2\r\n00:00:06,300 --> 00:00:08,100\r\n我们现在站在一个\r\n"
)


def build(tmp: Path) -> None:
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text("drafts: {}\ntemplates:\n  intro_mapping: {}\n  outro: null\n",
                                        encoding="utf-8")
    (root / "标题.md").write_text(TITLES, encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in ("合集一", "合集二"):
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)


class SubCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        build(self.tmp)
        self.p = context.Project.open("我的世界", "2026-12",
                                      local={"workspace": {"root": str(self.tmp)}})
        self.c = self.p.collection("合集一")
        self.log = EventLog(self.p.log_dir)

    def write_txt(self, text="第一句\n第二句\n") -> Path:
        p = self.c.editing / "片.txt"
        p.write_text(text, encoding="utf-8")
        return p

    def write_srt(self) -> Path:
        p = self.c.editing / "片.srt"
        p.write_bytes(SRT.encode("utf-8"))
        return p

    def fake_runner(self, produce="1:改过的世界\n2:我们站在山谷\n"):
        calls = []

        def runner(target_dir, prompt):
            calls.append((target_dir, prompt))
            (Path(target_dir) / "corrected.txt").write_text(produce, encoding="utf-8")
            return {"corrected_file": str(Path(target_dir) / "corrected.txt")}
        runner.calls = calls
        return runner


# ─────────────────────────── ① 加行号 ───────────────────────────

class TestNumber(SubCase):
    def test_happy(self):
        self.write_txt()
        r = SUB.number(self.p, self.c, log=self.log)
        self.assertEqual(r.status, "done")
        out = self.c.editing / "片_ordered.txt"
        self.assertEqual(out.read_text(encoding="utf-8"), "1:第一句\n2:第二句\n")

    def test_missing_source(self):
        r = SUB.number(self.p, self.c)
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "source_txt_missing")

    def test_idempotent(self):
        self.write_txt()
        SUB.number(self.p, self.c, log=self.log)
        r = SUB.number(self.p, self.c, log=self.log)
        self.assertEqual(r.status, "skip")
        self.assertEqual([e.event for e in self.log.read() if e.verb == "subtitle:number"],
                         ["done", "skip"])

    def test_force_rewrites(self):
        src = self.write_txt()
        SUB.number(self.p, self.c)
        src.write_text("改过的句子\n", encoding="utf-8")
        r = SUB.number(self.p, self.c, force=True)
        self.assertEqual(r.status, "done")
        self.assertEqual((self.c.editing / "片_ordered.txt").read_text(encoding="utf-8"),
                         "1:改过的句子\n")

    def test_excludes_intermediate_files(self):
        """_ordered.txt 存在时也要挑中原始 txt"""
        self.write_txt()
        (self.c.editing / "corrected.txt").write_text("1:x", encoding="utf-8")
        r = SUB.number(self.p, self.c)
        self.assertEqual(r.status, "done")


# ─────────────────────────── ② 纠错 ───────────────────────────

class TestCorrect(SubCase):
    def test_happy_without_titles(self):
        self.write_txt()
        runner = self.fake_runner()
        # read_agent_titles 会去仓库里找旧 agent 写的标题文件。那里可能**真的**
        # 有文件（人跑过一次就留下了），不隔离的话这条测试会随环境飘。
        with mock.patch.object(SUB, "read_agent_titles", return_value=None):
            r = SUB.correct(self.p, self.c, log=self.log, runner=runner)
        self.assertEqual(r.status, "done")
        self.assertEqual(runner.calls[0][0], str(self.c.editing))
        self.assertTrue((self.c.editing / "corrected.txt").is_file())
        self.assertFalse(r.detail["titles_written"])

    def test_titles_are_copied_when_available(self):
        """旧 agent 写了标题时，要搬进批次的 标题.md"""
        self.write_txt()
        written = []
        with mock.patch.object(SUB, "read_agent_titles",
                               return_value=["第一集标题", "第二集标题"]):
            r = SUB.correct(self.p, self.c, log=self.log, runner=self.fake_runner(),
                            titles_writer=lambda ts: written.extend(ts))
        self.assertEqual(written, ["第一集标题", "第二集标题"])
        self.assertTrue(r.detail["titles_written"])
        self.assertEqual(r.detail["titles"], 2)

    def test_titles_writer_injected(self):
        self.write_txt()
        written = []
        with mock.patch.object(SUB, "read_agent_titles", return_value=None):
            r = SUB.correct(self.p, self.c, log=self.log, runner=self.fake_runner(),
                            titles_writer=lambda ts: written.extend(ts))
        # 没有标题来源时不该被调
        self.assertEqual(written, [])
        self.assertEqual(r.status, "done")

    def test_agent_output_is_saved_to_log(self):
        """agent 的 print 必须落盘 —— 出问题时这是唯一的线索"""
        self.write_txt()

        def noisy_runner(target_dir, prompt):
            print("解析主题：我的世界愚者整合包")
            print("流式回复：" + "纠" * 5)
            (Path(target_dir) / "corrected.txt").write_text("1:x\n", encoding="utf-8")
            return {}

        with mock.patch.object(SUB, "read_agent_titles", return_value=None):
            with redirect_stdout(io.StringIO()):
                r = SUB.correct(self.p, self.c, log=self.log, runner=noisy_runner)

        self.assertEqual(r.status, "done")
        log_file = r.detail["log_file"]
        self.assertTrue(log_file, "done 事件里应该带上日志文件名")
        text = (self.p.log_dir / log_file).read_text(encoding="utf-8")
        self.assertIn("解析主题：我的世界愚者整合包", text)
        self.assertIn("流式回复：纠纠纠纠纠", text)

        event = self.log.last(verb="subtitle:correct", event="done")
        self.assertEqual(event.fields["log_file"], log_file)

    def test_crash_still_leaves_log(self):
        """崩之前的输出必须留下 —— 那正是要查的东西"""
        self.write_txt()

        def bad_runner(target_dir, prompt):
            print("崩之前最后一句")
            raise RuntimeError("API 限流")

        with redirect_stdout(io.StringIO()):
            r = SUB.correct(self.p, self.c, log=self.log, runner=bad_runner)
        self.assertEqual(r.status, "fail")

        event = self.log.last(verb="subtitle:correct", event="fail")
        log_file = event.fields["log_file"]
        self.assertTrue(log_file)
        self.assertIn("崩之前最后一句",
                      (self.p.log_dir / log_file).read_text(encoding="utf-8"))

    def test_points_legacy_logger_at_batch_log(self):
        """旧 logger 默认往 src/logs 写，必须被指到批次 log/"""
        self.write_txt()
        with mock.patch.object(SUB, "_point_legacy_logger") as spy:
            with mock.patch.object(SUB, "read_agent_titles", return_value=None):
                SUB.correct(self.p, self.c, log=self.log, runner=self.fake_runner())
        spy.assert_called_once_with(self.p.log_dir)

    def test_legacy_logger_writes_into_batch_log(self):
        """真跑一次旧 logger，文件必须落在批次 log/ 里"""
        from deal_video_agent.agent import logger as agent_logger

        self.write_txt()

        def runner_with_logger(target_dir, prompt):
            agent_logger.get_logger().start(target_dir, prompt)
            agent_logger.get_logger().log_correct_subtitle_complete("corrected.txt", 7)
            (Path(target_dir) / "corrected.txt").write_text("1:x\n", encoding="utf-8")
            return {}

        with mock.patch.object(SUB, "read_agent_titles", return_value=None):
            with redirect_stdout(io.StringIO()):
                r = SUB.correct(self.p, self.c, log=self.log, runner=runner_with_logger)
        self.assertEqual(r.status, "done")

        jsonl = list(self.p.log_dir.glob("agent-*.jsonl"))
        self.assertEqual(len(jsonl), 1, f"应在 {self.p.log_dir} 里，实际: {list(self.p.log_dir.iterdir())}")
        text = jsonl[0].read_text(encoding="utf-8")
        self.assertIn("agent_start", text)
        self.assertIn("correct_subtitle_complete", text)

        # 不能把文件写到仓库里的 src/logs
        self.assertFalse((SUB.__file__ and
                          Path(SUB.__file__).resolve().parents[2] / "logs" / "agent-x.jsonl").exists())

    def test_token_usage_recorded(self):
        """经 vedio 调用时 agent 的性能报告不打印，用量得自己捞出来记进事件"""
        self.write_txt()

        def runner_with_usage(target_dir, prompt):
            (Path(target_dir) / "corrected.txt").write_text("1:x\n", encoding="utf-8")
            return {"api_details": [
                {"node": "correct_subtitle",
                 "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}},
                {"node": "generate_title",
                 "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}},
            ]}

        with mock.patch.object(SUB, "read_agent_titles", return_value=None):
            r = SUB.correct(self.p, self.c, log=self.log, runner=runner_with_usage)
        self.assertEqual(r.detail["tokens"], {"prompt": 120, "completion": 80, "total": 200})
        self.assertIn("200 tokens", r.message)
        event = self.log.last(verb="subtitle:correct", event="done")
        self.assertEqual(event.fields["tokens"]["total"], 200)

    def test_no_usage_means_no_token_field(self):
        self.write_txt()
        with mock.patch.object(SUB, "read_agent_titles", return_value=None):
            r = SUB.correct(self.p, self.c, log=self.log, runner=self.fake_runner())
        self.assertNotIn("tokens", r.detail)
        self.assertNotIn("tokens", self.log.last(verb="subtitle:correct", event="done").fields)

    def test_runner_failure(self):
        self.write_txt()

        def bad(target_dir, prompt):
            raise RuntimeError("API 限流")

        r = SUB.correct(self.p, self.c, log=self.log, runner=bad)
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "RuntimeError")
        self.assertIn("API 限流", r.message)

    def test_runner_produces_nothing(self):
        """agent 跑完没产出 corrected.txt —— 不能记成功"""
        self.write_txt()
        r = SUB.correct(self.p, self.c, log=self.log, runner=lambda d, p: {})
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "corrected_missing")

    def test_idempotent(self):
        self.write_txt()
        SUB.correct(self.p, self.c, runner=self.fake_runner())
        r = SUB.correct(self.p, self.c, runner=self.fake_runner())
        self.assertEqual(r.status, "skip")

    def test_missing_source_txt(self):
        r = SUB.correct(self.p, self.c, runner=self.fake_runner())
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "source_txt_missing")


# ─────────────────────────── ③ 回写 srt ───────────────────────────

class TestPatch(SubCase):
    def test_happy(self):
        self.write_srt()
        (self.c.editing / "corrected.txt").write_text("1:改过的世界\n", encoding="utf-8")
        r = SUB.patch(self.p, self.c, log=self.log)
        self.assertEqual(r.status, "done")
        out = self.c.editing / "片_corrected.srt"
        raw = out.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("改过的世界".encode("utf-8"), raw)
        self.assertIn(b"\r\n", raw)
        self.assertEqual(r.detail["total"], 2)
        self.assertEqual(r.detail["applied"], 1)

    def test_missing_corrected(self):
        self.write_srt()
        r = SUB.patch(self.p, self.c)
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "corrected_missing")

    def test_missing_srt(self):
        (self.c.editing / "corrected.txt").write_text("1:x\n", encoding="utf-8")
        r = SUB.patch(self.p, self.c)
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "source_srt_missing")

    def test_ignores_corrected_srt_as_source(self):
        """已有 *_corrected.srt 时不能把它当源文件"""
        self.write_srt()
        (self.c.editing / "corrected.txt").write_text("1:x\n", encoding="utf-8")
        SUB.patch(self.p, self.c)
        r = SUB.patch(self.p, self.c, force=True)
        self.assertEqual(r.status, "done")

    def test_idempotent(self):
        self.write_srt()
        (self.c.editing / "corrected.txt").write_text("1:x\n", encoding="utf-8")
        SUB.patch(self.p, self.c)
        r = SUB.patch(self.p, self.c)
        self.assertEqual(r.status, "skip")


# ─────────────────────────── 串起来 ───────────────────────────

class TestRun(SubCase):
    def test_full_chain(self):
        self.write_txt()
        self.write_srt()
        results = SUB.run(self.p, self.c, log=self.log, runner=self.fake_runner())
        self.assertEqual([r.step for r in results], ["number", "correct", "patch"])
        self.assertTrue(all(r.ok for r in results))
        self.assertTrue((self.c.editing / "片_corrected.srt").is_file())

    def test_stops_on_first_failure(self):
        self.write_srt()          # 没有 txt → number 失败
        results = SUB.run(self.p, self.c, runner=self.fake_runner())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].step, "number")
        self.assertEqual(results[0].status, "fail")

    def test_subset_of_steps(self):
        self.write_srt()
        (self.c.editing / "corrected.txt").write_text("1:x\n", encoding="utf-8")
        results = SUB.run(self.p, self.c, steps=["patch"])
        self.assertEqual([r.step for r in results], ["patch"])

    def test_unknown_step(self):
        with self.assertRaises(ValueError):
            SUB.run(self.p, self.c, steps=["不存在"])

    def test_events_recorded(self):
        self.write_txt()
        self.write_srt()
        SUB.run(self.p, self.c, log=self.log, runner=self.fake_runner())
        verbs = [e.verb for e in self.log.read()]
        self.assertIn("subtitle:number", verbs)
        self.assertIn("subtitle:correct", verbs)
        self.assertIn("subtitle:patch", verbs)


if __name__ == "__main__":
    unittest.main()
