# -*- coding: utf-8 -*-
"""vedio/stages/series.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

重点：
    - 分组写法解析（中英文分隔符都认）
    - 上下篇后缀：1 个不加、2 个上下、3 个上中下、超过 3 个报错
    - 写 标题.md 时**只改小节头，不动标题正文**
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import context  # noqa: E402
from vedio.events import EventLog  # noqa: E402
from vedio.stages import series as SE  # noqa: E402


RULES = """\
game: 我的世界
batch: 2026-12
collections: 4
duration:
  material_per_collection: 1200
  episode_body: 60
  episode_count: 3
  segment_tolerance: 3
meta:
  host: 波波
"""

TITLES = """\
# 我的世界系列视频标题列表
公共前缀:波波之我的世界
---
#### 合集一:
林中小屋初探
骷髅头颅之谜
---
#### 合集二:
夜视药水配方
---
#### 合集三:
小鸡引诱记
---
#### 合集四:
徒手拓书
"""


def build(tmp: Path) -> None:
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text("drafts: {}\ntemplates:\n  intro_mapping: {}\n  outro: null\n",
                                        encoding="utf-8")
    (root / "标题.md").write_text(TITLES, encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in ("合集一", "合集二", "合集三", "合集四"):
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)


# ─────────────────────────── 解析 ───────────────────────────

class TestParse(unittest.TestCase):
    def test_basic(self):
        groups = SE.parse_groups("合集一,合集二=收集强力变身;合集三=下界合金升级")
        self.assertEqual(groups, [("收集强力变身", ["合集一", "合集二"]),
                                  ("下界合金升级", ["合集三"])])

    def test_fullwidth_separators(self):
        """中文输入法打出来的全角分隔符和等号都要认"""
        groups = SE.parse_groups("合集一，合集二＝收集强力变身；合集三＝下界合金升级")
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], ("收集强力变身", ["合集一", "合集二"]))
        self.assertEqual(groups[1], ("下界合金升级", ["合集三"]))

    def test_empty(self):
        self.assertEqual(SE.parse_groups(""), [])
        self.assertEqual(SE.parse_groups("   "), [])

    def test_missing_equal_raises(self):
        with self.assertRaises(SE.SeriesError) as ctx:
            SE.parse_groups("合集一,合集二")
        self.assertEqual(ctx.exception.code, "bad_spec")

    def test_missing_title_raises(self):
        with self.assertRaises(SE.SeriesError):
            SE.parse_groups("合集一=")


class TestAssignments(unittest.TestCase):
    def test_single_collection_no_suffix(self):
        got = SE.build_assignments([("初探巨龙", ["合集九"])])
        self.assertEqual(got, {"合集九": "初探巨龙"})

    def test_two_collections_up_down(self):
        got = SE.build_assignments([("下界合金升级", ["合集四", "合集五"])])
        self.assertEqual(got["合集四"], "下界合金升级-上篇")
        self.assertEqual(got["合集五"], "下界合金升级-下篇")

    def test_three_collections_up_mid_down(self):
        got = SE.build_assignments([("收集强力变身", ["合集一", "合集二", "合集三"])])
        self.assertEqual(got["合集一"], "收集强力变身-上篇")
        self.assertEqual(got["合集二"], "收集强力变身-中篇")
        self.assertEqual(got["合集三"], "收集强力变身-下篇")

    def test_more_than_three_rejected(self):
        with self.assertRaises(SE.SeriesError) as ctx:
            SE.build_assignments([("太长", ["合集一", "合集二", "合集三", "合集四"])])
        self.assertEqual(ctx.exception.code, "group_too_large")

    def test_duplicate_collection_rejected(self):
        with self.assertRaises(SE.SeriesError) as ctx:
            SE.build_assignments([("A", ["合集一"]), ("B", ["合集一"])])
        self.assertEqual(ctx.exception.code, "duplicate_collection")


# ─────────────────────────── 写文件 ───────────────────────────

class TestSetSubtitles(unittest.TestCase):
    def test_only_header_changes(self):
        new, missing = SE.set_subtitles(TITLES, {"合集一": "收集强力变身-上篇"})
        self.assertEqual(missing, [])
        self.assertIn("#### 合集一:收集强力变身-上篇", new)
        # 标题正文原样保留
        self.assertIn("林中小屋初探", new)
        self.assertIn("骷髅头颅之谜", new)
        # 别的小节没动
        self.assertIn("#### 合集二:", new)

    def test_existing_subtitle_replaced(self):
        text = TITLES.replace("#### 合集一:", "#### 合集一:旧的篇名-上篇")
        new, _ = SE.set_subtitles(text, {"合集一": "新篇名-下篇"})
        self.assertIn("#### 合集一:新篇名-下篇", new)
        self.assertNotIn("旧的篇名", new)

    def test_missing_section_is_appended(self):
        text = "# 标题\n公共前缀:波波之我的世界\n"
        new, missing = SE.set_subtitles(text, {"合集七": "独一篇"})
        self.assertEqual(missing, ["合集七"])
        self.assertIn("#### 合集七:独一篇", new)


# ─────────────────────────── 端到端 ───────────────────────────

class TestApply(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        build(self.tmp)
        self.p = context.Project.open("我的世界", "2026-12",
                                      local={"workspace": {"root": str(self.tmp)}})
        self.log = EventLog(self.p.log_dir)

    def test_happy(self):
        r = SE.apply(self.p, "合集一,合集二=收集强力变身;合集三=下界合金升级")
        self.assertEqual(r.status, "done")
        self.assertEqual(r.assignments["合集二"], "收集强力变身-下篇")
        # 回读：context 应该能解析出副标题
        project = context.Project.open("我的世界", "2026-12",
                                       local={"workspace": {"root": str(self.tmp)}})
        self.assertEqual(project.subtitle_for("合集一"), "收集强力变身-上篇")
        self.assertEqual(project.subtitle_for("合集三"), "下界合金升级")
        # 标题正文没丢
        self.assertEqual(project.titles_of("合集一"), ["林中小屋初探", "骷髅头颅之谜"])

    def test_idempotent(self):
        spec = "合集一,合集二=收集强力变身"
        SE.apply(self.p, spec)
        r = SE.apply(self.p, spec)
        self.assertEqual(r.status, "skip")

    def test_unknown_collection_rejected(self):
        r = SE.apply(self.p, "合集九十九=不存在的篇")
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "collection_not_found")

    def test_bad_spec(self):
        r = SE.apply(self.p, "没有等号")
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "bad_spec")

    def test_empty_spec(self):
        r = SE.apply(self.p, "")
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "empty_spec")

    def test_event_recorded(self):
        SE.apply(self.p, "合集一=独一篇", log=self.log)
        last = self.log.last(verb="series")
        self.assertEqual(last.event, "done")
        self.assertEqual(last.fields["assignments"], {"合集一": "独一篇"})


if __name__ == "__main__":
    unittest.main()
