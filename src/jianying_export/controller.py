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
              timeout: Optional[float] = None, interval: Optional[float] = None):
        """轮询直到 probe() 返回真值；超时抛 AutomationError。

        用条件等待代替固定 sleep：剪映的渲染时间与草稿时长强相关，
        固定值在短草稿上浪费、在长草稿上可能还不够。
        """
        timeout = self.UI_TIMEOUT if timeout is None else timeout
        interval = self.POLL_INTERVAL if interval is None else interval
        start = time.time()
        while True:
            try:
                value = probe()
            except Exception:
                value = None
            if value:
                return value
            if time.time() - start > timeout:
                raise AutomationError(f"等待「{label}」超时（{timeout:.0f} 秒）")
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

        # ── 2. 打开导出面板 ──
        export_btn = self.app.TextControl(
            searchDepth=2, Compare=ControlFinder.desc_matcher("MainWindowTitleBarExportBtn")
        )
        if not export_btn.Exists(0):
            raise AutomationError("未在编辑窗口中找到导出按钮")
        export_btn.Click(simulateMove=False)

        # 等面板渲染完（原实现固定 sleep 60 秒）
        self._wait_export_panel()

        # ── 3. 读回当前导出路径（面板上直接显示了完整路径）──
        export_path = self._read_export_path()
        if not export_path:
            export_path = str(Path.home() / "Videos" / f"{draft_name}.mp4")
            print(f"警告：未能从界面读到导出路径，按默认推定为 {export_path}")
        else:
            print(f"剪映默认导出到：{export_path}")

        # ── 4. 设分辨率 ──
        if resolution is not None:
            self._choose_option("ExportSharpnessInput", resolution.value, "分辨率")

        # ── 5. 设帧率 ──
        if framerate is not None:
            self._choose_option("FrameRateInput", framerate.value, "帧率")

        # ── 6. 点「导出」 ──
        ok_btn = self.app.TextControl(
            searchDepth=2, Compare=ControlFinder.desc_matcher("ExportOkBtn", exact=True)
        )
        if not ok_btn.Exists(0):
            raise AutomationError("未在导出窗口中找到导出按钮")
        ok_btn.Click(simulateMove=False)

        # ── 7. 等导出完成 ──
        self._wait_export_done(timeout)

        # ── 8. 回目录页 ──
        self._safe_refresh()
        self.switch_to_home()

        # ── 9. 把文件移到目标位置 ──
        if output_path is not None:
            src = self._locate_exported(export_path, draft_name)
            dest = self._resolve_dest(src, output_path)
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

        self._poll(probe, f"{label}选项 {value}", timeout=30.0, interval=0.5)

    def _wait_export_done(self, timeout: float) -> None:
        """等导出完成。

        判据：出现「导出成功」弹窗的关闭按钮。
        **超时检查放在每轮开头** —— 原实现放在 continue 之后，永远执行不到。
        """
        start = time.time()
        while True:
            if time.time() - start > timeout:
                raise ExportTimeout(f"导出超时，时限为 {timeout:.0f} 秒")

            self._safe_refresh()
            if self.app_status == "pre_export":
                close_btn = self.app.TextControl(
                    searchDepth=2, Compare=ControlFinder.desc_matcher("ExportSucceedCloseBtn")
                )
                if self._clickable(close_btn):
                    close_btn.Click(simulateMove=False)
                    return

            time.sleep(4)

    @staticmethod
    def _resolve_dest(src: Path, output_path: str) -> Path:
        """output_path 是目录就保留原文件名，是文件就用它"""
        target = Path(output_path)
        if target.suffix:            # 看起来像文件（有后缀）
            return target
        return target / src.name

    # ─────────────────────────── 窗口 ───────────────────────────

    def switch_to_home(self, timeout: Optional[float] = None) -> None:
        """切换到剪映首页（草稿列表）"""
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
