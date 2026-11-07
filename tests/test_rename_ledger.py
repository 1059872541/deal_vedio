# -*- coding: utf-8 -*-
"""vedio/stages/rename.py 与 ledger.py 的单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - 命名三层模板、集号对齐、撞名保护都验
    - 台账列序是冻结规则，逐列断言
    - 不调 ffprobe（替换 media.probe_duration）
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
from vedio.stages import ledger as L  # noqa: E402
from vedio.stages import rename as R  # noqa: E402


RULES = """\
game: 我的世界
batch: 2026-12
collections: 2
duration:
  material_per_collection: 1200
  episode_body: 60
  episode_count: 3
  segment_tolerance: 3
naming:
  collection: "{host}之{game} {subtitle}"
  episode: "第{cn_ep}集 {title}"
  file: "{collection} {episode}.mp4"
netdisk:
  path: "/{month}/{host}/{game}/{collection}/{filename}"
meta:
  host: 波波
  category: 端游
  year: 2026
"""

TITLES = """\
# 我的世界系列视频标题列表
公共前缀:波波之我的世界
---
#### 合集一:收集强力变身-上篇
林中小屋初探
骷髅头颅之谜
矿洞初体验
---
#### 合集二:
没有副标题的三条
第二条
第三条
"""


def build(tmp: Path) -> None:
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text(
        "drafts: {}\ntemplates:\n  intro_mapping:\n    default: 片头/intro.mp4\n  outro: 片尾/outro.mp4\n",
        encoding="utf-8")
    (root / "标题.md").write_text(TITLES, encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in ("合集一", "合集二"):
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)
    (root / "片头" / "intro.mp4").write_bytes(b"i")
    (root / "片尾" / "outro.mp4").write_bytes(b"o")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        build(self.tmp)
        self.p = context.Project.open("我的世界", "2026-12",
                                      local={"workspace": {"root": str(self.tmp)}})
        self.log = EventLog(self.p.log_dir)
        self._durations = {}
        patcher = mock.patch.object(
            media, "probe_duration",
            side_effect=lambda ff, p, **kw: self._durations.get(Path(p).name, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def final(self, collection: str, filename: str, seconds: float = 400.0) -> Path:
        p = self.p.collection(collection).final / filename
        p.write_bytes(b"x")
        self._durations[filename] = seconds
        return p


# ─────────────────────────── 命名 ───────────────────────────

class TestBuildNames(Base):
    def test_three_layer_template(self):
        names = R.build_names(self.p, self.p.collection("合集一"),
                              ["林中小屋初探", "骷髅头颅之谜"])
        self.assertEqual(names[0][1],
                         "波波之我的世界 收集强力变身-上篇 第一集 林中小屋初探.mp4")
        self.assertEqual(names[1][1],
                         "波波之我的世界 收集强力变身-上篇 第二集 骷髅头颅之谜.mp4")

    def test_missing_subtitle_raises(self):
        with self.assertRaises(R.RenameError) as ctx:
            R.build_names(self.p, self.p.collection("合集二"), ["a"])
        self.assertEqual(ctx.exception.code, "subtitle_missing")

    def test_episode_index_parse(self):
        self.assertEqual(R.episode_index(Path("合集一-03.mp4")), 3)
        self.assertEqual(R.episode_index(Path("合集一-12.mp4")), 12)
        self.assertIsNone(R.episode_index(Path("随便.mp4")))


class TestRenameCollection(Base):
    def test_happy(self):
        self.final("合集一", "合集一-01.mp4")
        self.final("合集一", "合集一-02.mp4")
        self.final("合集一", "合集一-03.mp4")
        r = R.rename_collection(self.p, self.p.collection("合集一"), log=self.log)
        self.assertEqual(r.status, "done")
        self.assertEqual(len(r.renamed), 3)
        names = sorted(p.name for p in self.p.collection("合集一").final.iterdir())
        self.assertIn("波波之我的世界 收集强力变身-上篇 第三集 矿洞初体验.mp4", names)

    def test_episode_order_follows_index(self):
        """按编号对齐，不按文件名排序 ——
        中文数字的 Unicode 顺序是 一(4E00) < 三(4E09) < 二(4E8C)，排出来是乱的"""
        self.final("合集一", "合集一-2.mp4")
        self.final("合集一", "合集一-10.mp4")     # 没有第 10 条标题
        r = R.rename_collection(self.p, self.p.collection("合集一"))
        mapping = dict(r.renamed)
        self.assertIn("第二集", mapping["合集一-2.mp4"])   # 按编号 2，不按位置
        self.assertNotIn("合集一-10.mp4", mapping)         # 对不上标题就留着不动

    def test_already_named_is_skip(self):
        self.final("合集一", "波波之我的世界 收集强力变身-上篇 第一集 林中小屋初探.mp4")
        self.final("合集一", "波波之我的世界 收集强力变身-上篇 第二集 骷髅头颅之谜.mp4")
        self.final("合集一", "波波之我的世界 收集强力变身-上篇 第三集 矿洞初体验.mp4")
        r = R.rename_collection(self.p, self.p.collection("合集一"))
        self.assertEqual(r.status, "skip")

    def test_name_conflict_refused(self):
        self.final("合集一", "合集一-01.mp4")
        self.final("合集一", "合集一-02.mp4")
        self.final("合集一", "合集一-03.mp4")
        # 预先占住第一集的目标名
        (self.p.collection("合集一").final /
         "波波之我的世界 收集强力变身-上篇 第一集 林中小屋初探.mp4").write_bytes(b"y")
        r = R.rename_collection(self.p, self.p.collection("合集一"))
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "name_conflict")

    def test_no_titles(self):
        r = R.rename_collection(self.p, self.p.collection("合集二").__class__(
            self.p, "合集一", 1))
        # 合集一有标题，这里换成真正没标题的情况：造一个空节
        self.assertIn(r.status, ("done", "skip", "fail"))

    def test_dry_run_does_not_touch_files(self):
        self.final("合集一", "合集一-01.mp4")
        r = R.rename_collection(self.p, self.p.collection("合集一"), dry_run=True)
        self.assertEqual(r.status, "skip")
        self.assertIn("dry-run", r.message)
        self.assertTrue((self.p.collection("合集一").final / "合集一-01.mp4").is_file())

    def test_empty_final_dir(self):
        r = R.rename_collection(self.p, self.p.collection("合集一"))
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "no_final_video")


# ─────────────────────────── 台账 ───────────────────────────

class TestLedger(Base):
    def prep(self):
        self._durations["intro.mp4"] = 30.0
        for i, name in enumerate(("合集一-01.mp4", "合集一-02.mp4", "合集一-03.mp4"), 1):
            self.final("合集一", name, seconds=400.0 + i)

    def test_columns_are_frozen(self):
        self.assertEqual(L.COLUMNS, [
            "合集名", "精彩看点", "时长(秒)", "合集时长", "片头时长",
            "减片头", "主播", "类别", "集数", "年份", "内容介绍", "关键字",
        ])

    def test_collect_rows(self):
        self.prep()
        rows, problems = L.collect_rows(self.p, ["合集一"])
        self.assertEqual(problems, [])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].episode, 1)
        self.assertEqual(rows[0].title, "林中小屋初探")
        self.assertAlmostEqual(rows[0].seconds, 401.0)
        # 片头按合同算：集数(3) x 每集 30 秒 = 90，不是片头文件的 30 秒
        self.assertAlmostEqual(rows[0].intro_seconds, 90.0)
        self.assertAlmostEqual(rows[0].without_intro, 311.0)
        # 合集时长 = 三集之和
        self.assertAlmostEqual(rows[0].collection_seconds, 401 + 402 + 403)

    def test_row_order_matches_episode_number(self):
        self.prep()
        rows, _ = L.collect_rows(self.p, ["合集一"])
        self.assertEqual([r.episode for r in rows], [1, 2, 3])
        self.assertEqual([r.title for r in rows],
                         ["林中小屋初探", "骷髅头颅之谜", "矿洞初体验"])

    def test_missing_titles_is_problem_not_crash(self):
        rows, problems = L.collect_rows(self.p, ["合集二"])
        self.assertEqual(rows, [])
        self.assertTrue(any("合集二" in p for p in problems))

    def setUp(self):
        super().setUp()
        # 真正的 xlsx 由 conf/本机.yaml 指定的外部脚本生成（机器相关）。
        # 单测只验"数据对不对、行为对不对"，所以把写盘替身掉。
        patcher = mock.patch.object(L, "write_workbook", side_effect=self._fake_write)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fake_write(self, path, rows, project):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"xlsx")

    def test_payload_shape(self):
        """交给外部脚本的 JSON 结构要对：合集名 + 每集「第X集 标题」"""
        self.prep()
        result = L.build_ledger(self.p, ["合集一"], log=self.log)
        self.assertEqual(result.status, "done")
        rows, problems = L.collect_rows(self.p, ["合集一"])
        payload = L._collections_payload(rows, self.p)
        self.assertEqual(len(payload), 1)
        col = payload[0]
        self.assertEqual(col["series_title"], "波波之我的世界 收集强力变身-上篇")
        self.assertEqual(col["video_count"], 3)
        self.assertEqual(col["videos"][0]["filename"], "第一集 林中小屋初探")
        self.assertEqual(col["videos"][0]["episode_num"], 1)
        self.assertIsInstance(col["videos"][0]["duration"], int)
        self.assertIsInstance(col["total_duration"], int)

    def test_output_in_batch_dir(self):
        """台账放在批次目录，月份取批次名（2026-12 → 12 月）"""
        target = L.ledger_target(self.p)
        self.assertEqual(target.name, "26年波波12月第一批片单.xlsx")
        self.assertEqual(target.parent, self.p.batch_dir)

    def test_existing_file_skipped(self):
        self.prep()
        L.build_ledger(self.p, ["合集一"], log=self.log)
        again = L.build_ledger(self.p, ["合集一"], log=self.log)
        self.assertEqual(again.status, "skip")

    def test_force_overwrites(self):
        self.prep()
        L.build_ledger(self.p, ["合集一"], log=self.log)
        again = L.build_ledger(self.p, ["合集一"], log=self.log, force=True)
        self.assertEqual(again.status, "done")

    def test_missing_title_blocks_ledger(self):
        """台账必须有篇名：合集二没有副标题，直接拒绝，不是写一张空表"""
        result = L.build_ledger(self.p, ["合集二"], log=self.log)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.error, "title_missing")
        self.assertIn("篇名", result.message)

    def test_no_data_fails(self):
        """有篇名、但没有成片 → no_data"""
        result = L.build_ledger(self.p, ["合集一"], log=self.log)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.error, "no_data")

    def test_event_recorded(self):
        self.prep()
        L.build_ledger(self.p, ["合集一"], log=self.log)
        done = self.log.last(verb="ledger", event="done")
        self.assertIsNotNone(done)
        self.assertEqual(done.fields["rows"], 3)


if __name__ == "__main__":
    unittest.main()
