"""自定义异常类

从pyJianYingDraft项目迁移而来，用于剪映自动化操作。
"""

class TrackNotFound(NameError):
    """未找到满足条件的轨道"""
    pass

class AmbiguousTrack(ValueError):
    """找到多个满足条件的轨道"""
    pass

class SegmentOverlap(ValueError):
    """新片段与已有的轨道片段重叠"""
    pass

class MaterialNotFound(NameError):
    """未找到满足条件的素材"""
    pass

class AmbiguousMaterial(ValueError):
    """找到多个满足条件的素材"""
    pass

class ExtensionFailed(ValueError):
    """替换素材时延伸片段失败"""
    pass

class DraftNotFound(NameError):
    """未找到草稿"""
    pass

class AutomationError(Exception):
    """自动化操作失败"""
    pass

class ExportTimeout(AutomationError):
    """导出超时。

    继承 AutomationError 而不是 Exception：超时本质上也是一种自动化失败，
    调用方通常只需要 `except AutomationError` 一个分支就能覆盖。
    """
    pass