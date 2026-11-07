# -*- coding: utf-8 -*-
"""vedio/progress.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

定位：进度表是**记录**，不是证据。
    - 程序只打 ✓，永不擦回 `·`
    - 表格外面人写的东西原样保留
    - 表被改乱了，先备份再重建
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import progress as P  # noqa: E402


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.path = self.tmp / P.FILE_NAME

    def fresh(self, names=("合集一", "合集二"), ignored=None) -> P.ProgressTable:
        return P.ProgressTable.create("我的世界-2026-12", list(names), ignored)


# ─────────────────────────── 建表 ───────────────────────────

class TestCreate(unittest.TestCase):
    def test_header_and_rows(self):
        t = P.ProgressTable.create("我的世界-2026-12", ["合集一", "合集二"])
        self.assertEqual(t.header, ["合集", "剪辑", "字幕", "导出", "拼接", "命名", "台账"])
        self.assertEqual(t.collections(), ["合集一", "合集二"])
        self.assertTrue(all(c == P.EMPTY for c in t.rows[0][1:]))

    def test_banner_says_hand_editable(self):
        text = P.ProgressTable.create("X", ["合集一"]).render()
        self.assertIn("人可以直接改", text)
        self.assertIn("不会把 ✓ 改回去", text)

    def test_ignored_section(self):
        text = P.ProgressTable.create("X", ["合集一"], ["合集三"]).render()
        self.assertIn("## 已忽略", text)
        self.assertIn("`合集三`", text)

    def test_render_is_parseable(self):
        t = P.ProgressTable.create("X", ["合集一", "合集二"])
        again = P.ProgressTable.parse(t.render())
        self.assertEqual(again.header, t.header)
        self.assertEqual(again.collections(), ["合集一", "合集二"])


# ─────────────────────────── 解析 ───────────────────────────

class TestParse(TempCase):
    def test_preserves_text_outside_table(self):
        """人在表头/表尾写的东西不能被吃掉"""
        text = (
            "# 进度 · 我的世界-2026-12\n"
            "\n"
            "> 我自己加的说明\n"
            "\n"
            "| 合集 | 剪辑 | 字幕 |\n"
            "|---|---|---|\n"
            "| 合集一 | ✓ | · |\n"
            "\n"
            "随手记一句：合集二卡在素材，等下周补录\n"
        )
        parsed = P.ProgressTable.parse(text)
        rendered = parsed.render()
        self.assertIn("我自己加的说明", rendered)
        self.assertIn("随手记一句：合集二卡在素材，等下周补录", rendered)
        self.assertEqual(parsed.collections(), ["合集一"])

    def test_roundtrip_stable(self):
        text = self.fresh().render()
        self.assertEqual(P.ProgressTable.parse(text).render(), text)

    def test_missing_table_raises(self):
        with self.assertRaises(P.ProgressFormatError):
            P.ProgressTable.parse("# 进度\n\n什么都没有\n")

    def test_wrong_first_column_raises(self):
        with self.assertRaises(P.ProgressFormatError):
            P.ProgressTable.parse("| 集数 | 剪辑 |\n|---|---|\n| 一 | · |\n")

    def test_row_shorter_than_header_is_padded(self):
        text = "| 合集 | 剪辑 | 字幕 |\n|---|---|---|\n| 合集一 | ✓ |\n"
        t = P.ProgressTable.parse(text)
        self.assertEqual(t.rows[0], ["合集一", "✓", ""])

    def test_separator_optional(self):
        text = "| 合集 | 剪辑 |\n| 合集一 | ✓ |\n"
        t = P.ProgressTable.parse(text)
        self.assertEqual(t.collections(), ["合集一"])

    def test_bom_tolerated_on_load(self):
        self.path.write_text("\ufeff" + self.fresh().render(), encoding="utf-8")
        self.assertEqual(P.ProgressTable.load(self.path).collections(), ["合集一", "合集二"])


# ─────────────────────────── 改格子 ───────────────────────────

class TestSetCell(unittest.TestCase):
    def setUp(self):
        self.t = P.ProgressTable.create("X", ["合集一", "合集二"])

    def test_marks_done(self):
        self.assertTrue(self.t.set_cell("合集一", "字幕"))
        self.assertEqual(self.t.cell("合集一", "字幕"), P.DONE)
        self.assertEqual(self.t.cell("合集二", "字幕"), P.EMPTY)

    def test_idempotent(self):
        self.t.set_cell("合集一", "字幕")
        self.assertFalse(self.t.set_cell("合集一", "字幕"))

    def test_refuses_to_erase_done(self):
        """程序不许把 ✓ 擦回 ·；退回状态只能人来做"""
        self.t.set_cell("合集一", "字幕")
        self.assertFalse(self.t.set_cell("合集一", "字幕", P.EMPTY))
        self.assertEqual(self.t.cell("合集一", "字幕"), P.DONE)

    def test_can_write_ledger_name(self):
        self.t.set_cell("合集一", "台账", "台账-01")
        self.assertEqual(self.t.cell("合集一", "台账"), "台账-01")

    def test_auto_creates_row(self):
        self.assertTrue(self.t.set_cell("合集三", "剪辑"))
        self.assertIn("合集三", self.t.collections())

    def test_unknown_stage_raises(self):
        with self.assertRaises(P.ProgressFormatError):
            self.t.set_cell("合集一", "不存在的环节")

    def test_human_added_column_is_kept(self):
        text = self.t.render().replace("| 合集 | 剪辑 |", "| 合集 | 备注 | 剪辑 |")
        t = P.ProgressTable.parse(text)
        self.assertIn("备注", t.header)
        t.set_cell("合集一", "剪辑")
        self.assertIn("备注", t.render())


# ─────────────────────────── 落盘 / 重建 ───────────────────────────

class TestSave(TempCase):
    def test_atomic_write_leaves_no_tmp(self):
        self.fresh().save(self.path)
        self.assertTrue(self.path.is_file())
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_save_creates_parents(self):
        deep = self.tmp / "a" / "b" / P.FILE_NAME
        self.fresh().save(deep)
        self.assertTrue(deep.is_file())

    def test_creates_when_missing(self):
        self.assertFalse(self.fresh().save_or_rebuild(self.path, "X", ["合集一"]))
        self.assertTrue(self.path.is_file())

    def test_rebuilds_and_backs_up_broken_table(self):
        self.path.write_text("# 乱七八糟\n\n没有表格\n", encoding="utf-8")
        rebuilt = self.fresh().save_or_rebuild(self.path, "我的世界-2026-12", ["合集一"])
        self.assertTrue(rebuilt)
        self.assertTrue((self.tmp / (P.FILE_NAME + ".bak")).is_file())
        self.assertIn("合集一", self.path.read_text(encoding="utf-8"))

    def test_save_or_rebuild_keeps_content_when_valid(self):
        t = self.fresh()
        t.set_cell("合集一", "字幕")
        t.save(self.path)
        t2 = P.ProgressTable.load(self.path)
        self.assertFalse(t2.save_or_rebuild(self.path, "X", ["合集一"]))
        self.assertEqual(P.ProgressTable.load(self.path).cell("合集一", "字幕"), P.DONE)


# ─────────────────────────── 追加合集 ───────────────────────────

class TestAddCollections(TempCase):
    def test_appends_new_rows_only(self):
        P.write_initial(self.tmp, "我的世界-2026-12", ["合集一", "合集二"])
        result = P.add_collections(self.path, "我的世界-2026-12", ["合集二", "合集三"])
        self.assertEqual(result["added"], ["合集三"])
        self.assertEqual(result["existing"], ["合集二"])
        table = P.ProgressTable.load(self.path)
        self.assertEqual(table.collections(), ["合集一", "合集二", "合集三"])

    def test_creates_file_when_missing(self):
        result = P.add_collections(self.path, "X", ["合集一"])
        self.assertEqual(result["added"], ["合集一"])
        self.assertTrue(self.path.is_file())

    def test_rebuilds_broken_file(self):
        self.path.write_text("坏的\n", encoding="utf-8")
        result = P.add_collections(self.path, "X", ["合集一"])
        self.assertTrue(result["rebuilt"])
        self.assertTrue((self.tmp / (P.FILE_NAME + ".bak")).is_file())

    def test_keeps_existing_progress(self):
        P.write_initial(self.tmp, "X", ["合集一"])
        table = P.ProgressTable.load(self.path)
        table.set_cell("合集一", "字幕")
        table.save(self.path)
        P.add_collections(self.path, "X", ["合集二"])
        self.assertEqual(P.ProgressTable.load(self.path).cell("合集一", "字幕"), P.DONE)


class TestRecord(TempCase):
    """`record()` 是各 stage 成功后调的那一个函数 —— 它**永不抛异常**。"""

    class FakeProject:
        def __init__(self, root: Path, names=("合集一", "合集二"), ignored=None):
            self.batch_dir = Path(root)
            self.name = "我的世界-2026-12"
            self._names = list(names)
            self._ignored = list(ignored or [])

        def collection_names(self):
            return self._names

        def ignored_collections(self):
            return self._ignored

    def setUp(self):
        super().setUp()
        self.project = self.FakeProject(self.tmp)

    def table(self):
        return P.ProgressTable.load(self.tmp / P.FILE_NAME)

    def test_marks_stage(self):
        self.assertTrue(P.record(self.project, "合集一", "字幕"))
        self.assertEqual(self.table().cell("合集一", "字幕"), P.DONE)

    def test_second_call_is_noop(self):
        P.record(self.project, "合集一", "字幕")
        self.assertFalse(P.record(self.project, "合集一", "字幕"))

    def test_creates_table_when_missing(self):
        P.record(self.project, "合集一", "剪辑")
        self.assertEqual(self.table().collections(), ["合集一", "合集二"])

    def test_rebuilds_broken_table_with_backup(self):
        (self.tmp / P.FILE_NAME).write_text("坏的\n", encoding="utf-8")
        self.assertTrue(P.record(self.project, "合集一", "字幕"))
        self.assertTrue((self.tmp / (P.FILE_NAME + ".bak")).is_file())
        self.assertEqual(self.table().cell("合集一", "字幕"), P.DONE)

    def test_unknown_stage_does_not_raise(self):
        """表头少一列也不能把一次成功的导出搞成失败"""
        P.write_initial(self.tmp, "我的世界-2026-12", ["合集一"])
        raw = (self.tmp / P.FILE_NAME).read_text(encoding="utf-8")
        (self.tmp / P.FILE_NAME).write_text(
            raw.replace("| 合集 | 剪辑 |", "| 合集 | 备注 |"), encoding="utf-8")
        self.assertFalse(P.record(self.project, "合集一", "剪辑"))

    def test_bad_project_does_not_raise(self):
        class Broken:
            pass
        self.assertFalse(P.record(Broken(), "合集一", "字幕"))

    def test_ledger_value_is_written(self):
        P.record(self.project, "合集一", "台账", "台账-01.xlsx")
        self.assertEqual(self.table().cell("合集一", "台账"), "台账-01.xlsx")

    def test_ignored_section_survives(self):
        project = self.FakeProject(self.tmp, ignored=["合集三"])
        P.record(project, "合集一", "字幕")
        text = (self.tmp / P.FILE_NAME).read_text(encoding="utf-8")
        self.assertIn("已忽略", text)
        self.assertIn("合集三", text)


if __name__ == "__main__":
    unittest.main()
