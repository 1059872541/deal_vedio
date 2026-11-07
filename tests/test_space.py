# -*- coding: utf-8 -*-
"""vedio/space.py 单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

要点：账目表要**给用户看**，所以断言的是"四行都在、结论明确"，
不是精确排版 —— 中文双宽字符靠空格对齐换个终端就歪，所以用「标签：值」。
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import space  # noqa: E402

GB = 1024 ** 3


def report(enough=True):
    total = int(5.2 * GB)
    free = int(11.7 * GB) if enough else int(0.6 * GB)
    return {
        "steps": ["export", "splice"],
        "collections": [
            {"name": "合集一", "stages": {"export": int(1.6 * GB), "splice": int(3.6 * GB)},
             "total": total},
        ],
        "total": total,
        "free": free,
        "enough": enough,
        "short": 0 if enough else total - free,
        "drive": "D:",
    }


class TestRender(unittest.TestCase):
    def test_shows_export_and_splice_separately(self):
        """用户要求：导出占多少、拼接占多少，要分开看"""
        text = space.render(report())
        self.assertIn("导出：1.6 GB", text)
        self.assertIn("分割拼接：3.6 GB", text)

    def test_shows_total_and_free(self):
        text = space.render(report())
        self.assertIn("合计：5.2 GB", text)
        self.assertIn("当前剩余：11.7 GB", text)

    def test_enough_says_ok(self):
        text = space.render(report(enough=True))
        self.assertIn("✅", text)
        self.assertNotIn("不够", text)

    def test_short_says_how_much_and_where(self):
        """不够时必须说清"差多少 + 清理哪个盘"，不能只说不允许"""
        text = space.render(report(enough=False))
        self.assertIn("❌", text)
        self.assertIn("还差 4.6 GB", text)
        self.assertIn("请清理 D:", text)

    def test_unknown_free_skips_verdict(self):
        rep = report()
        rep["free"] = -1
        text = space.render(rep)
        self.assertIn("查不到", text)
        self.assertNotIn("✅", text)

    def test_aggregates_per_stage_not_per_collection(self):
        """两个合集 → 每步的数值要是总和"""
        rep = report()
        rep["collections"] = [
            {"name": "合集一", "stages": {"export": GB, "splice": GB}, "total": 2 * GB},
            {"name": "合集二", "stages": {"export": GB, "splice": GB}, "total": 2 * GB},
        ]
        rep["total"] = 4 * GB
        text = space.render(rep)
        self.assertIn("导出：2.0 GB", text)
        self.assertIn("分割拼接：2.0 GB", text)


if __name__ == "__main__":
    unittest.main()
