# -*- coding: utf-8 -*-
"""TitlesManager 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

覆盖 2026-11-07 修的两处：

1. **一级标题硬编码**：三处都写死 ``# 我的世界系列视频标题列表``，
   已经导致 ``足球在线4-2026-06_titles.md`` 的第一行变成"我的世界"。
2. **副标题被并进合集名**：``_parse_all_collections`` 用 ``replace(':', '')``，
   把 ``#### 合集一:收集强力变身-上篇`` 整行当成 key，于是
   ````collection_name in existing_collections`` 永远不成立 ——
   ``overwrite=True`` 失效，每次重跑都会追加一个重复小节；
   而重建时又用 ``f"#### {name}:"`` 输出，副标题被抹掉。

全部在临时目录里跑，不碰真实标题文件。
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from deal_video_agent.agent.tools.titles_manager import TitlesManager  # noqa: E402


SAMPLE = """# 我的世界系列视频标题列表
公共前缀:波波之我的世界
---
#### 合集一:收集强力变身-上篇
林中小屋初探
骷髅头颅之谜
---
#### 合集二:收集强力变身-中篇
夜视药水配方
"""


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def make(self, filename="我的世界-2026-06_titles.md", content=None) -> TitlesManager:
        m = TitlesManager(str(self.tmp), title_file=f"titles/{filename}")
        if content is not None:
            m.title_file.write_text(content, encoding="utf-8")
        return m


# ─────────────────────────── 一级标题 ───────────────────────────

class TestGameName(TempCase):
    def test_derive_from_batch_filename(self):
        m = self.make("我的世界-2026-06_titles.md")
        self.assertEqual(m.game_name, "我的世界")

    def test_derive_handles_digits_in_game_name(self):
        """足球在线4 里的 4 不能被当成批次的一部分"""
        m = self.make("足球在线4-2026-06_titles.md")
        self.assertEqual(m.game_name, "足球在线4")

    def test_derive_falls_back_to_stem(self):
        m = self.make("all_collection_titles.md")
        self.assertEqual(m.game_name, "all_collection")

    def test_explicit_game_name_wins(self):
        m = TitlesManager(str(self.tmp), title_file="titles/x_titles.md", game_name="我的世界")
        self.assertEqual(m.game_name, "我的世界")

    def test_new_file_gets_correct_header(self):
        self.make("足球在线4-2026-06_titles.md")
        text = (self.tmp / "titles" / "足球在线4-2026-06_titles.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 足球在线4系列视频标题列表"))

    def test_clear_uses_correct_header(self):
        m = self.make("足球在线4-2026-06_titles.md", SAMPLE)
        m.clear_all_titles()
        text = m.title_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 足球在线4系列视频标题列表"))
        self.assertNotIn("我的世界", text)


# ─────────────────────────── 小节头解析 ───────────────────────────

class TestSectionHeader(unittest.TestCase):
    def test_with_subtitle(self):
        self.assertEqual(
            TitlesManager._parse_section_header("#### 合集一:收集强力变身-上篇"),
            ("合集一", "收集强力变身-上篇"),
        )

    def test_colon_but_no_subtitle(self):
        self.assertEqual(TitlesManager._parse_section_header("#### 合集二:"), ("合集二", None))

    def test_no_colon(self):
        self.assertEqual(TitlesManager._parse_section_header("#### 合集三"), ("合集三", None))

    def test_fullwidth_colon(self):
        self.assertEqual(
            TitlesManager._parse_section_header("#### 合集九：初探巨龙-上篇"),
            ("合集九", "初探巨龙-上篇"),
        )


# ─────────────────────────── 解析 ───────────────────────────

class TestParse(TempCase):
    def test_keys_are_collection_names_not_including_subtitle(self):
        """核心回归：key 必须是「合集一」，不能是「合集一收集强力变身-上篇」"""
        m = self.make(content=SAMPLE)
        parsed = m._parse_all_collections(m.title_file.read_text(encoding="utf-8"))
        self.assertEqual(sorted(parsed), ["合集一", "合集二"])
        self.assertEqual(parsed["合集一"], ["林中小屋初探", "骷髅头颅之谜"])

    def test_subtitles_are_stashed(self):
        m = self.make(content=SAMPLE)
        m._parse_all_collections(m.title_file.read_text(encoding="utf-8"))
        self.assertEqual(m._section_subtitles["合集一"], "收集强力变身-上篇")
        self.assertEqual(m._section_subtitles["合集二"], "收集强力变身-中篇")


# ─────────────────────────── 追加 / 覆盖 ───────────────────────────

class TestAppend(TempCase):
    def test_new_collection_appends_without_touching_existing(self):
        m = self.make(content=SAMPLE)
        self.assertTrue(m.append_titles("合集三", ["初探巨龙", "龙巢金矿"]))
        text = m.title_file.read_text(encoding="utf-8")
        self.assertIn("#### 合集一:收集强力变身-上篇", text)
        self.assertIn("#### 合集三:", text)
        self.assertIn("初探巨龙", text)

    def test_overwrite_replaces_titles_and_keeps_subtitle(self):
        """原实现这里会追加重复小节，且把副标题弄丢"""
        m = self.make(content=SAMPLE)
        self.assertTrue(m.append_titles("合集一", ["新标题A", "新标题B"], overwrite=True))
        text = m.title_file.read_text(encoding="utf-8")

        self.assertEqual(text.count("#### 合集一"), 1, "不该出现重复小节")
        self.assertIn("#### 合集一:收集强力变身-上篇", text)
        self.assertIn("新标题A", text)
        self.assertNotIn("林中小屋初探", text)

    def test_overwrite_keeps_header_correct(self):
        m = self.make("足球在线4-2026-06_titles.md", SAMPLE)
        m.append_titles("合集一", ["x"], overwrite=True)
        text = m.title_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 足球在线4系列视频标题列表"))
        self.assertNotIn("我的世界系列", text)

    def test_overwrite_section_without_subtitle(self):
        m = self.make(content="# 我的世界系列视频标题列表\n\n---\n#### 合集一:\n旧标题\n\n")
        m.append_titles("合集一", ["新标题"], overwrite=True)
        text = m.title_file.read_text(encoding="utf-8")
        self.assertEqual(text.count("#### 合集一"), 1)
        self.assertIn("新标题", text)
        self.assertNotIn("旧标题", text)

    def test_empty_titles_rejected(self):
        m = self.make(content=SAMPLE)
        self.assertFalse(m.append_titles("合集三", []))


# ─────────────────────────── 读取 ───────────────────────────

class TestRead(TempCase):
    def test_read_all_titles_list(self):
        m = self.make(content=SAMPLE)
        self.assertEqual(
            m.read_all_titles_list(),
            ["林中小屋初探", "骷髅头颅之谜", "夜视药水配方"],
        )

    def test_prefix_line_is_not_a_title(self):
        """回归：原实现把「公共前缀:波波之我的世界」也当成一条标题，
        喂给 LLM 做去重时是噪音，还会让 is_duplicate 误判。"""
        m = self.make(content=SAMPLE)
        titles = m.read_all_titles_list()
        self.assertNotIn("公共前缀:波波之我的世界", titles)
        self.assertFalse(m.check_duplicate("公共前缀:波波之我的世界"))

    def test_read_all_titles_text_excludes_prefix(self):
        m = self.make(content=SAMPLE)
        self.assertNotIn("公共前缀", m.read_all_titles())

    def test_check_duplicate_finds_real_title(self):
        m = self.make(content=SAMPLE)
        self.assertTrue(m.check_duplicate("林中小屋初探"))
        self.assertFalse(m.check_duplicate("全新的标题"))

    def test_missing_batch_but_constructor_creates_it(self):
        m = TitlesManager(str(self.tmp), title_file="titles/新游戏-2027-01_titles.md")
        self.assertTrue(m.title_file.is_file())
        self.assertTrue(m.title_file.read_text(encoding="utf-8").startswith("# 新游戏系列"))


if __name__ == "__main__":
    unittest.main()
