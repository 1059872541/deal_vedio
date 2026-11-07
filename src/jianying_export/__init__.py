"""剪映自动化导出模块

提供剪映草稿的自动化导出功能，基于pyJianYingDraft项目迁移而来。
注意：仅支持Windows平台，依赖uiautomation库。
"""

import sys

# 模块版本
from ._version import __version__, __author__, __description__

# 平台检查
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from .controller import JianyingController, ExportResolution, ExportFramerate, ControlFinder
    from .controller import jianying_running
    from .exceptions import (
        DraftNotFound, AutomationError, ExportTimeout,
        TrackNotFound, AmbiguousTrack, SegmentOverlap,
        MaterialNotFound, AmbiguousMaterial, ExtensionFailed
    )

    __all__ = [
        "JianyingController",
        "jianying_running",
        "ExportResolution",
        "ExportFramerate",
        "ControlFinder",
        "DraftNotFound",
        "AutomationError",
        "ExportTimeout",
        "TrackNotFound",
        "AmbiguousTrack",
        "SegmentOverlap",
        "MaterialNotFound",
        "AmbiguousMaterial",
        "ExtensionFailed",
    ]
else:
    # 非Windows平台提供虚拟实现，保持类型兼容性
    __all__ = []

    class PlatformNotSupportedError(ImportError):
        """平台不支持错误"""
        def __init__(self, *args, **kwargs):
            super().__init__("剪映自动化导出仅支持Windows平台")

    # 创建虚拟的ExportResolution枚举
    class _DummyEnumMeta(type):
        def __getattr__(cls, name):
            raise PlatformNotSupportedError()

        def __iter__(cls):
            # 返回一个空迭代器，防止遍历时崩溃
            return iter([])

    class ExportResolution(metaclass=_DummyEnumMeta):
        """虚拟导出分辨率枚举（仅用于类型检查）"""
        RES_8K = "8K"
        RES_4K = "4K"
        RES_2K = "2K"
        RES_1080P = "1080P"
        RES_720P = "720P"
        RES_480P = "480P"

        def __init__(self, *args, **kwargs):
            raise PlatformNotSupportedError()

        @property
        def value(self):
            raise PlatformNotSupportedError()

    class ExportFramerate(metaclass=_DummyEnumMeta):
        """虚拟导出帧率枚举（仅用于类型检查）"""
        FR_24 = "24fps"
        FR_25 = "25fps"
        FR_30 = "30fps"
        FR_50 = "50fps"
        FR_60 = "60fps"

        def __init__(self, *args, **kwargs):
            raise PlatformNotSupportedError()

        @property
        def value(self):
            raise PlatformNotSupportedError()

    # 其他类使用PlatformNotSupportedError
    JianyingController = PlatformNotSupportedError
    ControlFinder = PlatformNotSupportedError
    DraftNotFound = PlatformNotSupportedError
    AutomationError = PlatformNotSupportedError
    ExportTimeout = PlatformNotSupportedError
    TrackNotFound = PlatformNotSupportedError
    AmbiguousTrack = PlatformNotSupportedError
    SegmentOverlap = PlatformNotSupportedError
    MaterialNotFound = PlatformNotSupportedError
    AmbiguousMaterial = PlatformNotSupportedError
    ExtensionFailed = PlatformNotSupportedError