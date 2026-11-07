# -*- coding: utf-8 -*-
"""vedio/stages/splice.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - **不真跑 ffmpeg**：注入假 runner，按命令里的输出路径造文件
    - 计划计算是纯函数，单独验（边界：余量、碎段、超长）
    - 重点守四件事：片头片尾缺失要停、优先 copy、copy 失败回退重编码、
      中间分段文件用完要删
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

from vedio import context, media  # noqa: E402
from vedio.events import EventLog  # noqa: E402
from vedio.stages import splice as SP  # noqa: E402


RULES = """\
game: 我的世界
batch: 2026-12
collections: 2
duration:
  material_per_collection: 1200
  episode_body: 60
  episode_count: 3
  segment_tolerance: 3
encode:
  encoder_priority: [h264_qsv, libx264]
  quality: 23
  preset: medium
  pix_fmt: yuv420p
  audio_codec: aac
  audio_bitrate: 128k
meta:
  host: 波波
"""

MANIFEST = """\
drafts: {}
templates:
  intro_mapping:
    default: 片头/intro.mp4
  outro: 片尾/outro.mp4
"""


def build(tmp: Path, with_templates=True) -> None:
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "标题.md").write_text("# 我的世界系列视频标题列表\n公共前缀:波波之我的世界\n",
                                  encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in ("合集一", "合集二"):
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)
    if with_templates:
        (root / "片头").mkdir(exist_ok=True)
        (root / "片尾").mkdir(exist_ok=True)
        (root / "片头" / "intro.mp4").write_bytes(b"intro")
        (root / "片尾" / "outro.mp4").write_bytes(b"outro")


class FakeFfmpeg:
    """按命令参数造出输出文件；可指定某类命令失败"""

    def __init__(self, fail_concat_copy=False, fail_cut=False):
        self.calls = []
        self.fail_concat_copy = fail_concat_copy
        self.fail_cut = fail_cut

    def __call__(self, args, timeout):
        args = list(args)
        self.calls.append(args)
        out = Path(args[-1])
        if "-f" in args and "concat" in args and "copy" in args:
            if self.fail_concat_copy:
                return 1, "Non-monotonous DTS"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"concatenated")
            return 0, ""
        if "-c" in args and "copy" in args and "slice" not in args:
            # 切分：-ss 后跟 -i
            if self.fail_cut:
                return 1, "Invalid data"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"segment")
            return 0, ""
        # 回退重编码
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"encoded")
        return 0, ""

    def kinds(self):
        """把调用归类，方便断言"""
        out = []
        for args in self.calls:
            if "-filter_complex" in args:
                out.append("encode")
            elif "-f" in args and "concat" in args:
                out.append("copy")
            else:
                out.append("cut")
        return out


class SpliceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        build(self.tmp)
        self.p = context.Project.open("我的世界", "2026-12",
                                      local={"workspace": {"root": str(self.tmp)}})
        self.c = self.p.collection("合集一")
        self.log = EventLog(self.p.log_dir)

        # 假时长：长片 100 秒，片头 5 秒，片尾 3 秒
        table = {"长片.mp4": 100.0, "intro.mp4": 5.0, "outro.mp4": 3.0}
        patcher = mock.patch.object(
            media, "probe_duration",
            side_effect=lambda ff, p, **kw: table.get(Path(p).name, 10.0),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def touch_long(self, name="长片.mp4") -> Path:
        p = self.c.editing / name
        p.write_bytes(b"x" * 10)
        return p

    def splice(self, runner=None, force=False):
        return SP.splice_collection(
            self.p, self.c, log=self.log,
            runner=runner or FakeFfmpeg(), force=force,
        )


# ─────────────────────────── 计划（纯函数） ───────────────────────────

class TestPlan(unittest.TestCase):
    def plan(self, total, body=60, count=3, tol=3):
        return SP.plan_segments(total, body, count, Path("成片"), "合集一",
                                tolerance=tol, temp_dir=Path("tmp"))

    def test_exact_division(self):
        segs = self.plan(180)
        self.assertEqual(len(segs), 3)
        self.assertEqual([s.duration for s in segs], [60, 60, 60])
        self.assertEqual(segs[0].start, 0)
        self.assertEqual(segs[1].start, 60)

    def test_remainder_merges_into_last(self):
        """余量不足一段时并进上一段，不产生 2 秒碎集"""
        segs = self.plan(125)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[-1].duration, 65)
        self.assertAlmostEqual(sum(s.duration for s in segs), 125)

    def test_small_tail_is_merged(self):
        """切出 5 秒尾巴时必须并进上一段，不能产出一个 5 秒的"集"""
        segs = self.plan(125)
        self.assertTrue(all(s.duration >= 30 for s in segs))

    def test_large_tail_is_kept(self):
        """尾巴有 40 秒就是个正经集，不该被吞掉"""
        segs = self.plan(160)
        self.assertEqual([s.duration for s in segs], [60, 60, 40])

    def test_just_over_boundary_creates_new_segment(self):
        segs = self.plan(124)
        self.assertEqual(len(segs), 2)

    def test_temp_and_output_are_different_paths(self):
        segs = self.plan(180)
        self.assertNotEqual(segs[0].output, segs[0].temp)
        self.assertEqual(segs[0].output.name, "合集一-01.mp4")
        self.assertEqual(segs[0].temp.name, "合集一-01.seg.mp4")

    def test_zero_body_rejected(self):
        with self.assertRaises(SP.SpliceError):
            self.plan(180, body=0)

    def test_zero_duration_rejected(self):
        with self.assertRaises(SP.SpliceError):
            self.plan(0)


