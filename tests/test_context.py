# -*- coding: utf-8 -*-
"""vedio/context.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

特点：
    - 不读 conf/本机.yaml：LocalConfig 由字典注入，换电脑也能跑
    - 不碰真实视频：全部在临时目录里造目录与占位文件
    - 重点守护「目录树唯一真相」：建目录用的常量和查目录用的属性必须对得上
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import context as C  # noqa: E402


# ─────────────────────────── 测试脚手架 ───────────────────────────

RULES = """\
game: 我的世界
batch: 2026-12
collections: 3
duration:
  material_per_collection: 9000
  episode_body: 450
  episode_count: 20
  segment_tolerance: 3
naming:
  collection: "波波之我的世界 {subtitle}"
  episode: "第{cn_ep}集 {title}"
  file: "{collection} {episode}.mp4"
meta:
  host: 波波
  category: 端游
  year: 2026
"""

MANIFEST = """\
drafts:
  合集一: MC-合集一
  合集二: MC-合集二
templates:
  intro_mapping:
    合集九: 片头/2026-06-MC-9-10-开头.mp4
    default: 片头/2026-06-MC-开头-合集-1-3.mp4
  outro: 片尾/2026-06-MC-结尾.mp4
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
#### 合集二:收集强力变身-中篇
夜视药水配方
幽灵穿墙术
"""


def build_batch(
    tmp,
    game="我的世界",
    batch="2026-12",
    collections=("合集一", "合集二"),
    rules=RULES,
    manifest=None,
    titles=None,
    make_dirs=True,
):
    """在 tmp 下造一个合规批次，返回可直接喂给 Project.open 的 local 配置字典"""
    root = Path(tmp) / f"{game}-{batch}"
    root.mkdir(parents=True, exist_ok=True)
    if rules is not None:
        (root / C.RULES_FILE).write_text(rules, encoding="utf-8")
    if manifest is not None:
        (root / C.MANIFEST_FILE).write_text(manifest, encoding="utf-8")
    if titles is not None:
        (root / C.TITLES_FILE).write_text(titles, encoding="utf-8")
    if make_dirs:
        for d in C.BATCH_TREE:
            (root / d).mkdir(exist_ok=True)
        for name in collections:
            for sub in C.COLLECTION_TREE:
                (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)
    return {"workspace": {"root": str(tmp)}}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # 隔离真实机器：默认认为"这台机器没装剪映 / 没有索引"。
        # 不这么做的话，开发机上真实存在的草稿会漏进测试结果。
        patcher = mock.patch.object(C, "jianying_index_paths", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def open(self, **kw):
        local = build_batch(self.tmp, **kw)
        return C.Project.open("我的世界", "2026-12", local=local)


# ─────────────────────────── 合集编号 ───────────────────────────

class TestCollectionNumbering(unittest.TestCase):
    def test_index_parses_chinese_numerals(self):
        self.assertEqual(C.collection_index("合集一"), 1)
        self.assertEqual(C.collection_index("合集十"), 10)
        self.assertEqual(C.collection_index("合集十二"), 12)
        self.assertEqual(C.collection_index("合集二十三"), 23)
        self.assertEqual(C.collection_index("合集九十九"), 99)

    def test_index_rejects_bad_names(self):
        for bad in ("合集", "合集十零", "概念图", "合集10", "", "素材"):
            self.assertIsNone(C.collection_index(bad), bad)

    def test_index_tolerates_surrounding_space(self):
        self.assertEqual(C.collection_index("  合集七 "), 7)

    def test_name_generates_reverse(self):
        self.assertEqual(C.collection_name(1), "合集一")
        self.assertEqual(C.collection_name(20), "合集二十")
        self.assertEqual(C.collection_name(99), "合集九十九")

    def test_round_trip(self):
        for i in (1, 2, 9, 10, 11, 20, 21, 33, 99):
            self.assertEqual(C.collection_index(C.collection_name(i)), i)


# ─────────────────────────── 本机配置 ───────────────────────────

class TestLocalConfig(unittest.TestCase):
    def test_missing_workspace_root_raises(self):
        with self.assertRaises(C.LocalConfigError) as ctx:
            C.LocalConfig.from_dict({})
        self.assertEqual(ctx.exception.code, "local_config_error")
        self.assertIn("workspace.root", ctx.exception.message)

    def test_defaults(self):
        cfg = C.LocalConfig.from_dict({"workspace": {"root": "/tmp/ws"}})
        self.assertEqual(cfg.ffmpeg, "ffmpeg")
        self.assertEqual(cfg.ffprobe, "ffprobe")
        self.assertIsNone(cfg.draft_dir)
        self.assertEqual(cfg.window_title, "剪映专业版")

    def test_empty_draft_dir_becomes_none(self):
        cfg = C.LocalConfig.from_dict(
            {"workspace": {"root": "/tmp/ws"}, "jianying": {"draft_dir": "   "}}
        )
        self.assertIsNone(cfg.draft_dir)

    def test_full(self):
        cfg = C.LocalConfig.from_dict({
            "workspace": {"root": "/tmp/ws"},
            "jianying": {"draft_dir": "/tmp/drafts", "window_title": "JY"},
            "tool": {"ffmpeg": "C:/ffmpeg.exe", "ffprobe": "C:/ffprobe.exe"},
        })
        self.assertEqual(cfg.draft_dir, Path("/tmp/drafts"))
        self.assertEqual(cfg.ffmpeg, "C:/ffmpeg.exe")
        self.assertEqual(cfg.window_title, "JY")


# ─────────────────────────── 打开批次 ───────────────────────────

class TestProjectOpen(TempDirCase):
    def test_batch_name_is_compound(self):
        self.assertEqual(C.Project.batch_name("我的世界", "2026-12"), "我的世界-2026-12")

    def test_missing_batch_raises(self):
        local = {"workspace": {"root": str(self.tmp)}}
        with self.assertRaises(C.BatchNotFound) as ctx:
            C.Project.open("我的世界", "2026-12", local=local)
        self.assertEqual(ctx.exception.code, "batch_not_found")

    def test_missing_game_yaml_raises_not_initialized(self):
        root = self.tmp / "我的世界-2026-12"
        root.mkdir(parents=True)
        (root / "合集").mkdir()
        with self.assertRaises(C.NotInitialized) as ctx:
            C.Project.open("我的世界", "2026-12", local={"workspace": {"root": str(self.tmp)}})
        self.assertEqual(ctx.exception.code, "not_initialized")

    def test_opens_with_minimal_batch(self):
        p = self.open(collections=(), manifest=None, titles=None)
        self.assertEqual(p.name, "我的世界-2026-12")
        self.assertEqual(p.game, "我的世界")
        self.assertEqual(p.batch, "2026-12")

    def test_reads_rules_with_bom(self):
        local = build_batch(self.tmp, rules="\ufeff" + RULES)
        p = C.Project.open("我的世界", "2026-12", local=local)
        self.assertEqual(p.episode_count, 20)

    def test_convenience_rule_accessors(self):
        p = self.open()
        self.assertEqual(p.episode_count, 20)
        self.assertEqual(p.episode_body, 450)
        self.assertEqual(p.material_target, 9000)
        self.assertEqual(p.tolerance, 3)
        self.assertEqual(p.host, "波波")

    def test_rule_dotted_default(self):
        p = self.open()
        self.assertIsNone(p.rule("duration.nope"))
        self.assertEqual(p.rule("duration.nope", 7), 7)
        self.assertEqual(p.rule("a.b.c", "d"), "d")


# ─────────────────────────── 路径（唯一真相） ───────────────────────────

class TestPaths(TempDirCase):
    def test_batch_level_paths_all_under_batch_dir(self):
        p = self.open()
        for attr in ("rules_file", "manifest_file", "titles_file", "ledger_file",
                     "collections_dir", "intro_dir", "outro_dir",
                     "assets_dir", "glossary_dir", "log_dir"):
            path = getattr(p, attr)
            self.assertTrue(str(path).startswith(str(p.batch_dir)), f"{attr} 跑出批次目录了")

    def test_expected_file_names(self):
        p = self.open()
        self.assertEqual(p.rules_file.name, "game.yaml")
        self.assertEqual(p.manifest_file.name, "合集清单.yaml")
        self.assertEqual(p.titles_file.name, "标题.md")
        self.assertEqual(p.ledger_file.name, "台账.xlsx")

    def test_intro_outro_are_batch_level_not_inside_collection(self):
        """片头片尾是合集组共用的一套，绝不能落在 合集/合集X/ 下面。"""
        p = self.open()
        c = p.collection("合集一")
        self.assertEqual(p.intro_dir, p.batch_dir / "片头")
        self.assertEqual(p.outro_dir, p.batch_dir / "片尾")
        # 片头片尾目录不应在 合集/ 之下
        self.assertNotEqual(p.intro_dir.parent, p.collections_dir)
        self.assertNotEqual(p.outro_dir.parent, p.collections_dir)
        # 合集目录里只有 素材/剪辑/成片 三个子目录
        self.assertEqual(sorted(x.name for x in c.root.iterdir()), sorted(C.COLLECTION_TREE))

    def test_collection_paths(self):
        p = self.open()
        c = p.collection("合集一")
        base = p.batch_dir / "合集" / "合集一"
        self.assertEqual(c.root, base)
        self.assertEqual(c.material, base / "素材")
        self.assertEqual(c.editing, base / "剪辑")
        self.assertEqual(c.final, base / "成片")

    def test_collection_does_not_have_titles_file(self):
        """标题是批次级单文件，合集目录下不应再有 标题.md。"""
        p = self.open()
        c = p.collection("合集一")
        self.assertFalse((c.root / "标题.md").exists())
        self.assertEqual(p.titles_file.parent, p.batch_dir)

    def test_tree_constants_match_created_dirs(self):
        p = self.open()
        self.assertEqual(p.missing_dirs(), [])
        self.assertEqual(p.collection("合集一").missing_dirs(), [])


# ─────────────────────────── 合集列表与解析 ───────────────────────────

class TestCollections(TempDirCase):
    def test_sorted_by_chinese_number_not_string(self):
        names = ("合集十", "合集二", "合集一", "合集十一")
        p = self.open(collections=names)
        self.assertEqual(p.collection_names(), ["合集一", "合集二", "合集十", "合集十一"])

    def test_empty_batch(self):
        p = self.open(collections=())
        self.assertEqual(p.collections(), [])

    def test_unknown_name_raises_with_available(self):
        p = self.open()
        with self.assertRaises(C.CollectionNotFound) as ctx:
            p.collection("合集九")
        self.assertEqual(ctx.exception.code, "collection_not_found")
        self.assertEqual(ctx.exception.detail["available"], ["合集一", "合集二"])

    def test_invalid_name_raises(self):
        p = self.open()
        with self.assertRaises(C.CollectionNotFound):
            p.collection("概念图")

    def test_dir_exists_only_in_filesystem(self):
        """合集名合法但目录不存在 → 报错，不能凭空造一个。"""
        p = self.open()
        with self.assertRaises(C.CollectionNotFound):
            p.collection("合集三")

    def test_unknown_collection_dirs_reported(self):
        p = self.open()
        (p.collections_dir / "合集备份").mkdir()
        (p.collections_dir / "素材临时").mkdir()
        self.assertEqual(p.unknown_collection_dirs(), ["合集备份", "素材临时"])
        # 但合规合集不受影响
        self.assertEqual(p.collection_names(), ["合集一", "合集二"])

    def test_resolve_none_means_all(self):
        p = self.open()
        self.assertEqual([c.name for c in p.resolve_collections(None)], ["合集一", "合集二"])

    def test_resolve_empty_means_all(self):
        p = self.open()
        self.assertEqual([c.name for c in p.resolve_collections([])], ["合集一", "合集二"])

    def test_resolve_subset_in_given_order(self):
        p = self.open()
        got = [c.name for c in p.resolve_collections(["合集二", "合集一"])]
        self.assertEqual(got, ["合集二", "合集一"])

    def test_resolve_ignores_blanks(self):
        p = self.open()
        got = [c.name for c in p.resolve_collections([" 合集一 ", "", "  "])]
        self.assertEqual(got, ["合集一"])

    def test_resolve_unknown_raises(self):
        p = self.open()
        with self.assertRaises(C.CollectionNotFound):
            p.resolve_collections(["合集八"])


# ─────────────────────────── 标题与副标题 ───────────────────────────

class TestTitles(TempDirCase):
    def test_parse_prefix_subtitle_and_titles(self):
        p = self.open(titles=TITLES)
        t = p.titles
        self.assertEqual(t.prefix, "波波之我的世界")
        self.assertEqual(t.subtitle("合集一"), "收集强力变身-上篇")
        self.assertEqual(t.titles_of("合集一"), ["林中小屋初探", "骷髅头颅之谜", "矿洞初体验"])
        self.assertEqual(len(t.titles_of("合集二")), 2)

    def test_full_collection_name(self):
        p = self.open(titles=TITLES)
        self.assertEqual(p.titles.full_collection_name("合集一"), "波波之我的世界 收集强力变身-上篇")

    def test_missing_titles_file_is_empty_not_error(self):
        p = self.open(titles=None)
        self.assertIsNone(p.subtitle_for("合集一"))
        self.assertEqual(p.titles_of("合集一"), [])
        self.assertIsNone(p.titles.full_collection_name("合集一"))

    def test_unknown_collection_in_titles_file(self):
        p = self.open(titles=TITLES)
        self.assertIsNone(p.subtitle_for("合集五"))
        self.assertEqual(p.titles_of("合集五"), [])

    def test_full_width_colon(self):
        text = "公共前缀：波波之我的世界\n---\n#### 合集一：上篇\nA\nB\n"
        t = C.parse_titles(text)
        self.assertEqual(t.prefix, "波波之我的世界")
        self.assertEqual(t.subtitle("合集一"), "上篇")
        self.assertEqual(t.titles_of("合集一"), ["A", "B"])

    def test_separator_does_not_let_titles_bleed(self):
        text = "#### 合集一:上篇\nA\n---\n不属于任何合集的一行\n"
        t = C.parse_titles(text)
        self.assertEqual(t.titles_of("合集一"), ["A"])

    def test_header_without_subtitle(self):
        text = "#### 合集一\nA\n"
        t = C.parse_titles(text)
        self.assertIsNone(t.subtitle("合集一"))
        self.assertEqual(t.titles_of("合集一"), ["A"])

    def test_blank_lines_skipped(self):
        text = "#### 合集一:上篇\nA\n\nB\n\n"
        t = C.parse_titles(text)
        self.assertEqual(t.titles_of("合集一"), ["A", "B"])

    def test_reload_picks_up_changes(self):
        p = self.open(titles=TITLES)
        self.assertEqual(len(p.titles_of("合集一")), 3)
        p.titles_file.write_text("#### 合集一:改过了\n新标题\n", encoding="utf-8")
        self.assertEqual(len(p.titles_of("合集一")), 3)  # 还是缓存
        p.reload_titles()
        self.assertEqual(p.titles_of("合集一"), ["新标题"])
        self.assertEqual(p.subtitle_for("合集一"), "改过了")


# ─────────────────────────── 登记事实：草稿名 ───────────────────────────

class TestDraftRegistry(TempDirCase):
    def test_draft_from_manifest(self):
        p = self.open(manifest=MANIFEST)
        self.assertEqual(p.draft_for("合集一"), "MC-合集一")
        self.assertIsNone(p.draft_for("合集三"))

    def test_no_manifest_is_not_an_error(self):
        p = self.open(manifest=None)
        self.assertEqual(p.manifest, {})
        self.assertIsNone(p.draft_for("合集一"))

    def test_collection_exposes_draft(self):
        p = self.open(manifest=MANIFEST)
        self.assertEqual(p.collection("合集一").draft(), "MC-合集一")

    def test_available_drafts_reads_filesystem(self):
        drafts = self.tmp / "JianyingPro Drafts"
        for name in ("MC-合集一", "MC-合集二"):
            (drafts / name).mkdir(parents=True)
            (drafts / name / "draft_content.json").write_text("{}", encoding="utf-8")
        (drafts / "空目录").mkdir()  # 没有 draft_content.json，不算草稿

        local = build_batch(self.tmp, manifest=MANIFEST)
        local["jianying"] = {"draft_dir": str(drafts)}
        p = C.Project.open("我的世界", "2026-12", local=local)
        self.assertEqual(p.available_drafts(), ["MC-合集一", "MC-合集二"])

    def test_available_drafts_without_draft_dir(self):
        p = self.open()
        self.assertIsNone(p.draft_dir)
        self.assertEqual(p.available_drafts(), [])

    def test_draft_candidates_excludes_other_collections(self):
        drafts = self.tmp / "JianyingPro Drafts"
        for name in ("MC-合集一", "MC-合集二", "MC-合集三"):
            (drafts / name).mkdir(parents=True)
            (drafts / name / "draft_content.json").write_text("{}", encoding="utf-8")
        local = build_batch(self.tmp, manifest=MANIFEST)
        local["jianying"] = {"draft_dir": str(drafts)}
        p = C.Project.open("我的世界", "2026-12", local=local)
        # 合集一、二已被占，候选只剩 合集三
        self.assertEqual(p.draft_candidates("合集三"), ["MC-合集三"])
        # 合集一自己的名字仍在候选里（用于重认）
        self.assertIn("MC-合集一", p.draft_candidates("合集一"))


# ─────────────────────────── 剪映索引（草稿发现） ───────────────────────────

INDEX_ENTRY = {
    "draft_cloud_last_action_download": False,
    "draft_cover": "D:/drafts/11月7日/draft_cover.jpg",
    "draft_fold_path": "D:/drafts/11月7日",
    "draft_id": "DF7B19E3-7119-4466-8120-88B4F6E642DE",
    "draft_json_file": "D:/drafts/11月7日/draft_content.json",
    "draft_name": "MC-合集一",
    "draft_root_path": "D:\\drafts",
    "tm_duration": 1559600000,
    "tm_draft_create": 1794034023008284,
    "tm_draft_modified": 1794034039560346,
}


def write_index(path: Path, entries, root_path: str = "C:/.../com.lveditor.draft"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"all_draft_store": entries, "draft_ids": len(entries), "root_path": root_path},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class TestJianyingIndex(TempDirCase):
    """核心回归：**文件夹名 ≠ 界面显示名**。这是实测踩到的坑。"""

    def test_display_name_comes_from_index_not_folder(self):
        idx = write_index(self.tmp / "idx" / "root_meta_info.json", [INDEX_ENTRY])
        drafts = C.load_jianying_index(index_paths=[idx])
        self.assertEqual(len(drafts), 1)
        d = drafts[0]
        self.assertEqual(d.name, "MC-合集一")            # 界面显示名
        self.assertEqual(d.folder.name, "11月7日")        # 实际文件夹
        self.assertEqual(d.root, Path("D:\\drafts"))

    def test_duration_in_microseconds(self):
        idx = write_index(self.tmp / "idx" / "root_meta_info.json", [INDEX_ENTRY])
        d = C.load_jianying_index(index_paths=[idx])[0]
        self.assertAlmostEqual(d.seconds, 1559.6, places=1)   # 26:00
        self.assertIsNotNone(d.modified)
        self.assertTrue(d.modified.startswith("2026-"))

    def test_missing_index_is_empty_not_error(self):
        self.assertEqual(C.load_jianying_index(index_paths=[self.tmp / "nope.json"]), [])

    def test_corrupt_index_is_empty_not_error(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(C.load_jianying_index(index_paths=[bad]), [])

    def test_index_with_bom_is_readable(self):
        p = self.tmp / "bom.json"
        p.write_text("\ufeff" + json.dumps({"all_draft_store": [INDEX_ENTRY]}, ensure_ascii=False),
                     encoding="utf-8")
        self.assertEqual(len(C.load_jianying_index(index_paths=[p])), 1)

    def test_duplicate_drafts_across_indexes_keep_latest(self):
        older = dict(INDEX_ENTRY, tm_draft_modified=1700000000000000)
        a = write_index(self.tmp / "a" / "root_meta_info.json", [older])
        b = write_index(self.tmp / "b" / "root_meta_info.json", [INDEX_ENTRY])
        drafts = C.load_jianying_index(index_paths=[a, b])
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].modified, C.load_jianying_index(index_paths=[b])[0].modified)

    def test_root_hint_filters_other_roots(self):
        idx = write_index(self.tmp / "idx" / "root_meta_info.json", [INDEX_ENTRY])
        self.assertEqual(len(C.load_jianying_index(Path("D:/drafts"), [idx])), 1)
        self.assertEqual(len(C.load_jianying_index(Path("D:/other"), [idx])), 0)

    def test_empty_name_or_folder_skipped(self):
        good = dict(INDEX_ENTRY)
        no_name = dict(INDEX_ENTRY, draft_name="")
        no_folder = dict(INDEX_ENTRY, draft_fold_path="")
        idx = write_index(self.tmp / "idx" / "root_meta_info.json", [good, no_name, no_folder])
        self.assertEqual(len(C.load_jianying_index(index_paths=[idx])), 1)

    def test_discover_root_picks_the_one_with_most_drafts(self):
        rootA = str(self.tmp / "旧根")
        rootB = str(self.tmp / "新根")
        entries = [
            dict(INDEX_ENTRY, draft_name="旧一", draft_folder="x", draft_fold_path=f"{rootA}/a",
                 draft_root_path=rootA),
            dict(INDEX_ENTRY, draft_name="新一", draft_fold_path=f"{rootB}/a", draft_root_path=rootB),
            dict(INDEX_ENTRY, draft_name="新二", draft_fold_path=f"{rootB}/b", draft_root_path=rootB),
        ]
        idx = write_index(self.tmp / "idx" / "root_meta_info.json", entries)
        self.assertEqual(C.discover_jianying_root([idx]), Path(rootB))

    def test_discover_root_returns_none_without_index(self):
        self.assertIsNone(C.discover_jianying_root([self.tmp / "nope.json"]))

    def test_project_uses_index_when_available(self):
        drafts_dir = self.tmp / "drafts"
        (drafts_dir / "11月7日").mkdir(parents=True)
        (drafts_dir / "11月7日" / "draft_content.json").write_text("{}", encoding="utf-8")
        idx = write_index(
            self.tmp / "idx" / "root_meta_info.json",
            [dict(INDEX_ENTRY, draft_fold_path=str(drafts_dir / "11月7日"),
                  draft_root_path=str(drafts_dir))],
        )
        local = build_batch(self.tmp, manifest=MANIFEST)
        local["jianying"] = {"draft_dir": str(drafts_dir)}
        with mock.patch.object(C, "jianying_index_paths", return_value=[idx]):
            p = C.Project.open("我的世界", "2026-12", local=local)
            self.assertEqual(p.available_drafts(), ["MC-合集一"])
            self.assertEqual(p.draft_info("MC-合集一").folder.name, "11月7日")

    def test_project_falls_back_to_listdir_without_index(self):
        """索引读不到时退化为扫目录 —— 名字可能是文件夹名，但总比空列表强。"""
        drafts_dir = self.tmp / "drafts"
        (drafts_dir / "11月7日").mkdir(parents=True)
        (drafts_dir / "11月7日" / "draft_content.json").write_text("{}", encoding="utf-8")
        local = build_batch(self.tmp, manifest=MANIFEST)
        local["jianying"] = {"draft_dir": str(drafts_dir)}
        p = C.Project.open("我的世界", "2026-12", local=local)   # 索引被 patch 成 []
        self.assertEqual(p.available_drafts(), ["11月7日"])

    def test_draft_info_unknown_returns_none(self):
        p = self.open()
        self.assertIsNone(p.draft_info("不存在的草稿"))


# ─────────────────────────── 登记事实：片头片尾 ───────────────────────────

class TestTemplates(TempDirCase):
    def setUp(self):
        super().setUp()
        self.p = self.open(manifest=MANIFEST)

    def _touch(self, rel: str):
        f = self.p.batch_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")
        return f

    def test_outro_and_intro_paths_relative_to_batch(self):
        self.assertEqual(self.p.outro_for(), self.p.batch_dir / "片尾" / "2026-06-MC-结尾.mp4")
        self.assertEqual(self.p.intro_for("合集一"),
                         self.p.batch_dir / "片头" / "2026-06-MC-开头-合集-1-3.mp4")

    def test_specific_mapping_beats_default(self):
        self.assertEqual(self.p.intro_for("合集九"),
                         self.p.batch_dir / "片头" / "2026-06-MC-9-10-开头.mp4")

    def test_default_fallback(self):
        self.assertEqual(self.p.intro_for("合集七"),
                         self.p.batch_dir / "片头" / "2026-06-MC-开头-合集-1-3.mp4")

    def test_absolute_path_kept(self):
        p = self.open(manifest="templates:\n  outro: D:/abs/x.mp4\n")
        self.assertEqual(p.outro_for(), Path("D:/abs/x.mp4"))

    def test_no_manifest_returns_none(self):
        self.p.manifest_file.unlink()  # setUp 里写过，这里删掉模拟"还没登记过"
        p = C.Project.open("我的世界", "2026-12",
                           local={"workspace": {"root": str(self.tmp)}})
        self.assertEqual(p.manifest, {})
        self.assertIsNone(p.intro_for("合集一"))
        self.assertIsNone(p.outro_for())

    def test_validate_reports_both_missing(self):
        r = self.p.validate_templates("合集一")
        self.assertFalse(r["ok"])
        codes = [x["error"] for x in r["problems"]]
        self.assertEqual(codes, ["intro_file_missing", "outro_file_missing"])

    def test_validate_not_registered(self):
        p = self.open(manifest="templates:\n  intro_mapping: {}\n")
        r = p.validate_templates("合集一")
        codes = [x["error"] for x in r["problems"]]
        self.assertIn("intro_not_registered", codes)
        self.assertIn("outro_not_registered", codes)

    def test_validate_ok_when_files_exist(self):
        self._touch("片头/2026-06-MC-开头-合集-1-3.mp4")
        self._touch("片尾/2026-06-MC-结尾.mp4")
        r = self.p.validate_templates("合集一")
        self.assertTrue(r["ok"])
        self.assertEqual(r["problems"], [])

    def test_validate_specific_intro_needs_its_own_file(self):
        self._touch("片头/2026-06-MC-开头-合集-1-3.mp4")
        self._touch("片尾/2026-06-MC-结尾.mp4")
        self.assertTrue(self.p.validate_templates("合集一")["ok"])
        # 合集九用的是另一个片头，文件还没放
        r = self.p.validate_templates("合集九")
        self.assertFalse(r["ok"])
        self.assertEqual([x["error"] for x in r["problems"]], ["intro_file_missing"])


# ─────────────────────────── 输出 ───────────────────────────

class TestSerialization(TempDirCase):
    def test_as_dict_is_json_serializable(self):
        p = self.open(manifest=MANIFEST, titles=TITLES)
        payload = p.as_dict()
        json.dumps(payload, ensure_ascii=False)  # 不抛异常即合格
        self.assertEqual(payload["collections"], ["合集一", "合集二"])
        self.assertEqual(payload["missing_dirs"], [])
        self.assertTrue(payload["titles_file_exists"])

    def test_collection_as_dict(self):
        p = self.open(manifest=MANIFEST, titles=TITLES)
        d = p.collection("合集一").as_dict()
        json.dumps(d, ensure_ascii=False)
        self.assertEqual(d["collection"], "合集一")
        self.assertEqual(d["index"], 1)
        self.assertEqual(d["draft"], "MC-合集一")
        self.assertEqual(d["subtitle"], "收集强力变身-上篇")
        self.assertEqual(d["full_name"], "波波之我的世界 收集强力变身-上篇")

    def test_error_as_dict(self):
        err = C.CollectionNotFound("没有", collection="合集九", available=["合集一"])
        d = err.as_dict()
        self.assertEqual(d["error"], "collection_not_found")
        self.assertEqual(d["message"], "没有")
        self.assertEqual(d["available"], ["合集一"])
        json.dumps(d, ensure_ascii=False)


class TestMissingDirs(TempDirCase):
    def test_reports_partial_skeleton(self):
        local = build_batch(self.tmp, make_dirs=False)
        p = C.Project.open("我的世界", "2026-12", local=local)
        self.assertEqual(sorted(p.missing_dirs()), sorted(C.BATCH_TREE))


if __name__ == "__main__":
    unittest.main()
