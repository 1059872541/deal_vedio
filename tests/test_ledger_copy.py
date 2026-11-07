# -*- coding: utf-8 -*-
"""台账文案的校验与重试

背景：提示词里写了「20~40 字」，实测模型给过 76 字、43 字 ——
光靠提示词约束字数不可靠，必须生成后量一遍，不合格带着具体问题再要一次。
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

from vedio import context  # noqa: E402
from vedio.stages import ledger as L  # noqa: E402


class FakeClient:
    """按顺序返回预设的 JSON 文本，并记录每次调用。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system_prompt, user_prompt, **_kw):
        self.calls.append((system_prompt, user_prompt))
        text = self.replies.pop(0) if self.replies else '{"intro": "", "keywords": ""}'
        return text, {}


def reply(intro, keywords):
    return '{"intro": "%s", "keywords": "%s"}' % (intro, keywords)


GOOD_INTRO = "波波借助指南针探索下界，记录群系地貌与遗物。"      # 24 字
GOOD_KW = "指南针、下界、群系、遗物"


class TestCheckCopy(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(L.check_copy(GOOD_INTRO, GOOD_KW, set()), [])

    def test_too_long(self):
        problems = L.check_copy("波" * 76, GOOD_KW, set())
        self.assertTrue(any("76 字" in p for p in problems))

    def test_too_short(self):
        problems = L.check_copy("太短了。", GOOD_KW, set())
        self.assertTrue(any("必须 20~40 字" in p for p in problems))

    def test_too_few_fresh_keywords(self):
        """去重后不足 4 个也要报 —— 关键词撞车等于白给"""
        problems = L.check_copy(GOOD_INTRO, GOOD_KW, {"指南针", "下界"})
        self.assertTrue(any("新关键词" in p for p in problems))

    def test_too_many_keywords(self):
        problems = L.check_copy(GOOD_INTRO, "甲、乙、丙、丁、戊、己、庚", set())
        self.assertTrue(any("最多 6" in p for p in problems))


class TestGenerateCopyChecked(unittest.TestCase):
    def setUp(self):
        # 只用到 game / host / titles 三样，用替身就行 —— 不必造整个批次目录
        class Titles:
            @staticmethod
            def full_collection_name(name):
                return "波波之我的世界 " + name

        class Project:
            game = "我的世界"
            host = "波波"
            titles = Titles()

        self.project = Project()

    def test_first_try_ok(self):
        client = FakeClient([reply(GOOD_INTRO, GOOD_KW)])
        intro, kw, bad = L.generate_copy_checked(
            self.project, "合集一", ["第一集 测试"], client=client)
        self.assertEqual(bad, [])
        self.assertEqual(intro, GOOD_INTRO)
        self.assertEqual(len(client.calls), 1)

    def test_retries_when_too_long(self):
        client = FakeClient([
            reply("波" * 76, GOOD_KW),          # 第一次：太长
            reply(GOOD_INTRO, GOOD_KW),          # 第二次：合格
        ])
        intro, kw, bad = L.generate_copy_checked(
            self.project, "合集一", ["第一集 测试"], client=client)
        self.assertEqual(bad, [])
        self.assertEqual(intro, GOOD_INTRO)
        self.assertEqual(len(client.calls), 2)
        # 第二次必须把问题明确告诉模型，不是简单重来
        self.assertIn("必须 20~40 字", client.calls[1][1])

    def test_gives_up_after_attempts_and_reports(self):
        client = FakeClient([reply("波" * 76, GOOD_KW)] * 2)
        intro, kw, bad = L.generate_copy_checked(
            self.project, "合集一", ["第一集 测试"], client=client)
        self.assertTrue(bad)
        self.assertEqual(len(client.calls), 2)
