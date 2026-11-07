# -*- coding: utf-8 -*-
"""vedio/subtitles.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

重点守三件事：
    1. 解析宽松，**一条字幕都不能丢**
    2. 补丁按序号匹配（不是数组下标）
    3. 输出是 UTF-8 无 BOM + CRLF（实测剪映自己导出的就是这个格式）
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import subtitles as S  # noqa: E402


SRT = (
    "1\r\n"
    "00:00:04,433 --> 00:00:06,233\r\n"
    "一个崭新的世界\r\n"
    "\r\n"
    "2\r\n"
    "00:00:06,300 --> 00:00:08,100\r\n"
    "我们现在站在一个\r\n"
    "山谷边缘\r\n"
    "\r\n"
    "3\r\n"
    "00:00:08,200 --> 00:00:09,000\r\n"
    "开始吧\r\n"
)


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, text: str) -> Path:
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
        return p


# ─────────────────────────── 解析 ───────────────────────────

class TestParse(TempCase):
    def test_basic(self):
        blocks = S.parse_srt(SRT)
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0].index, 1)
        self.assertEqual(blocks[0].start, "00:00:04,433")
        self.assertEqual(blocks[0].end, "00:00:06,233")
        self.assertEqual(blocks[0].text, "一个崭新的世界")

    def test_multiline_block(self):
        blocks = S.parse_srt(SRT)
        self.assertEqual(blocks[1].lines, ["我们现在站在一个", "山谷边缘"])

    def test_bom_and_lf_are_tolerated(self):
        text = "\ufeff" + SRT.replace("\r\n", "\n")
        self.assertEqual(len(S.parse_srt(text)), 3)

    def test_extra_blank_lines(self):
        text = SRT.replace("\r\n\r\n", "\r\n\r\n\r\n")
        self.assertEqual(len(S.parse_srt(text)), 3)

    def test_missing_sequence_number_still_parsed(self):
        """没序号也得解析出来 —— 少一句就少一处校对"""
        text = "00:00:01,000 --> 00:00:02,000\n只有时间轴\n\n"
        blocks = S.parse_srt(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].start, "00:00:01,000")
        self.assertEqual(blocks[0].text, "只有时间轴")

    def test_empty_text(self):
        self.assertEqual(S.parse_srt(""), [])
        self.assertEqual(S.parse_srt("\r\n\r\n"), [])

    def test_trailing_block_without_blank_line(self):
        text = "1\n00:00:01,000 --> 00:00:02,000\n最后一句"
        blocks = S.parse_srt(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, "最后一句")


# ─────────────────────────── 渲染 ───────────────────────────

class TestRender(unittest.TestCase):
    def test_roundtrip(self):
        blocks = S.parse_srt(SRT)
        out = S.render_srt(blocks)
        again = S.parse_srt(out)
        self.assertEqual([b.text for b in again], [b.text for b in blocks])

    def test_crlf_by_default(self):
        out = S.render_srt(S.parse_srt(SRT))
        self.assertIn("\r\n", out)
        self.assertEqual(out.count("\n"), out.count("\r\n"))

    def test_no_bom(self):
        out = S.render_srt(S.parse_srt(SRT))
        self.assertFalse(out.startswith("\ufeff"))

    def test_indices_renumbered(self):
        blocks = S.parse_srt(SRT)
        blocks[0].index = 99
        out = S.render_srt(blocks)
        self.assertTrue(out.startswith("1\r\n"))
        self.assertIn("\r\n2\r\n", out)

    def test_lf_mode(self):
        out = S.render_srt(S.parse_srt(SRT), crlf=False)
        self.assertNotIn("\r\n", out)


# ─────────────────────────── 补丁 ───────────────────────────

class TestPatch(unittest.TestCase):
    def test_parse_basic(self):
        patch = S.parse_patch("1:改过的第一句\n3:改过的第三句\n")
        self.assertEqual(patch, {1: "改过的第一句", 3: "改过的第三句"})

    def test_parse_pipe_separator(self):
        """旧实现容忍 `行号|内容`，保持一致"""
        self.assertEqual(S.parse_patch("2|内容\n"), {2: "内容"})

    def test_parse_continuation_lines(self):
        patch = S.parse_patch("2:第一行\n第二行\n3:x\n")
        self.assertEqual(patch[2], "第一行\n第二行")
        self.assertEqual(patch[3], "x")

    def test_parse_skips_blank_and_garbage(self):
        patch = S.parse_patch("\n\n1:a\n\n")
        self.assertEqual(patch, {1: "a"})

    def test_apply_by_index_not_position(self):
        """补丁按序号匹配：序号 2 改的是第 2 块，不是数组第 2 个"""
        blocks = S.parse_srt(SRT)
        new, stats = S.apply_patch(blocks, {2: "改过的第二块"})
        self.assertEqual(new[1].text, "改过的第二块")
        self.assertEqual(new[0].text, "一个崭新的世界")
        self.assertEqual(new[2].text, "开始吧")
        self.assertEqual(stats["applied"], 1)

    def test_apply_reports_missing(self):
        blocks = S.parse_srt(SRT)
        new, stats = S.apply_patch(blocks, {9: "不存在"})
        self.assertEqual(stats["missing"], [9])
        self.assertEqual(stats["applied"], 0)
        self.assertEqual(len(new), 3)

    def test_apply_does_not_mutate_input(self):
        blocks = S.parse_srt(SRT)
        S.apply_patch(blocks, {1: "改了"})
        self.assertEqual(blocks[0].text, "一个崭新的世界")

    def test_apply_multiline_replacement(self):
        blocks = S.parse_srt(SRT)
        new, _ = S.apply_patch(blocks, {1: "第一行\n第二行"})
        self.assertEqual(new[0].lines, ["第一行", "第二行"])


# ─────────────────────────── 文件级 ───────────────────────────

class TestPatchFile(TempCase):
    def test_writes_utf8_without_bom_crlf(self):
        srt = self.write("片.srt", SRT)
        pat = self.write("corrected.txt", "1:改过的句子\n")
        stats = S.patch_file(srt, pat)
        out = Path(stats["out"])
        self.assertEqual(out.name, "片_corrected.srt")

        raw = out.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "不能带 BOM")
        self.assertTrue(raw.startswith(b"1\r\n"), "第一行应是序号 + CRLF")
        text = raw.decode("utf-8")
        self.assertIn("改过的句子", text)
        self.assertEqual(text.count("\n"), text.count("\r\n"))
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["applied"], 1)

    def test_reading_bom_srt(self):
        srt = self.write("片.srt", "\ufeff" + SRT)
        pat = self.write("corrected.txt", "1:x\n")
        self.assertEqual(S.patch_file(srt, pat)["total"], 3)

    def test_explicit_output_path(self):
        srt = self.write("片.srt", SRT)
        pat = self.write("corrected.txt", "1:x\n")
        out = self.tmp / "自己定的名字.srt"
        stats = S.patch_file(srt, pat, out)
        self.assertEqual(Path(stats["out"]), out)


class TestNumberFile(TempCase):
    def test_numbering(self):
        src = self.write("片.txt", "第一句\n第二句\n\n第三句\n")
        stats = S.number_file(src)
        out = Path(stats["out"])
        self.assertEqual(out.name, "片_ordered.txt")
        self.assertEqual(out.read_text(encoding="utf-8"),
                         "1:第一句\n2:第二句\n3:第三句\n")
        self.assertEqual(stats["lines"], 3)

    def test_strips_crlf(self):
        src = self.write("片.txt", "甲\r\n乙\r\n")
        stats = S.number_file(src)
        self.assertEqual(Path(stats["out"]).read_text(encoding="utf-8"), "1:甲\n2:乙\n")

    def test_empty(self):
        src = self.write("片.txt", "")
        stats = S.number_file(src)
        self.assertEqual(stats["lines"], 0)


# ─────────────────────────── 找输入 ───────────────────────────

class TestFinders(TempCase):
    def test_find_source_txt_excludes_intermediates(self):
        d = self.tmp / "剪辑"
        d.mkdir()
        (d / "片.txt").write_text("x", encoding="utf-8")
        (d / "片_ordered.txt").write_text("1:x", encoding="utf-8")
        (d / "corrected.txt").write_text("1:y", encoding="utf-8")
        self.assertEqual(S.find_source_txt(d).name, "片.txt")

    def test_find_source_srt_excludes_corrected(self):
        d = self.tmp / "剪辑"
        d.mkdir()
        (d / "片.srt").write_text("x", encoding="utf-8")
        (d / "片_corrected.srt").write_text("x", encoding="utf-8")
        self.assertEqual(S.find_source_srt(d).name, "片.srt")

    def test_missing_dir_returns_none(self):
        self.assertIsNone(S.find_source_txt(self.tmp / "不存在"))
        self.assertIsNone(S.find_source_srt(self.tmp / "不存在"))

    def test_find_corrected(self):
        d = self.tmp / "剪辑"
        d.mkdir()
        self.assertIsNone(S.find_corrected(d))
        (d / "corrected.txt").write_text("1:x", encoding="utf-8")
        self.assertEqual(S.find_corrected(d).name, "corrected.txt")


if __name__ == "__main__":
    unittest.main()
