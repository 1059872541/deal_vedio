# -*- coding: utf-8 -*-
"""提示词加载：一处管理（prompts/），支持按游戏覆写。

用户的要求：提示词不硬编码、不要分散在两套机制里。
现在的规则：

    prompts/editorial.yaml            ← 运营类提示词（篇名、片单文案）
    prompts/subtitle_correction.yaml  ← 字幕 agent（知识库/纠正/标题）
    prompts/games/{游戏}.yaml         ← 该游戏的同名键整条替换

`conf/agent.yaml` 只管账号/模型/额度。
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio import context  # noqa: E402


class TestLoadPrompt(unittest.TestCase):
    def test_reads_editorial_file(self):
        text = context.load_prompt("ledger_copy", "兜底")
        self.assertNotEqual(text, "兜底")
        self.assertIn("intro", text)

    def test_unknown_key_falls_back(self):
        self.assertEqual(context.load_prompt("没有这个键", "兜底"), "兜底")

    def test_game_override_replaces_whole_entry(self):
        """`prompts/games/{游戏}.yaml` 里写了同名键 → 整条替换"""
        override = context.PROMPTS_DIR / "games" / "测试游戏X.yaml"
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_text("ledger_copy: |\n  这是测试覆写\n", encoding="utf-8")
        try:
            self.assertEqual(
                context.load_prompt("ledger_copy", "兜底", game="测试游戏X"),
                "这是测试覆写",
            )
            # 不传游戏 → 还是通用模板
            self.assertIn("intro", context.load_prompt("ledger_copy", "兜底"))
        finally:
            override.unlink()

    def test_override_without_key_uses_base(self):
        """游戏覆写文件里没这个键 → 回落到通用模板，不是空"""
        override = context.PROMPTS_DIR / "games" / "测试游戏Y.yaml"
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_text("knowledge_building: |\n  只管知识库\n", encoding="utf-8")
        try:
            self.assertIn("intro",
                          context.load_prompt("ledger_copy", "兜底", game="测试游戏Y"))
        finally:
            override.unlink()

    def test_agent_yaml_has_no_prompts(self):
        """提示词不该再散落在 agent.yaml 里（它含 api_key，不进 git）"""
        cfg = context.AgentConfig.load()
        self.assertEqual(cfg.prompts, {})
