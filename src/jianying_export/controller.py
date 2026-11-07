"""剪映自动化控制，主要与自动导出有关

从 pyJianYingDraft 项目迁移而来，适配到当前项目架构。
仅支持 Windows 平台，依赖 uiautomation 库。

本版本修正了原实现的四个问题（2026-11-07）：

1. **死循环**：取消完成判定的 `continue`，把超时检查放在每一轮的开头。
   原写法 `if app_status != "pre_export": continue` 会跳过超时判断，
   状态认不出时永不退出，且每轮反复把剪映窗口抢到前台。

2. **固定 sleep → 条件等待**：
   原来点开草稿后 `sleep(60)`、点导出后再 `sleep(60)`。加等待本身是合理的
   （剪映渲染慢，2 小时草稿尤其明显），但固定值两头不对：短草稿浪费、
   长草稿可能还不够。改为轮询"目标控件出现且位置稳定"，上限 180 秒。

3. **导出路径不再靠 SetValue**：6.0.1 上那个控件是 QQuickText，没有
   ValuePattern，SetValue 无效。改为"走剪映默认路径 → 从界面读回真实路径 →
   shutil.move 到目标位置"。

4. **读导出路径不再用"随便取一个兄弟节点"**：改成按 FullDescription 以 .mp4
   结尾就近匹配，避免拿到 ExportDialog 之类的无关节点。

界面元素统一按 FullDescription（UIA 属性 30159）匹配，不是 Name ——
剪映的 QML 控件 Name 基本都是空的。
"""

import time
import shutil
import sys

from enum import Enum
from pathlib import Path
from typing import Optional, Literal, Callable

# 平台检查
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import uiautomation as uia
else:
    # 非Windows平台提供占位，但实际使用时会在初始化时报错
    uia = None

from . import exceptions
from .exceptions import AutomationError, ExportTimeout

#: 认作"视频"的扩展名。导出面板勾错区块时吐出来的 .srt/.txt 要能识别出来。
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".flv", ".avi", ".m4v", ".wmv", ".webm"})

#: UIA_FullDescriptionPropertyId —— 剪映把控件语义标识放在这个属性里
FULL_DESC = 30159


class ExportResolution(Enum):
    """导出分辨率"""
    RES_8K = "8K"
    RES_4K = "4K"
    RES_2K = "2K"
    RES_1080P = "1080P"
    RES_720P = "720P"
    RES_480P = "480P"


class ExportFramerate(Enum):
    """导出帧率"""
    FR_24 = "24fps"
    FR_25 = "25fps"
    FR_30 = "30fps"
    FR_50 = "50fps"
    FR_60 = "60fps"


class ControlFinder:
    """控件查找器，封装部分与控件查找相关的逻辑"""

    @staticmethod
    def desc_matcher(target_desc: str, depth: int = 2, exact: bool = False) -> Callable[["uia.Control", int], bool]:
        """根据 full_description 查找控件的匹配器"""
        if not IS_WINDOWS:
            raise RuntimeError("ControlFinder仅支持Windows平台")

        target_desc = target_desc.lower()

        def matcher(control: "uia.Control", _depth: int) -> bool:
            if _depth != depth:
                return False
            try:
                full_desc: str = str(control.GetPropertyValue(FULL_DESC)).lower()
            except Exception:
                return False
            return (target_desc == full_desc) if exact else (target_desc in full_desc)

        return matcher

    @staticmethod
    def desc_endswith(suffix: str, depth: int = 2) -> Callable[["uia.Control", int], bool]:
        """按 full_description 的**后缀**匹配。

        专门用来找"导出面板里显示完整输出路径"的那个控件 ——
        它的 FullDescription 就是 `C:/Users/xxx/Videos/MC-合集二.mp4` 这种。
        """
        if not IS_WINDOWS:
            raise RuntimeError("ControlFinder仅支持Windows平台")

        suffix = suffix.lower()

        def matcher(control: "uia.Control", _depth: int) -> bool:
            if _depth != depth:
                return False
            try:
                full_desc: str = str(control.GetPropertyValue(FULL_DESC)).lower()
            except Exception:
                return False
            return full_desc.endswith(suffix)

        return matcher

    @staticmethod
    def class_name_matcher(class_name: str, depth: int = 1, exact: bool = False) -> Callable[["uia.Control", int], bool]:
        """根据 ClassName 查找控件的匹配器"""
        if not IS_WINDOWS:
            raise RuntimeError("ControlFinder仅支持Windows平台")

        class_name = class_name.lower()

        def matcher(control: "uia.Control", _depth: int) -> bool:
            if _depth != depth:
                return False
            curr_class_name: str = control.ClassName.lower()
            return (class_name == curr_class_name) if exact else (class_name in curr_class_name)

        return matcher


