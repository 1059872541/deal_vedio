# -*- coding: utf-8 -*-
"""jianying_export 控制器单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

特点：
    - **不需要剪映**：用 object.__new__ 绕过 __init__（它要找一个真实窗口），
      只测纯逻辑部分
    - 覆盖 2026-11-07 修的四个问题：超时位置、条件等待、路径回读、目标解析
    - 不碰真实文件系统之外的东西，全部在临时目录里
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jianying_export import controller as C  # noqa: E402
from jianying_export import exceptions  # noqa: E402


# ─────────────────────────── 假控件 ───────────────────────────

class FakeRect:
    def __init__(self, left=0, top=0, right=10, bottom=10):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class FakeControl:
    """只实现被测代码用到的那几个属性"""

    def __init__(self, desc="", exists=True, rect=None):
        self._desc = desc
        self._exists = exists
        self.BoundingRectangle = FakeRect(*(rect or (0, 0, 10, 10)))

    def GetPropertyValue(self, prop):
        if prop != C.FULL_DESC:
            raise KeyError(prop)
        return self._desc

    def Exists(self, wait=0):
        return self._exists


def make_controller(app_status="edit"):
    """绕过 __init__ 造一个控制器实例（__init__ 需要真实剪映窗口）"""
    ctrl = object.__new__(C.JianyingController)
    ctrl.app = None
    ctrl.app_status = app_status
    return ctrl


# ─────────────────────────── 控件匹配 ───────────────────────────

class TestControlFinder(unittest.TestCase):
    def test_desc_matcher_exact(self):
        m = C.ControlFinder.desc_matcher("ExportOkBtn", exact=True)
        self.assertTrue(m(FakeControl("ExportOkBtn"), 2))
        self.assertFalse(m(FakeControl("ExportOkBtnX"), 2))

    def test_desc_matcher_substring(self):
        m = C.ControlFinder.desc_matcher("ExportPath")
        self.assertTrue(m(FakeControl("ExportPathInput"), 2))
        self.assertFalse(m(FakeControl("ExportDialog"), 2))

    def test_matcher_respects_depth(self):
        """深度对不上就不匹配 —— 这是原实现容易踩的坑"""
        m = C.ControlFinder.desc_matcher("ExportOkBtn", depth=2, exact=True)
        self.assertFalse(m(FakeControl("ExportOkBtn"), 1))
        self.assertFalse(m(FakeControl("ExportOkBtn"), 3))

    def test_matcher_survives_bad_property(self):
        class Broken:
            def GetPropertyValue(self, prop):
                raise RuntimeError("boom")
        self.assertFalse(C.ControlFinder.desc_matcher("x")(Broken(), 2))

    def test_desc_endswith_finds_output_path(self):
        """用它替代原来的 GetSiblingControl(lambda: True)"""
        m = C.ControlFinder.desc_endswith(".mp4")
        self.assertTrue(m(FakeControl("C:/Users/x/Videos/MC-合集二.mp4"), 2))
        self.assertFalse(m(FakeControl("ExportDialog"), 2))


# ─────────────────────────── 轮询原语 ───────────────────────────

class TestPoll(unittest.TestCase):
    def test_returns_value(self):
        ctrl = make_controller()
        calls = []

        def probe():
            calls.append(1)
            return "ok" if len(calls) >= 3 else None

        with mock.patch.object(C.time, "sleep", return_value=None):
            self.assertEqual(ctrl._poll(probe, "测试", timeout=5, interval=0), "ok")
        self.assertEqual(len(calls), 3)

    def test_timeout_raises_automation_error(self):
        ctrl = make_controller()
        with mock.patch.object(C.time, "sleep", return_value=None):
            with self.assertRaises(exceptions.AutomationError) as ctx:
                ctrl._poll(lambda: None, "永不就绪", timeout=0, interval=0)
        self.assertIn("永不就绪", str(ctx.exception))

    def test_probe_exception_is_swallowed(self):
        """探针抛异常不该炸掉整个等待 —— 剪映窗口随时可能消失"""
        ctrl = make_controller()
        state = {"n": 0}

        def probe():
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("窗口没了")
            return True

        with mock.patch.object(C.time, "sleep", return_value=None):
            self.assertTrue(ctrl._poll(probe, "测试", timeout=5, interval=0))


class TestClickable(unittest.TestCase):
    def test_normal(self):
        self.assertTrue(C.JianyingController._clickable(FakeControl()))

    def test_zero_rect_is_not_clickable(self):
        """QML 控件可能先创建后布局，零矩形时不能点"""
        self.assertFalse(C.JianyingController._clickable(FakeControl(rect=(0, 0, 0, 0))))

    def test_not_exists(self):
        self.assertFalse(C.JianyingController._clickable(FakeControl(exists=False)))

    def test_none(self):
        self.assertFalse(C.JianyingController._clickable(None))


# ─────────────────────────── 目标路径解析 ───────────────────────────

class TestResolveDest(unittest.TestCase):
    def test_directory_keeps_filename(self):
        src = Path("C:/Users/x/Videos/MC-合集二.mp4")
        dest = C.JianyingController._resolve_dest(src, r"D:\工作区\合集\合集二\剪辑")
        self.assertEqual(dest, Path(r"D:\工作区\合集\合集二\剪辑") / "MC-合集二.mp4")

    def test_file_path_used_as_is(self):
        src = Path("C:/Users/x/Videos/MC-合集二.mp4")
        dest = C.JianyingController._resolve_dest(src, r"D:\out\自定义.mp4")
        self.assertEqual(dest, Path(r"D:\out\自定义.mp4"))


# ─────────────────────────── 等文件写完 ───────────────────────────

class TestWaitFileStable(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # 把轮询间隔压到毫秒级，否则一个用例要等 2 秒
        patcher = mock.patch.object(C.JianyingController, "FILE_POLL_INTERVAL", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_existing_file_is_stable(self):
        f = self.tmp / "a.mp4"
        f.write_bytes(b"x" * 100)
        self.assertTrue(C.JianyingController._wait_file_stable(f, timeout=2, interval=0.01))

    def test_missing_file_times_out(self):
        self.assertFalse(
            C.JianyingController._wait_file_stable(self.tmp / "nope.mp4", timeout=0.1, interval=0.01)
        )

    def test_empty_file_not_considered_done(self):
        """0 字节文件是"刚创建还没写"，不是完成"""
        f = self.tmp / "empty.mp4"
        f.write_bytes(b"")
        self.assertFalse(C.JianyingController._wait_file_stable(f, timeout=0.2, interval=0.01))


class TestLocateExported(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.object(C.JianyingController, "FILE_POLL_INTERVAL", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctrl = make_controller()

    def test_exact_path_found(self):
        f = self.tmp / "MC-合集二.mp4"
        f.write_bytes(b"x" * 100)
        self.assertEqual(
            self.ctrl._locate_exported(str(f), "MC-合集二", timeout=1),
            f,
        )

    def test_fallback_to_renamed_file(self):
        """剪映遇到同名文件会改名成 xxx（1）.mp4，此时界面上读到的路径是错的"""
        renamed = self.tmp / "MC-合集二（1）.mp4"
        renamed.write_bytes(b"x" * 100)
        got = self.ctrl._locate_exported(str(self.tmp / "MC-合集二.mp4"), "MC-合集二", timeout=0.2)
        self.assertEqual(got, renamed)

    def test_fallback_prefers_newest(self):
        old = self.tmp / "MC-合集二（1）.mp4"
        new = self.tmp / "MC-合集二（2）.mp4"
        old.write_bytes(b"x" * 100)
        time.sleep(0.01)
        new.write_bytes(b"x" * 200)
        got = self.ctrl._locate_exported(str(self.tmp / "MC-合集二.mp4"), "MC-合集二", timeout=0.2)
        self.assertEqual(got, new)

    def test_raises_when_nothing_found(self):
        with self.assertRaises(exceptions.AutomationError):
            self.ctrl._locate_exported(str(self.tmp / "MC-合集二.mp4"), "MC-合集二", timeout=0.1)


# ─────────────────────────── 导出完成判定 ───────────────────────────

class TestWaitExportFile(unittest.TestCase):
    """导出完成的判据是**文件**，不是界面弹窗。

    实测教训：6.0.1 上「导出成功」弹窗的关闭按钮标识从没验证过，
    文件 1.33 GB 都写完了它还在傻等，最后只能超时。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        patcher = mock.patch.object(C.time, "sleep", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_export_timeout_is_automation_error(self):
        """超时也要能被 `except AutomationError` 抓到"""
        self.assertTrue(issubclass(exceptions.ExportTimeout, exceptions.AutomationError))

    def test_timeout_when_file_never_appears(self):
        ctrl = make_controller()
        with self.assertRaises(exceptions.ExportTimeout):
            ctrl._wait_export_file(self.dir / "never.mp4", timeout=0)

    def test_returns_when_file_complete(self):
        target = self.dir / "ok.mp4"
        target.write_bytes(b"x" * 1024)
        ctrl = make_controller()
        ctrl._wait_export_file(target, timeout=5)      # 不抛就算过

    def test_empty_file_times_out(self):
        """0 字节不算写完 —— 剪映刚建文件时就是 0 字节"""
        target = self.dir / "empty.mp4"
        target.write_bytes(b"")
        ctrl = make_controller()
        with self.assertRaises(exceptions.ExportTimeout):
            ctrl._wait_export_file(target, timeout=0)


class TestDismissSuccessDialog(unittest.TestCase):
    def test_falls_back_to_closing_panel(self):
        """认不出弹窗就关面板 —— 别让它挡住后面的操作"""
        ctrl = make_controller(app_status="pre_export")
        with mock.patch.object(ctrl, "_safe_refresh", return_value=None), \
             mock.patch.object(ctrl, "_clickable", return_value=False), \
             mock.patch.object(ctrl, "close_export_panel", return_value=True) as close:
            self.assertTrue(ctrl._dismiss_success_dialog())
        close.assert_called_once()


# ─────────────────────────── 默认上限 ───────────────────────────

class TestEnsureVideo(unittest.TestCase):
    """剪映的导出面板有四个可选区块，勾错区块会吐出字幕而不是视频。

    这些勾选框在 UIA 里完全不可见（没有 CheckBox / TogglePattern），
    程序替不了人勾 —— 只能判断产出物对不对，不对就停下来讲清楚。
    """

    def test_mp4_passes(self):
        C.JianyingController._ensure_video(Path("a.mp4"))
        C.JianyingController._ensure_video(Path("A.MOV"))

    def test_subtitle_is_rejected(self):
        with self.assertRaises(C.AutomationError) as ctx:
            C.JianyingController._ensure_video(Path("MC-01.srt"))
        message = str(ctx.exception)
        self.assertIn("视频导出", message)
        self.assertIn("剪映会记住", message)

    def test_txt_is_rejected(self):
        with self.assertRaises(C.AutomationError):
            C.JianyingController._ensure_video(Path("MC-01.txt"))

    def test_audio_is_rejected(self):
        with self.assertRaises(C.AutomationError):
            C.JianyingController._ensure_video(Path("MC-01.mp3"))


class TestSetExportDir(unittest.TestCase):
    """剪映的导出目录可以通过「导出至」右边的文件夹按钮设进去。

    实测（6.0.1）：点它弹的是 Windows 标准 IFileDialog（`#32770`「请选择导出路径」），
    里面 `EditControl name='文件夹:'` 支持 SetValue，`ButtonControl name='选择文件夹'`
    可以确认。这样导出直接落到目标目录，不用事后跨盘搬 1 GB。
    """

    def test_target_dir_from_directory(self):
        self.assertEqual(C.JianyingController._target_dir(r"D:\a\b"), Path(r"D:\a\b"))

    def test_target_dir_from_file(self):
        self.assertEqual(C.JianyingController._target_dir(r"D:\a\b\x.mp4"), Path(r"D:\a\b"))

    def test_returns_false_without_icon(self):
        """找不到文件夹图标 → 返回 False，让调用方退回"先导后搬\""""
        ctrl = make_controller(app_status="pre_export")
        with mock.patch.object(ctrl, "_clickable", return_value=False):
            self.assertFalse(ctrl.set_export_dir(Path(r"D:\x")))

    def test_returns_false_when_dialog_never_appears(self):
        ctrl = make_controller(app_status="pre_export")

        class FakeIcon:
            def Click(self, **kwargs):
                pass

        class FakeApp:
            def TextControl(self, **kwargs):
                return FakeIcon()

        ctrl.app = FakeApp()
        with mock.patch.object(ctrl, "_clickable", return_value=True), \
             mock.patch.object(C.time, "sleep", return_value=None), \
             mock.patch.object(ctrl, "_find_folder_dialog", return_value=None):
            self.assertFalse(ctrl.set_export_dir(Path(r"D:\x"), timeout=0))

    def test_find_folder_dialog_searches_whole_tree(self):
        """它挂在剪映窗口下面，不是桌面顶层窗口 —— 只看顶层会漏"""
        with mock.patch.object(C.uia, "GetRootControl"), \
             mock.patch.object(C.uia, "WalkControl", return_value=[]) as walk:
            self.assertIsNone(C.JianyingController._find_folder_dialog())
        walk.assert_called_once()


class TestDefaults(unittest.TestCase):
    def test_ui_timeout_is_180(self):
        """用户定的上限：界面就绪 180 秒"""
        self.assertEqual(C.JianyingController.UI_TIMEOUT, 180.0)

    def test_full_desc_constant(self):
        self.assertEqual(C.FULL_DESC, 30159)


if __name__ == "__main__":
    unittest.main()