class TestMismatch(unittest.TestCase):
    def segs(self, n):
        return [SP.Segment(i, 0, 1, Path(f"o{i}"), Path(f"t{i}")) for i in range(1, n + 1)]

    def test_match(self):
        self.assertIsNone(SP.expected_mismatch(self.segs(3), 3))

    def test_too_few(self):
        self.assertIn("只切出 2 段", SP.expected_mismatch(self.segs(2), 3))

    def test_too_many(self):
        self.assertIn("比预期", SP.expected_mismatch(self.segs(5), 3))


# ─────────────────────────── 单个合集 ───────────────────────────

class TestSpliceCollection(SpliceCase):
    def test_missing_templates_stops_immediately(self):
        (self.p.batch_dir / "片头" / "intro.mp4").unlink()
        self.touch_long()
        r = self.splice()
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "template_missing")
        self.assertIn("片头", r.message)
        self.assertEqual(r.outputs, [])

    def test_missing_long_video(self):
        r = self.splice()
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "no_long_video")

    def test_happy_copy_path(self):
        self.touch_long()
        ff = FakeFfmpeg()
        r = self.splice(runner=ff)
        self.assertEqual(r.status, "done")
        self.assertEqual(r.mode, "copy")
        self.assertEqual(r.segments, 2)          # 100 秒 / 60 秒
        self.assertEqual(len(r.outputs), 2)
        # 每段：一次切分 + 一次 copy 拼接
        kinds = ff.kinds()
        self.assertEqual(kinds.count("cut"), 2)
        self.assertEqual(kinds.count("copy"), 2)
        self.assertEqual(kinds.count("encode"), 0)

    def test_outputs_land_in_final_dir(self):
        self.touch_long()
        self.splice()
        finals = media.list_videos(self.c.final)
        self.assertEqual(len(finals), 2)
        self.assertTrue(all(f.name.startswith("合集一-") for f in finals))

    def test_temp_segments_are_cleaned(self):
        self.touch_long()
        self.splice()
        leftovers = list((self.c.final / "_segments").glob("*.mp4")) \
            if (self.c.final / "_segments").is_dir() else []
        self.assertEqual(leftovers, [])

    def test_fallback_to_encode_when_copy_fails(self):
        self.touch_long()
        ff = FakeFfmpeg(fail_concat_copy=True)
        r = self.splice(runner=ff)
        self.assertEqual(r.status, "done")
        self.assertEqual(r.mode, "encode")
        kinds = ff.kinds()
        self.assertEqual(kinds.count("encode"), 2)

    def test_cut_failure_reports(self):
        self.touch_long()
        r = self.splice(runner=FakeFfmpeg(fail_cut=True))
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "cut_failed")

    def test_skip_when_already_done(self):
        self.touch_long()
        self.splice()
        ff = FakeFfmpeg()
        r = self.splice(runner=ff)
        self.assertEqual(r.status, "skip")
        self.assertEqual(ff.calls, [])

    def test_force_redoes(self):
        self.touch_long()
        self.splice()
        r = self.splice(runner=FakeFfmpeg(), force=True)
        self.assertEqual(r.status, "done")

    def test_events(self):
        self.touch_long()
        self.splice()
        kinds = [e.event for e in self.log.read() if e.verb == "splice"]
        self.assertEqual(kinds, ["start", "done"])
        done = self.log.last(verb="splice", event="done")
        self.assertEqual(done.fields["mode"], "copy")
        self.assertEqual(done.fields["outputs"], 2)


# ─────────────────────────── 批量 ───────────────────────────

class TestSpliceBatch(SpliceCase):
    def test_batch_continues_after_failure(self):
        self.touch_long()                                # 只有合集一有长片
        results = SP.splice_batch(self.p, log=self.log, runner=FakeFfmpeg())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].status, "done")
        self.assertEqual(results[1].status, "fail")      # 合集二没长片
        self.assertEqual(results[1].error, "no_long_video")

    def test_subset(self):
        self.touch_long()
        results = SP.splice_batch(self.p, ["合集一"], log=self.log, runner=FakeFfmpeg())
        self.assertEqual([r.collection for r in results], ["合集一"])


if __name__ == "__main__":
    unittest.main()
