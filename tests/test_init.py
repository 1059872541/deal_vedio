# -*- coding: utf-8 -*-
"""vedio/stages/init.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - 用临时 conf/ 与临时工作区，不碰真文件
    - 两层合并（默认 + 游戏差异）与覆盖项都验
    - 建完之后必须能被 `context.Project.open` 正确读出（闭环）
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import yaml  # noqa: E402

from vedio import context  # noqa: E402
from vedio.stages import init as I  # noqa: E402


DEFAULT_RULES = """\
duration:
  material_per_collection: 7200
  episode_body: 360
  episode_count: 20
  segment_tolerance: 3
export:
  resolution: 1080P
  bitrate: 推荐
  codec: H.264
  format: mp4
  framerate: 30fps
  timeout_seconds: 10800
  pause_between: 10
naming:
  collection: "{host}之{game} {subtitle}"
  episode: "第{cn_ep}集 {title}"
  file: "{collection} {episode}.mp4"
netdisk:
  path: "/{month}/{host}/{game}/{collection}/{filename}"
meta:
  category: 端游
encode:
  encoder_priority: [h264_qsv, libx264]
  quality: 23
  preset: medium
  pix_fmt: yuv420p
  audio_codec: aac
  audio_bitrate: 128k
"""

GAME_DIFF = """\
duration:
  material_per_collection: 9000
  episode_body: 450
