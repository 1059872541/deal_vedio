# -*- coding: utf-8 -*-
"""vedio/stages/export.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：
    - **不启动剪映**：注入一个假控制器，只验证"该传什么、该记什么、该跳什么"
    - 时长探测靠替换 `media.probe_duration`，不调 ffprobe
    - 重点守三件事：草稿没登记要报错、已导出要跳过、一个失败不拖累整批
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
from vedio.stages import export as X  # noqa: E402


RULES = """\
game: 我的世界
batch: 2026-12
collections: 2
export:
  resolution: 1080P
  framerate: 30fps
  timeout_seconds: 3600
duration:
  material_per_collection: 1200
  episode_body: 60
  episode_count: 20
  segment_tolerance: 3
meta:
  host: 波波
"""

MANIFEST = """\
drafts:
  合集一: "MC-合集一"
  合集二: "MC-合集二"
templates:
  intro_mapping: {}
  outro: null
"""


from enum import Enum


class FakeResolution(Enum):
    """镜像 jianying_export.ExportResolution 的取值，避免测试导入 Windows 依赖"""
    RES_1080P = "1080P"
    RES_720P = "720P"


class FakeFramerate(Enum):
    FR_30 = "30fps"
    FR_24 = "24fps"


def build(tmp: Path) -> None:
    root = tmp / "我的世界-2026-12"
    root.mkdir(parents=True, exist_ok=True)
    (root / "game.yaml").write_text(RULES, encoding="utf-8")
    (root / "合集清单.yaml").write_text(MANIFEST, encoding="utf-8")
    for d in context.BATCH_TREE:
        (root / d).mkdir(exist_ok=True)
    for name in ("合集一", "合集二"):
        for sub in context.COLLECTION_TREE:
            (root / "合集" / name / sub).mkdir(parents=True, exist_ok=True)


class FakeController:
    """记录调用参数；可选地抛异常；成功时往目标目录写一个片子（模拟 move）"""

    def __init__(self, raise_for=None, create_output=True):
        self.calls = []
        self.raise_for = raise_for or {}
        self.create_output = create_output

    def export_draft(self, draft_name, output_path=None, *, resolution=None,
                     framerate=None, timeout=1200):
        self.calls.append({
            "draft": draft_name, "output": output_path,
            "resolution": getattr(resolution, "value", None),
            "framerate": getattr(framerate, "value", None),
            "timeout": timeout,
        })
        if draft_name in self.raise_for:
            raise self.raise_for[draft_name]
        if self.create_output and output_path:
            out = Path(output_path) / f"{draft_name}.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"fake video")


class ExportCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        build(self.tmp)
        self.p = context.Project.open(
            "我的世界", "2026-12",
            local={"workspace": {"root": str(self.tmp)}},
        )
        self.log = EventLog(self.p.log_dir)

        # 假时长：指定文件名给指定秒数，其余文件一律算 1300 秒
        self._durations = {"长片.mp4": 1300.0}
        patcher = mock.patch.object(
            media, "probe_duration",
            side_effect=lambda ff, p, **kw: self._durations.get(Path(p).name, 1300.0),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.enums = {"resolution": FakeResolution, "framerate": FakeFramerate}

    def touch(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def export(self, collections=None, controller=None, force=False):
        return X.export_drafts(
            self.p, collections,
            log=self.log,
            force=force,
            controller=controller or FakeController(),
            enums=self.enums,
        )


# ─────────────────────────── 参数映射 ───────────────────────────

class TestParams(ExportCase):
    def test_reads_resolution_and_framerate_from_rules(self):
        params = X.export_params(self.p, self.enums)
        self.assertEqual(params["resolution"].value, "1080P")
        self.assertEqual(params["framerate"].value, "30fps")

    def test_unknown_value_becomes_none(self):
        """写错时宁可不改剪映设置，也不猜一个"""
        self.p._rules["export"]["resolution"] = "9999P"
        self.assertIsNone(X.export_params(self.p, self.enums)["resolution"])

    def test_timeout_from_rules(self):
        self.assertEqual(X.export_timeout(self.p), 3600.0)

    def test_timeout_fallback(self):
        del self.p._rules["export"]["timeout_seconds"]
        self.assertEqual(X.export_timeout(self.p), X.DEFAULT_TIMEOUT)


# ─────────────────────────── 单个合集 ───────────────────────────

class TestExportCollection(ExportCase):
    def test_happy_path(self):
        ctrl = FakeController()
        r = X.export_collection(self.p, self.p.collection("合集一"), ctrl,
                                log=self.log, enums=self.enums)
        self.assertEqual(r.status, "done")
        self.assertTrue(r.ok)
        self.assertEqual(r.draft, "MC-合集一")
        # target 是实际落地的文件，必须在 剪辑/ 下
        self.assertEqual(r.target.parent, self.p.collection("合集一").editing)
        self.assertEqual(r.target.name, "MC-合集一.mp4")
        # 传给控制器的必须是 剪辑/ 目录
        self.assertEqual(ctrl.calls[0]["output"], str(self.p.collection("合集一").editing))
        self.assertEqual(ctrl.calls[0]["resolution"], "1080P")
        self.assertEqual(ctrl.calls[0]["framerate"], "30fps")
        self.assertEqual(ctrl.calls[0]["timeout"], 3600.0)

    def test_missing_draft_registration(self):
        c = self.p.collection("合集二")
        # 把登记抹掉
        self.p._manifest["drafts"].pop("合集二")
        with mock.patch.object(self.p, "available_drafts", return_value=["MC-合集一", "MC-合集二"]):
            r = X.export_collection(self.p, c, FakeController(), log=self.log, enums=self.enums)
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "draft_not_found")
        self.assertIn("MC-合集一", r.message)          # 列出候选，方便人指认

    def test_skip_when_already_exported(self):
        ctrl = FakeController()
        self.touch(self.p.collection("合集一").editing / "长片.mp4")
        r = X.export_collection(self.p, self.p.collection("合集一"), ctrl,
                                log=self.log, enums=self.enums)
        self.assertEqual(r.status, "skip")
        self.assertEqual(ctrl.calls, [])               # 不该碰剪映
        self.assertEqual(self.log.last(verb="export", collection="合集一").event, "skip")

    def test_force_re_exports(self):
        ctrl = FakeController()
        self.touch(self.p.collection("合集一").editing / "长片.mp4")
        r = X.export_collection(self.p, self.p.collection("合集一"), ctrl,
                                log=self.log, force=True, enums=self.enums)
        self.assertEqual(r.status, "done")
        self.assertEqual(len(ctrl.calls), 1)

    def test_controller_error_becomes_fail_result(self):
        ctrl = FakeController(raise_for={"MC-合集一": RuntimeError("剪映没响应")})
        r = X.export_collection(self.p, self.p.collection("合集一"), ctrl,
                                log=self.log, enums=self.enums)
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "RuntimeError")
        self.assertIn("剪映没响应", r.message)

    def test_success_without_file_is_failure(self):
        """控制器说成功但目标目录里没片子 —— 不能记成功"""
        ctrl = FakeController(create_output=False)
        r = X.export_collection(self.p, self.p.collection("合集一"), ctrl,
                                log=self.log, enums=self.enums)
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.error, "export_file_missing")
        self.assertEqual(self.log.last(verb="export", event="fail").fields["error"],
                         "export_file_missing")

    def test_events_written(self):
        X.export_collection(self.p, self.p.collection("合集一"), FakeController(),
                            log=self.log, enums=self.enums)
        kinds = [e.event for e in self.log.read() if e.verb == "export"]
        self.assertEqual(kinds, ["start", "done"])
        start = self.log.last(verb="export", event="start")
        self.assertEqual(start.fields["draft"], "MC-合集一")
        self.assertEqual(start.fields["resolution"], "1080P")
        self.assertEqual(start.fields["timeout"], 3600.0)


# ─────────────────────────── 批量 ───────────────────────────

class TestExportBatch(ExportCase):
    def test_all_ok(self):
        ctrl = FakeController()
        b = self.export(controller=ctrl)
        self.assertTrue(b.ok)
        self.assertEqual([r.collection for r in b.results], ["合集一", "合集二"])
        self.assertEqual(len(ctrl.calls), 2)
        self.assertEqual(b.as_dict()["done"], 2)

    def test_one_failure_does_not_stop_others(self):
        """夜间无人值守的关键：一个合集挂了，后面的照跑"""
        ctrl = FakeController(raise_for={"MC-合集一": RuntimeError("boom")})
        b = self.export(controller=ctrl)
        self.assertFalse(b.ok)
        self.assertEqual(b.results[0].status, "fail")
        self.assertEqual(b.results[1].status, "done")
        self.assertEqual(len(ctrl.calls), 2)

    def test_subset(self):
        b = self.export(collections=["合集二"])
        self.assertEqual([r.collection for r in b.results], ["合集二"])

    def test_missing_draft_in_one_collection_only(self):
        self.p._manifest["drafts"].pop("合集一")
        b = self.export(controller=FakeController())
        self.assertEqual(b.results[0].status, "fail")
        self.assertEqual(b.results[1].status, "done")

    def test_lazy_controller_factory(self):
        made = []

        def factory():
            made.append(1)
            return FakeController()

        b = X.export_drafts(self.p, ["合集一"], log=self.log,
                            controller_factory=factory, enums=self.enums)
        self.assertEqual(len(made), 1)
        self.assertTrue(b.ok)

    def test_json_serializable(self):
        import json
        payload = self.export(controller=FakeController()).as_dict()
        json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["total"], 2)


if __name__ == "__main__":
    unittest.main()
