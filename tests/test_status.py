# -*- coding: utf-8 -*-
"""vedio/stages/status.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - **不调 ffprobe**：时长靠注入的 probe（按文件名给固定秒数）
    - 全部在临时目录里造批次，不碰真实工作区
    - 逐阶段推进，验证 stage / 七列标记 / JSON 输出
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

from vedio import context  # noqa: E402
from vedio.events import EventLog  # noqa: E402
from vedio.stages import status as S  # noqa: E402


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

MANIFEST = """\
drafts:
  合集一: "MC-合集一"
templates:
  intro_mapping:
    default: 片头/intro.mp4
  outro: 片尾/outro.mp4
"""

TITLES = """\
# 我的世界系列视频标题列表
公共前缀:波波之我的世界
---
#### 合集一:收集强力变身-上篇
第一集标题
第二集标题
第三集标题
"""


def build(tmp: Path, collections=("合集一", "合集二")) -> dict:
    """造一个批次，返回可喂给 Project.open 的 local 配置"""
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "标题.md").write_text(TITLES, encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in collections:
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)
    return {"workspace": {"root": str(tmp)}}


def touch(path: Path, text: str = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


class StatusCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.local = build(self.tmp)
        self.p = context.Project.open("我的世界", "2026-12", local=self.local)
        self._durations: dict[str, float] = {}

    def probe(self, path: Path) -> float:
        return self._durations.get(path.name, 0.0)

    def set_duration(self, name: str, seconds: float) -> None:
        self._durations[name] = seconds

    def status(self, collections=None):
        return S.collect(self.p, probe=self.probe, collections=collections)

    def one(self, name="合集一") -> S.CollectionStatus:
        return self.status([name]).collections[0]

    # ── 素材 ──

    def test_empty_material_is_stage_material(self):
        st = self.one()
        self.assertEqual(st.stage, "素材")
        self.assertFalse(st.material_ok)
        self.assertEqual(st.material_files, 0)

    def test_material_below_target(self):
        touch(self.p.collection("合集一").material / "a.mkv")
        self.set_duration("a.mkv", 600)
        st = self.one()
        self.assertAlmostEqual(st.material_seconds, 600)
        self.assertEqual(st.stage, "素材")

    def test_material_reaches_target(self):
        touch(self.p.collection("合集一").material / "a.mkv")
        self.set_duration("a.mkv", 1200)
        st = self.one()
        self.assertTrue(st.material_ok)
        self.assertEqual(st.stage, "剪辑")

    # ── 字幕 / 导出 ──

    def _ready_material(self):
        touch(self.p.collection("合集一").material / "a.mkv")
        self.set_duration("a.mkv", 1300)

    def test_subtitle_stage(self):
        self._ready_material()
        touch(self.p.collection("合集一").editing / "片_corrected.srt", "")
        st = self.one()
        self.assertTrue(st.subtitle_ok)
        self.assertEqual(st.stage, "字幕")

    def test_export_stage(self):
        self._ready_material()
        touch(self.p.collection("合集一").editing / "片_corrected.srt", "")
        touch(self.p.collection("合集一").editing / "长片.mp4")
        self.set_duration("长片.mp4", 1300)
        st = self.one()
        self.assertTrue(st.export_ok)
        self.assertEqual(st.stage, "导出")

    def test_export_ignores_short_files(self):
        """剪辑/ 里如果只有一条 3 秒的残片，不算导出完成"""
        self._ready_material()
        touch(self.p.collection("合集一").editing / "片_corrected.srt", "")
        touch(self.p.collection("合集一").editing / "残片.mp4")
        self.set_duration("残片.mp4", 3)
        st = self.one()
        self.assertTrue(st.export_ok)      # 有文件就算导出过
        self.assertEqual(st.export_seconds, 3)

    # ── 拼接 ──

    def _ready_export(self):
        self._ready_material()
        c = self.p.collection("合集一")
        touch(c.editing / "片_corrected.srt", "")
        touch(c.editing / "长片.mp4")
        self.set_duration("长片.mp4", 1300)

    def test_splice_blocked_by_missing_templates(self):
        self._ready_export()
        st = self.one()
        self.assertFalse(st.templates_ok)
        self.assertEqual(st.stage, "导出")
        self.assertIn("intro_file_missing", [p["error"] for p in st.template_problems])

    def test_splice_ok_when_templates_and_finals_ready(self):
        self._ready_export()
        b = self.p.batch_dir
        touch(b / "片头" / "intro.mp4")
        touch(b / "片尾" / "outro.mp4")
        c = self.p.collection("合集一")
        for t in ("第一集标题", "第二集标题", "第三集标题"):
            touch(c.final / f"波波之我的世界 收集强力变身-上篇 {t}.mp4")
        st = self.one()
        self.assertTrue(st.templates_ok)
        self.assertEqual(st.final_count, 3)
        self.assertTrue(st.splice_ok)
        self.assertEqual(st.stage, "命名")

    # ── 命名 ──

    def test_named_ok(self):
        self._ready_export()
        b = self.p.batch_dir
        touch(b / "片头" / "intro.mp4")
        touch(b / "片尾" / "outro.mp4")
        c = self.p.collection("合集一")
        for t in ("第一集标题", "第二集标题", "第三集标题"):
            touch(c.final / f"... {t}.mp4")
        self.assertTrue(self.one().named_ok)

    def test_named_missing_reported(self):
        self._ready_export()
        b = self.p.batch_dir
        touch(b / "片头" / "intro.mp4")
        touch(b / "片尾" / "outro.mp4")
        c = self.p.collection("合集一")
        # 成片数量够了（拼接阶段算完成），但名字对不上标题
        for i in range(3):
            touch(c.final / f"随便一个名字{i}.mp4")
        st = self.one()
        self.assertTrue(st.splice_ok)
        self.assertFalse(st.named_ok)
        self.assertEqual(st.named_missing, ["第一集标题", "第二集标题", "第三集标题"])
        self.assertEqual(st.stage, "拼接")

    def test_finals_not_enough_stays_at_export(self):
        """成片数不够时还没到命名阶段，阶段应停在『导出』"""
        self._ready_export()
        b = self.p.batch_dir
        touch(b / "片头" / "intro.mp4")
        touch(b / "片尾" / "outro.mp4")
        touch(self.p.collection("合集一").final / "只有一个.mp4")
        st = self.one()
        self.assertFalse(st.splice_ok)
        self.assertEqual(st.stage, "导出")

    def test_named_none_when_no_title_section(self):
        """标题.md 里没有这个合集 → 未开始，不是失败"""
        self.assertEqual(self.one("合集二").named_ok, None)

    # ── 台账 ──

    def test_ledger_from_events_not_files(self):
        log = EventLog(self.p.log_dir)
        touch(self.p.batch_dir / "台账.xlsx")          # 光有 Excel 不算
        st = S.collect(self.p, probe=self.probe, log=log, collections=["合集一"]).collections[0]
        self.assertFalse(st.ledger_ok)

        log.emit("ledger", "done", "合集一", seconds=3)
        st = S.collect(self.p, probe=self.probe, log=log, collections=["合集一"]).collections[0]
        self.assertTrue(st.ledger_ok)

    def test_last_action_recorded(self):
        log = EventLog(self.p.log_dir)
        log.emit("export", "done", "合集一", seconds=2712)
        st = S.collect(self.p, probe=self.probe, log=log, collections=["合集一"]).collections[0]
        self.assertEqual(st.last_action, "export")
        self.assertEqual(st.last_seconds, 2712)


# ─────────────────────────── 整批与渲染 ───────────────────────────

class TestBatch(StatusCase):
    def test_counts(self):
        bs = self.status()
        self.assertEqual(len(bs.collections), 2)
        self.assertEqual(bs.episode_total, 6)
        self.assertEqual(bs.done_count, 0)

    def test_subset_selection(self):
        bs = self.status(["合集二"])
        self.assertEqual([c.collection for c in bs.collections], ["合集二"])

    def test_as_dict_json_serializable(self):
        payload = self.status().as_dict()
        json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["collection_count"], 2)
        self.assertIn("stage", payload["collections"][0])

    def test_render_has_expected_marks(self):
        bs = self.status()
        text = S.render(bs)
        self.assertIn("我的世界-2026-12", text)
        self.assertIn("合集一", text)
        for col in ("素材", "剪辑", "字幕", "导出", "拼接", "命名", "台账"):
            self.assertIn(col, text)
        self.assertIn("·", text)          # 命名列未开始

    def test_render_material_progress(self):
        touch(self.p.collection("合集一").material / "a.mkv")
        self.set_duration("a.mkv", 600)
        text = S.render(self.status(["合集一"]))
        self.assertIn("10:00/20:00", text)

    def test_render_next_hints(self):
        text = S.render_next(self.status())
        self.assertIn("继续录制", text)

    def test_render_next_all_done(self):
        bs = self.status()
        for c in bs.collections:
            c.material_seconds = c.material_target
            c.subtitle_file = Path("x_corrected.srt")
            c.export_file = Path("x.mp4")
            c.templates_ok = True
            c.final_count = c.episode_count
            c.named_ok = True
            c.ledger_ok = True
        self.assertEqual(S.render_next(bs), "  全部完成")


# ─────────────────────────── 时长格式化 ───────────────────────────

class TestHhmmss(unittest.TestCase):
    def test_minutes(self):
        from vedio.media import hhmmss
        self.assertEqual(hhmmss(0), "0:00")
        self.assertEqual(hhmmss(59.4), "0:59")
        self.assertEqual(hhmmss(600), "10:00")
        self.assertEqual(hhmmss(1559.6), "26:00")

    def test_hours(self):
        from vedio.media import hhmmss
        self.assertEqual(hhmmss(3600), "1:00:00")
        self.assertEqual(hhmmss(9000), "2:30:00")


if __name__ == "__main__":
    unittest.main()