"""


class InitCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.conf = self.tmp / "conf"
        (self.conf / "游戏规则").mkdir(parents=True)
        (self.conf / "默认规则.yaml").write_text(DEFAULT_RULES, encoding="utf-8")
        self.ws = self.tmp / "工作区"
        self.ws.mkdir()

    def write_diff(self, game="我的世界", text=GAME_DIFF):
        (self.conf / "游戏规则" / f"{game}.yaml").write_text(text, encoding="utf-8")

    def plan(self, **kw):
        kw.setdefault("conf_dir", self.conf)
        kw.setdefault("workspace_root", self.ws)
        return I.build_plan("我的世界", "2026-12", **kw)


# ─────────────────────────── 规则装载 ───────────────────────────

class TestRules(InitCase):
    def test_default_only(self):
        rules = I.load_rules(self.conf, "我的世界")
        self.assertEqual(rules["duration"]["episode_body"], 360)
        self.assertEqual(rules["meta"]["category"], "端游")

    def test_game_diff_overrides(self):
        self.write_diff()
        rules = I.load_rules(self.conf, "我的世界")
        self.assertEqual(rules["duration"]["material_per_collection"], 9000)
        self.assertEqual(rules["duration"]["episode_body"], 450)
        # 没写的键沿用默认
        self.assertEqual(rules["duration"]["episode_count"], 20)

    def test_merge_is_copy_not_reference(self):
        rules = I.load_rules(self.conf, "我的世界")
        rules["duration"]["episode_body"] = 1
        self.assertEqual(I.load_rules(self.conf, "我的世界")["duration"]["episode_body"], 360)

    def test_deep_merge_lists_are_replaced(self):
        merged = I.deep_merge({"a": {"l": [1, 2, 3]}}, {"a": {"l": [9]}})
        self.assertEqual(merged["a"]["l"], [9])

    def test_missing_default_rules(self):
        (self.conf / "默认规则.yaml").unlink()
        with self.assertRaises(I.InitError) as ctx:
            I.load_rules(self.conf, "我的世界")
        self.assertEqual(ctx.exception.code, "rules_missing")

    def test_diff_with_unknown_key_is_rejected(self):
        """差异文件只能覆盖已有键，不能凭空新增 —— 否则静默失效"""
        self.write_diff(text="新段:\n  x: 1\n")
        with self.assertRaises(I.InitError) as ctx:
            I.load_rules(self.conf, "我的世界")
        self.assertEqual(ctx.exception.code, "game_diff_unknown_keys")
        self.assertIn("新段", ctx.exception.message)

    def test_diff_with_nested_unknown_key_is_rejected(self):
        self.write_diff(text="duration:\n  不存在: 1\n")
        with self.assertRaises(I.InitError) as ctx:
            I.load_rules(self.conf, "我的世界")
        self.assertIn("duration.不存在", ctx.exception.message)


class TestOverrides(InitCase):
    def test_override_by_dotted_path(self):
        rules = I.apply_overrides({"a": {"b": 1}}, {"a.b": 2})
        self.assertEqual(rules["a"]["b"], 2)

    def test_override_unknown_key_rejected(self):
        with self.assertRaises(I.InitError):
            I.apply_overrides({"a": {"b": 1}}, {"a.zzz": 2})

    def test_override_does_not_mutate_source(self):
        base = {"a": {"b": 1}}
        I.apply_overrides(base, {"a.b": 2})
        self.assertEqual(base["a"]["b"], 1)


# ─────────────────────────── 计划 ───────────────────────────

class TestPlan(InitCase):
    def test_dirs_cover_tree(self):
        plan = self.plan(collections=2)
        names = {p.relative_to(plan.batch_dir).as_posix() for p in plan.dirs}
        for expected in ("素材库", "片头", "片尾", "术语库", "log", "合集"):
            self.assertIn(expected, names)
        for cname in ("合集一", "合集二"):
            for sub in ("素材", "剪辑", "成片"):
                self.assertIn(f"合集/{cname}/{sub}", names)

    def test_four_files(self):
        plan = self.plan()
        self.assertEqual(
            sorted(p.name for p in plan.files),
            sorted([I.RULES_FILE, I.MANIFEST_FILE, I.TITLES_FILE, "进度.md"]))

    def test_batch_dir_uses_compound_name(self):
        plan = self.plan()
        self.assertEqual(plan.batch_dir.name, "我的世界-2026-12")

    def test_existing_batch_rejected(self):
        plan = self.plan()
        I.apply(plan)
        with self.assertRaises(I.InitError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "batch_exists")

    def test_bad_args(self):
        for kw, code in (({"collections": 0}, "bad_collections"),):
            with self.assertRaises(I.InitError) as ctx:
                self.plan(**kw)
            self.assertEqual(ctx.exception.code, code)

    def test_host_goes_into_meta(self):
        plan = self.plan(host="波波")
        self.assertEqual(plan.rules["meta"]["host"], "波波")

    def test_diff_then_override(self):
        self.write_diff()
        plan = self.plan(overrides={"duration.episode_body": 500})
        self.assertEqual(plan.rules["duration"]["episode_body"], 500)
        self.assertEqual(plan.rules["duration"]["material_per_collection"], 9000)


# ─────────────────────────── 渲染内容 ───────────────────────────

class TestRender(InitCase):
    def test_game_yaml_is_complete_and_commented(self):
        self.write_diff()
        plan = self.plan(host="波波")
        text = plan.files[plan.batch_dir / I.RULES_FILE]
        data = yaml.safe_load(text.split("# ═════", 1)[-1] if False else text)
        self.assertEqual(data["game"], "我的世界")
        self.assertEqual(data["batch"], "2026-12")
        self.assertEqual(data["collections"], 1)
        self.assertEqual(data["meta"]["host"], "波波")
        self.assertEqual(data["duration"]["episode_body"], 450)
        self.assertIn("# ── 时长", text)

    def test_game_yaml_has_no_late_bound_sections(self):
        """templates / collection_names 属于 合集清单.yaml 与 标题.md"""
        plan = self.plan()
        text = plan.files[plan.batch_dir / I.RULES_FILE]
        self.assertNotIn("templates:", text)
        self.assertNotIn("collection_names:", text)

    def test_manifest_skeleton(self):
        plan = self.plan()
        text = plan.files[plan.batch_dir / I.MANIFEST_FILE]
        data = yaml.safe_load(text)
        self.assertEqual(data["drafts"], {})
        self.assertIsNone(data["templates"]["outro"])

    def test_titles_prefix(self):
        plan = self.plan(host="波波")
        text = plan.files[plan.batch_dir / I.TITLES_FILE]
        self.assertIn("# 我的世界系列视频标题列表", text)
        self.assertIn("公共前缀:波波之我的世界", text)


# ─────────────────────────── 落盘 + 闭环 ───────────────────────────

class TestApply(InitCase):
    def test_creates_everything_and_reopens(self):
        plan = self.plan(collections=2, host="波波")
        result = I.apply(plan)
        self.assertTrue(result["ok"])
        self.assertTrue(plan.batch_dir.is_dir())
        for d in plan.dirs:
            self.assertTrue(d.is_dir(), d)

        # 闭环：建完之后 context 必须认得
        project = context.Project.open("我的世界", "2026-12",
                                       local={"workspace": {"root": str(self.ws)}})
        self.assertEqual(project.collection_names(), ["合集一", "合集二"])
        self.assertEqual(project.missing_dirs(), [])
        self.assertEqual(project.material_target, 9000 if False else 7200)
        self.assertEqual(project.episode_body, 360)
        self.assertEqual(project.host, "波波")
        self.assertEqual(project.rules["export"]["framerate"], "30fps")

    def test_apply_is_idempotent_for_dirs(self):
        plan = self.plan()
        I.apply(plan)
        result = I.apply(plan)              # 再来一次不该炸
        self.assertEqual(result["created_dirs"], 0)

    def test_apply_writes_event(self):
        from vedio.events import EventLog
        plan = self.plan()
        log = EventLog(plan.batch_dir / "log")
        I.apply(plan, log=log)
        events = log.read()
        self.assertEqual([e.verb for e in events], ["init"])
        self.assertEqual(events[0].event, "done")


# ─────────────────────────── 进度表 ───────────────────────────

class TestProgressAtInit(InitCase):
    def test_init_creates_progress_table(self):
        """批次一建好就该有地方记进度 —— 全 `·` 等着打勾"""
        from vedio import progress as P
        plan = self.plan(collections=2, host="波波")
        I.apply(plan)
        path = plan.batch_dir / P.FILE_NAME
        self.assertTrue(path.is_file())
        table = P.ProgressTable.load(path)
        self.assertEqual(table.collections(), ["合集一", "合集二"])
        self.assertTrue(all(C == P.EMPTY for C in table.rows[0][1:]))

    def test_progress_lists_ignored(self):
        from vedio import progress as P
        plan = self.plan(collections=1)
        plan.rules["ignore_collections"] = ["合集九"]
        text = I.render_progress(plan)
        self.assertIn("已忽略", text)
        self.assertIn("`合集九`", text)


# ─────────────────────────── 给已有批次加合集 ───────────────────────────

class TestAddCollections(InitCase):
    def setUp(self):
        super().setUp()
        self.plan0 = self.plan(collections=2, host="波波")
        I.apply(self.plan0)
        self.project = context.Project.open(
            "我的世界", "2026-12", local={"workspace": {"root": str(self.ws)}})

    def test_creates_dirs_and_rows(self):
        from vedio import progress as P
        result = I.add_collections(self.project, ["合集四", "合集五"])
        self.assertEqual(result["added"], ["合集四", "合集五"])
        self.assertEqual(result["already_present"], [])
        self.assertEqual(result["created_dirs"], 8)     # 2 个 × (根 + 3 子目录)
        for name in ("合集四", "合集五"):
            for sub in ("素材", "剪辑", "成片"):
                self.assertTrue((self.plan0.batch_dir / "合集" / name / sub).is_dir(), f"{name}/{sub}")
        table = P.ProgressTable.load(self.plan0.batch_dir / P.FILE_NAME)
        self.assertEqual(table.collections(), ["合集一", "合集二", "合集四", "合集五"])

    def test_reopens_as_real_collections(self):
        I.add_collections(self.project, ["合集四"])
        p2 = context.Project.open("我的世界", "2026-12",
                                  local={"workspace": {"root": str(self.ws)}})
        self.assertEqual(p2.collection_names(), ["合集一", "合集二", "合集四"])

    def test_bumps_collections_field(self):
        result = I.add_collections(self.project, ["合集四"])
        self.assertEqual(result["collections_field"], 4)
        rules = (self.plan0.batch_dir / I.RULES_FILE).read_text(encoding="utf-8")
        self.assertIn("collections: 4", rules)

    def test_does_not_touch_comments(self):
        """game.yaml 是手写带注释的，行级替换不能动别的内容"""
        before = (self.plan0.batch_dir / I.RULES_FILE).read_text(encoding="utf-8")
        I.add_collections(self.project, ["合集四"])
        after = (self.plan0.batch_dir / I.RULES_FILE).read_text(encoding="utf-8")
        # 除了 collections 那一行，其余完全一致
        diff_before = [l for l in before.splitlines() if not l.startswith("collections:")]
        diff_after = [l for l in after.splitlines() if not l.startswith("collections:")]
        self.assertEqual(diff_before, diff_after)

    def test_idempotent(self):
        I.add_collections(self.project, ["合集四"])
        again = I.add_collections(self.project, ["合集四"])
        self.assertEqual(again["added"], [])
        self.assertEqual(again["already_present"], ["合集四"])
        self.assertIsNone(again["collections_field"])

    def test_does_not_delete_existing_dirs(self):
        marker = self.plan0.batch_dir / "合集" / "合集一" / "素材" / "keep.txt"
        marker.write_text("x", encoding="utf-8")
        I.add_collections(self.project, ["合集四"])
        self.assertTrue(marker.is_file())

    def test_fills_missing_subdir_only(self):
        """已经有 剪辑/ 的目录（比如测试素材），只补缺的"""
        partial = self.plan0.batch_dir / "合集" / "合集九" / "剪辑"
        partial.mkdir(parents=True)
        (partial / "a.srt").write_text("x", encoding="utf-8")
        I.add_collections(self.project, ["合集九"])
        self.assertTrue((self.plan0.batch_dir / "合集" / "合集九" / "素材").is_dir())
        self.assertTrue((partial / "a.srt").is_file())

    def test_invalid_name(self):
        with self.assertRaises(I.InitError) as ctx:
            I.add_collections(self.project, ["合集四号"])
        self.assertEqual(ctx.exception.code, "bad_collection_name")

    def test_empty_names(self):
        with self.assertRaises(I.InitError) as ctx:
            I.add_collections(self.project, [])
        self.assertEqual(ctx.exception.code, "no_collections")

    def test_missing_batch(self):
        """game.yaml 没了就当批次不存在（不猜别的目录凑合）"""
        (self.plan0.batch_dir / I.RULES_FILE).unlink()
        with self.assertRaises(I.InitError) as ctx:
            I.add_collections(self.project, ["合集四"])
        self.assertEqual(ctx.exception.code, "batch_not_found")

    def test_event_recorded(self):
        from vedio.events import EventLog
        log = EventLog(self.plan0.batch_dir / "log")
        I.add_collections(self.project, ["合集四"], log=log)
        last = log.last(verb="init")
        self.assertEqual(last.fields["mode"], "add")
        self.assertEqual(last.fields["collections"], ["合集四"])

    def test_rebuilds_broken_progress_table(self):
        from vedio import progress as P
        (self.plan0.batch_dir / P.FILE_NAME).write_text("坏了\n", encoding="utf-8")
        result = I.add_collections(self.project, ["合集四"])
        self.assertTrue(result["progress_rebuilt"])
        self.assertTrue((self.plan0.batch_dir / (P.FILE_NAME + ".bak")).is_file())
        table = P.ProgressTable.load(self.plan0.batch_dir / P.FILE_NAME)
        self.assertIn("合集四", table.collections())


if __name__ == "__main__":
    unittest.main()