class JianyingController:
    """剪映控制器"""

    app: "uia.WindowControl"
    """剪映窗口"""
    app_status: Literal["home", "edit", "pre_export"]

    #: 等界面就绪的上限（秒）。
    #: 为什么是 180：剪映渲染时间与草稿时长强相关，2 小时草稿可能要 40~60 秒，
    #: 留约 3 倍余量。这个值比原来写死的 60 秒**更宽**，但因为是条件等待，
    #: 短草稿照样 1~2 秒返回。
    UI_TIMEOUT = 180.0

    #: 轮询间隔（秒）
    POLL_INTERVAL = 1.0

    #: 等文件写完时的轮询间隔（秒）。比界面轮询松一些 —— 导出落盘是分钟级的事
    FILE_POLL_INTERVAL = 2.0

    def __init__(self):
        """初始化剪映控制器, 此时剪映应该处于目录页

        Raises:
            RuntimeError: 非Windows平台尝试初始化
            AutomationError: 剪映窗口未找到
        """
        if not IS_WINDOWS:
            raise RuntimeError("剪映自动化导出仅支持Windows平台")

        self.get_window()

    # ─────────────────────────── 等待原语 ───────────────────────────

    def _poll(self, probe: Callable[[], object], label: str,
              timeout: Optional[float] = None, interval: Optional[float] = None,
              heartbeat: float = 15.0):
        """轮询直到 probe() 返回真值；超时抛 AutomationError。

        用条件等待代替固定 sleep：剪映的渲染时间与草稿时长强相关，
        固定值在短草稿上浪费、在长草稿上可能还不够。

        `heartbeat`：每隔这么久打印一句"还在等"，否则长时间等待时
        控制台**一片死寂**，人看着就像程序卡死了（实际踩过）。
        """
        timeout = self.UI_TIMEOUT if timeout is None else timeout
        interval = self.POLL_INTERVAL if interval is None else interval
        start = time.time()
        last_note = start
        while True:
            try:
                value = probe()
            except Exception:
                value = None
            if value:
                return value
            now = time.time()
            if time.time() - start > timeout:
                raise AutomationError(f"等待「{label}」超时（{timeout:.0f} 秒）")
            if heartbeat and now - last_note >= heartbeat:
                print(f"  还在等「{label}」…（已等 {now - start:.0f} 秒）")
                last_note = now
            time.sleep(interval)

    def _safe_refresh(self) -> None:
        """重新定位剪映窗口，但不抢前台（轮询时用；失败忽略）"""
        try:
            self.get_window(activate=False)
        except Exception:
            pass

    @staticmethod
    def _clickable(ctrl) -> bool:
        """控件存在且已被布局（有非零矩形）"""
        try:
            if ctrl is None or not ctrl.Exists(0):
                return False
            r = ctrl.BoundingRectangle
            return r.width() > 0 and r.height() > 0
        except Exception:
            return False

    def _wait_enter_editor(self, timeout: Optional[float] = None):
        """等编辑器就绪：窗口类名变成 MainWindow，且导出按钮可点"""
        def probe():
            self._safe_refresh()
            if self.app_status != "edit":
                return None
            btn = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher("MainWindowTitleBarExportBtn")
            )
            return btn if self._clickable(btn) else None

        return self._poll(probe, "进入编辑器（导出按钮就绪）", timeout)

    #: 「导出至」右边那个文件夹图标
    FOLDER_ICON_DESC = "ExportFileNameInputBtn"
    #: 点它弹出的 Windows 标准目录框
    FOLDER_DIALOG_TITLE = "请选择导出路径"
    #: 目录框里确认按钮的名字
    FOLDER_DIALOG_OK = "选择文件夹"

    def set_export_dir(self, directory: Path, timeout: float = 20.0) -> bool:
        """把剪映的导出目录设成指定路径。

        为什么值得做：剪映会记住上次的导出目录，程序不设的话，合集二会被导到
        合集一的文件夹里，之后还得 `shutil.move` 跨目录搬一个 1 GB 的文件。
        实测（6.0.1）：点「导出至」右边的文件夹图标，弹的是 **Windows 标准
        IFileDialog**（`#32770`，「请选择导出路径」），里面
        `EditControl name='文件夹:'` + `ButtonControl name='选择文件夹'` 都能操作，
        `SetValue` 直接生效。

        Returns:
            True = 设置成功且读回确认；False = 任何一步失败（调用方退回"先导后搬"）
        """
        try:
            icon = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher(self.FOLDER_ICON_DESC, exact=True)
            )
            if not self._clickable(icon):
                return False
            icon.Click(simulateMove=False)
            time.sleep(0.5)

            dialog = self._poll(self._find_folder_dialog, "导出目录对话框",
                                timeout=timeout, interval=0.5)
            edit = dialog.EditControl(
                searchDepth=3, Compare=lambda c, d: (c.Name or "") == "文件夹:"
            )
            if not edit.Exists(2):
                self._close_dialog(dialog)
                return False
            try:
                edit.GetValuePattern().SetValue(str(directory))
            except Exception:
                # 极端情况下 ValuePattern 不可用 → 退化为键盘输入
                edit.Click(simulateMove=False)
                uia.SendKeys("{Ctrl}a")
                uia.SendKeys(str(directory))
            time.sleep(0.3)

            ok_btn = dialog.ButtonControl(
                searchDepth=3, Compare=lambda c, d: (c.Name or "") == self.FOLDER_DIALOG_OK
            )
            if not ok_btn.Exists(2):
                self._close_dialog(dialog)
                return False
            ok_btn.Click(simulateMove=False)
            time.sleep(0.8)

            # 读回确认：面板上的路径必须真的换了目录
            actual = self._read_export_path()
            if actual is None:
                return False
            return Path(actual).parent == Path(directory)
        except Exception:
            try:
                dialog = self._find_folder_dialog()
                if dialog is not None:
                    self._close_dialog(dialog)
            except Exception:
                pass
            return False

    @staticmethod
    def _find_folder_dialog():
        """在整棵 UI 树里找「请选择导出路径」对话框。

        它**不是**桌面顶层窗口（挂在剪映窗口下面），所以不能只看
        `GetRootControl().GetChildren()`。
        """
        try:
            for ctrl, _depth in uia.WalkControl(uia.GetRootControl(), maxDepth=8):
                if ((ctrl.ClassName or "") == "#32770"
                        and JianyingController.FOLDER_DIALOG_TITLE in (ctrl.Name or "")):
                    return ctrl
        except Exception:
            pass
        return None

    @staticmethod
    def _close_dialog(dialog) -> None:
        """放弃使用这个对话框：先点取消，再退回 WindowPattern.Close。"""
        try:
            cancel = dialog.ButtonControl(
                searchDepth=3, Compare=lambda c, d: (c.Name or "") == "取消"
            )
            if cancel.Exists(1):
                cancel.Click(simulateMove=False)
                return
        except Exception:
            pass
        try:
            pattern = dialog.GetWindowPattern()
            if pattern:
                pattern.Close()
        except Exception:
            pass

    def _open_export_panel(self, attempts: int = 3, per_try: float = 30.0) -> None:
        """点「导出」按钮打开面板。点不开就重试，别一次点不中就死等超时。

        面板已经在的话直接返回（上次运行可能把它留在了打开状态）。
        """
        last_error: Optional[Exception] = None
        for i in range(1, attempts + 1):
            self._safe_refresh()
            if self.app_status == "pre_export":
                return

            btn = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher("MainWindowTitleBarExportBtn")
            )
            if not self._clickable(btn):
                last_error = AutomationError("未在编辑窗口中找到导出按钮")
            else:
                btn.Click(simulateMove=False)
                try:
                    self._wait_export_panel(timeout=per_try)
                    return
                except AutomationError as exc:
                    last_error = exc
                    if i < attempts:
                        print(f"导出面板没弹出，复位后重试（第 {i} 次点击失败）")
                        # 复位：先把可能残留在打开状态的面板关掉、退回首页，
                        # 再重新点。直接连点效果更差 —— 剪映还停在上一次的状态里。
                        self.close_export_panel()
                        try:
                            self.switch_to_home()
                        except AutomationError:
                            pass
                        time.sleep(2.0)
            time.sleep(1.0)

        raise AutomationError(
            f"点了 {attempts} 次「导出」，面板都没弹出来。"
            f"剪映可能有个对话框挡着（比如「草稿正在使用」），请看一眼手动关掉。\n"
            f"最后一次错误：{last_error}"
        )

    def _wait_export_panel(self, timeout: Optional[float] = None):
        """等导出面板就绪：出现『导出』窗口且 ExportOkBtn 可点"""
        def probe():
            self._safe_refresh()
            if self.app_status != "pre_export":
                return None
            btn = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher("ExportOkBtn", exact=True)
            )
            return btn if self._clickable(btn) else None

        return self._poll(probe, "导出面板就绪", timeout)

    @staticmethod
    def _wait_file_stable(path: Path, timeout: float = 120.0,
                          interval: Optional[float] = None, need: int = 2) -> bool:
        """等文件写完：大小非零且连续 need 次采样不变"""
        if interval is None:
            interval = JianyingController.FILE_POLL_INTERVAL
        start = time.time()
        last, hits = None, 0
        while time.time() - start <= timeout:
            try:
                if path.is_file():
                    size = path.stat().st_size
                    if size > 0 and size == last:
                        hits += 1
                        if hits >= need:
                            return True
                    else:
                        hits = 0
                    last = size
            except OSError:
                pass
            time.sleep(interval)
        return False

    def _locate_exported(self, expected: str, draft_name: str,
                         timeout: float = 180.0) -> Path:
        """等导出文件落盘，返回真实路径。

        为什么不能只信界面上读到的路径：剪映写文件有延迟；而且同名文件已存在时
        会自动改名成 ``xxx（1）.mp4``，界面上那个路径就不准了。
        """
        p = Path(expected)
        if self._wait_file_stable(p, timeout=timeout):
            return p

        # 退化：同目录下最新的「草稿名开头 + .mp4」
        try:
            cands = sorted(
                (f for f in p.parent.glob(f"{draft_name}*.mp4") if f.is_file()),
                key=lambda f: f.stat().st_mtime, reverse=True,
            )
        except OSError:
            cands = []
        for c in cands:
            if self._wait_file_stable(c, timeout=30):
                return c

        raise AutomationError(f"找不到导出文件：{expected}")

    # ─────────────────────────── 主流程 ───────────────────────────

    def export_draft(self, draft_name: str, output_path: Optional[str] = None, *,
                     resolution: Optional[ExportResolution] = None,
                     framerate: Optional[ExportFramerate] = None,
                     timeout: float = 1200) -> None:
        """导出指定的剪映草稿（剪映 6.0.1 实测可用）

        **注意**：需要确认有导出权限（不使用 VIP 功能或已开通 VIP），否则可能长时间无响应。

        Args:
            draft_name: 要导出的剪映草稿名称（界面显示名，不是文件夹名）
            output_path: 导出目标。可以是目录（保留剪映默认文件名）或完整文件路径。
                         不指定则文件留在剪映默认目录。
            resolution: 导出分辨率；不指定则不改变剪映导出窗口中的设置。
            framerate: 导出帧率；不指定则不改变剪映导出窗口中的设置。
            timeout: **导出完成**的超时（秒），默认 20 分钟。
                     界面就绪另有一套上限（``UI_TIMEOUT``，默认 180 秒）。

        Raises:
            DraftNotFound: 未找到指定名称的剪映草稿
            AutomationError: 剪映操作失败 / 界面等待超时
            ExportTimeout: 导出完成超时
        """
        print(f"开始导出 {draft_name} 至 {output_path}")
        self.get_window()
        self.switch_to_home()

        # ── 1. 打开草稿 ──
        draft_name_text = self.app.TextControl(
            searchDepth=2,
            Compare=ControlFinder.desc_matcher(f"HomePageDraftTitle:{draft_name}", exact=True)
        )
        if not draft_name_text.Exists(0):
            raise exceptions.DraftNotFound(f"未找到名为{draft_name}的剪映草稿")
        draft_btn = draft_name_text.GetParentControl()
        if draft_btn is None:
            raise AutomationError("草稿卡片没有父控件，无法点击")
        draft_btn.Click(simulateMove=False)

        # 等编辑器渲染完（原实现固定 sleep 60 秒）
        self._wait_enter_editor()

        # ── 2. 打开导出面板（点不开就重试）──
        #
        # 实测：剪映有时收到点击但面板不弹（上次运行中途失败会留下怪状态）。
        # 原实现只点一次然后死等 180 秒 —— 表现就是"鼠标移到导出按钮，然后停住"。
        # 现在最多点 3 次，每次等 30 秒，点不开再点。
        self._open_export_panel(attempts=3)

        # ── 3. 设导出目录（能设就直接落到目标位置，省掉事后搬 1 GB 文件）──
        target_dir = self._target_dir(output_path) if output_path is not None else None
        if target_dir is not None and self.set_export_dir(target_dir):
            print(f"导出目录已设为：{target_dir}")

        # ── 4. 读回当前导出路径（面板上直接显示了完整路径）──
        export_path = self._read_export_path()
        if not export_path:
            export_path = str(Path.home() / "Videos" / f"{draft_name}.mp4")
            print(f"警告：未能从界面读到导出路径，按默认推定为 {export_path}")
        else:
            print(f"剪映导出到：{export_path}")

        # ── 4/5. 设分辨率、帧率（**尽力而为，失败不中断**）──
        #
        # 实测 6.0.1：`ExportSharpnessInput` / `FrameRateInput` 这两个锚点能找到、
        # 也能点开，但**弹出来的选项项在 UIA 里不可见** —— 主窗口整棵控件树只有
        # 18 个控件，点开下拉后 30 秒也搜不到任何带 "1080P" 字样的控件。
        # 也就是说这一版根本没法用程序选项。
        #
        # 所以改成"能设就设，设不了就大声说一句然后继续"。真正的把关放在
        # 导出之后：用 ffprobe 读产物实际的分辨率和帧率，和配置对比
        # （见 vedio/stages/export.py 的 verify）。宁可事后核对，也不要
        # 因为一个点不到的控件把整个导出卡死。
        for value, anchor, label in (
            (resolution, "ExportSharpnessInput", "分辨率"),
            (framerate, "FrameRateInput", "帧率"),
        ):
            if value is None:
                continue
            try:
                self._choose_option(anchor, value.value, label)
                print(f"{label} 已设为 {value.value}")
            except AutomationError as exc:
                print(f"警告：{label}没能自动设置（{exc}）——"
                      f"将使用剪映当前的设置，导出后会核对实际值")

        # ── 6. 点「导出」 ──
        # 先刷新窗口状态：设置参数那几步可能点开过下拉，窗口树会变；
        # 不刷新的话 self.app 可能还停在旧状态上。
        self._safe_refresh()

        def find_ok():
            btn = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher("ExportOkBtn", exact=True)
            )
            return btn if self._clickable(btn) else None

        ok_btn = self._poll(find_ok, "导出按钮", timeout=15.0, interval=0.5)
        ok_btn.Click(simulateMove=False)

        # ── 7. 等导出完成 ──
        # ── 7. 等导出完成：**以文件为准** ──
        #
        # 原实现等的是「导出成功」弹窗上的关闭按钮（`ExportSucceedCloseBtn`），
        # 但那个标识从没在 6.0.1 真机上验证过 —— 实测导出明明写完了 1.33 GB，
        # 它还在傻等，最后只能超时。现在改成看目标文件：出现、非零、连续两次
        # 采样大小不变 = 写完。
        self._wait_export_file(Path(export_path), timeout=timeout)

        # 顺手把可能出现的成功弹窗关掉 —— 认不出来也没关系，文件已经好了
        self._dismiss_success_dialog()

        # ── 8. 回目录页 ──
        self._safe_refresh()
        self.switch_to_home()

        # ── 9. 把文件移到目标位置（目录已经设对的话就不用搬了）──
        if output_path is not None:
            src = self._locate_exported(export_path, draft_name)
            dest = self._resolve_dest(src, output_path)
            self._ensure_video(dest)
            if src.resolve() == dest.resolve():
                print(f"文件已在目标位置：{dest}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    raise AutomationError(f"目标文件已存在，拒绝覆盖：{dest}")
                shutil.move(str(src), str(dest))
                print(f"已移动到：{dest}")

        print(f"导出 {draft_name} 完成")

    def _read_export_path(self) -> Optional[str]:
        """从导出面板读回完整输出路径（那个控件的 FullDescription 就是路径）"""
        try:
            ctrl = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_endswith(".mp4")
            )
            if ctrl.Exists(0):
                value = ctrl.GetPropertyValue(FULL_DESC)
                return str(value) if value else None
        except Exception:
            pass
        return None

    def _choose_option(self, anchor_desc: str, value: str, label: str) -> None:
        """点开某个下拉框并选中指定值"""
        setting_group = self.app.GroupControl(
            searchDepth=1, Compare=ControlFinder.class_name_matcher("PanelSettingsGroup_QMLTYPE")
        )
        if setting_group.Exists(0):
            anchor = setting_group.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher(anchor_desc)
            )
        else:
            # 兜底：有些版本没有这个分组容器，直接在面板里找
            anchor = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher(anchor_desc)
            )
        if not anchor.Exists(0.5):
            raise AutomationError(f"未找到{label}下拉框")
        anchor.Click(simulateMove=False)

        # 等选项列表出现并点中目标项
        def probe():
            item = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher(value, exact=True)
            )
            if self._clickable(item):
                item.Click(simulateMove=False)
                return True
            return False

        try:
            self._poll(probe, f"{label}选项 {value}", timeout=30.0, interval=0.5)
        except Exception:
            # **必须收尾**：失败时那个下拉还开着，会遮住后面的「导出」按钮，
            # 让整个导出卡死在一个跟参数无关的地方（实测踩过）。
            try:
                uia.SendKeys("{Esc}")
                time.sleep(0.3)
            except Exception:
                pass
            raise

    def _wait_export_file(self, path: Path, timeout: float) -> None:
        """等目标文件写完：出现、非零、连续两次采样大小不变。

        为什么不看界面：6.0.1 上「导出成功」弹窗的关闭按钮标识没验证过，
        实测文件写完了它却始终找不到 → 只能干等到超时。文件是最硬的证据。
        """
        if not self._wait_file_stable(path, timeout=timeout):
            raise ExportTimeout(
                f"导出超时：{timeout:.0f} 秒内没等到文件写完（{path}）"
            )
        size = path.stat().st_size
        if size <= 0:
            raise AutomationError(f"导出产物是空文件：{path}")
        print(f"导出完成：{path}（{size / 1024 / 1024:.1f} MB）")

    def _dismiss_success_dialog(self) -> bool:
        """关掉「导出成功」弹窗（如果找得到的话）。找不到就静默返回 False。"""
        try:
            self._safe_refresh()
            close_btn = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher("ExportSucceedCloseBtn")
            )
            if self._clickable(close_btn):
                close_btn.Click(simulateMove=False)
                time.sleep(0.5)
                return True
        except Exception:
            pass
        # 认不出弹窗，就试着直接把导出面板关掉，别让它挡住后面的操作
        return self.close_export_panel()

    @staticmethod
    def _ensure_video(path: Path) -> None:
        """确认导出的是视频，不是字幕/音频/GIF。

        剪映的导出面板有四个可选区块：视频 / 音频 / GIF / 字幕。勾了「字幕导出」
        没勾「视频导出」时，点导出吐出来的是 `.srt` / `.txt`。
        这些勾选框在 UIA 里**完全不可见**（实测没有 CheckBox、没有 TogglePattern，
        四个区块容器里一个可交互控件都找不到），程序没法替人勾。

        所以这里只做判断：不是视频就停下来说清楚，别把 `.srt` 当成品推进下一步。
        """
        suffix = Path(path).suffix.lower()
        if suffix in VIDEO_SUFFIXES:
            return
        raise AutomationError(
            f"剪映导出的是 {suffix or '无扩展名'} 文件，不是视频 ——"
            f" 导出面板里「视频导出」那一项没勾上。\n"
            f"请在剪映里勾一次「视频导出」（顺手取消「字幕导出」），"
            f"剪映会记住这个组合，之后就不用再管了。"
        )

    @staticmethod
    def _target_dir(output_path: str) -> Optional[Path]:
        """`output_path` 是目录就用它；是文件就用它的父目录。"""
        p = Path(output_path)
        return p.parent if p.suffix else p

    @staticmethod
    def _resolve_dest(src: Path, output_path: str) -> Path:
        """output_path 是目录就保留原文件名，是文件就用它"""
        target = Path(output_path)
        if target.suffix:            # 看起来像文件（有后缀）
            return target
        return target / src.name

    # ─────────────────────────── 窗口 ───────────────────────────

    def close_export_panel(self) -> bool:
        """关掉导出面板，让状态回到编辑/首页。

        为什么需要：`WindowPattern.Close()` 是唯一实测有效的方式
        （`SendKeys('{Esc}')` 对它没用）。上次运行中途失败会把这个面板留在
        打开状态，下次进来 `app_status` 就是 `pre_export`，
        `switch_to_home()` 会直接报"仅支持从编辑模式切换到主页"，整个流程卡死。
        """
        try:
            panel = self.app
            if self.app_status != "pre_export":
                panel = self.app.WindowControl(searchDepth=1, Name="导出")
            if panel is None or not panel.Exists(0.2):
                return False
            pattern = panel.GetWindowPattern()
            if pattern is None:
                return False
            pattern.Close()
            time.sleep(0.4)
            self._safe_refresh()
            return True
        except Exception:
            return False

    def switch_to_home(self, timeout: Optional[float] = None) -> None:
        """切换到剪映首页（草稿列表）"""
        # 上次运行留下的导出面板 → 先关掉再继续，别让它卡死整个流程
        if self.app_status == "pre_export":
            if not self.close_export_panel():
                raise AutomationError("导出面板还开着，关不掉 —— 请手动关一下剪映的导出窗口")
        if self.app_status == "home":
            return
        if self.app_status != "edit":
            raise AutomationError("仅支持从编辑模式切换到主页")

        close_btn = self.app.GroupControl(searchDepth=1, ClassName="TitleBarButton", foundIndex=3)
        if not close_btn.Exists(2):
            raise AutomationError("未找到关闭编辑器的按钮")
        close_btn.Click(simulateMove=False)

        def probe():
            self._safe_refresh()
            return self.app_status == "home"

        self._poll(probe, "回到首页", timeout)

    def get_window(self, activate: bool = True) -> None:
        """寻找剪映窗口并（可选）置顶

        Args:
            activate: 是否抢前台。轮询时应传 False —— 否则会每秒把剪映
                      抢到最前面一次，正是原实现被诟病的行为。
        """
        if hasattr(self, "app") and self.app.Exists(0):
            try:
                self.app.SetTopmost(False)
            except Exception:
                pass

        self.app = uia.WindowControl(searchDepth=1, Compare=self.__jianying_window_cmp)
        if not self.app.Exists(0):
            raise AutomationError("剪映窗口未找到")

        # 寻找可能存在的导出窗口
        export_window = self.app.WindowControl(searchDepth=1, Name="导出")
        if export_window.Exists(0):
            self.app = export_window
            self.app_status = "pre_export"

        if activate:
            self.app.SetActive()
            self.app.SetTopmost()

    def __jianying_window_cmp(self, control: "uia.WindowControl", depth: int) -> bool:
        if control.Name != "剪映专业版":
            return False
        if "HomePage".lower() in control.ClassName.lower():
            self.app_status = "home"
            return True
        if "MainWindow".lower() in control.ClassName.lower():
            self.app_status = "edit"
            return True
        return False
