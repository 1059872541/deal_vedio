# -*- coding: utf-8 -*-
"""agent 配置（conf/agent.yaml）的单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

背景：模型名以前硬编码在两处（`deepseek-v4-pro` / `deepseek-chat`），
厂商一改名就得改代码。现在统一由 `conf/agent.yaml` 决定：

    deepseek:
      api_key: "sk-..."
      model: "deepseek-flash"

三个用途（构建知识库 / 字幕纠错 / 标题生成）共用同一个模型。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from deal_video_agent.agent.tools import deepseek_api as D  # noqa: E402
from vedio import context  # noqa: E402


class EnvCase(unittest.TestCase):
    """把三个 key 环境变量 + 模型环境变量摘干净"""

    ENV_NAMES = D.ENV_KEYS + (D.ENV_MODEL,)

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.ENV_NAMES}
        for k in self.ENV_NAMES:
            os.environ.pop(k, None)
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ─────────────────────────── API key ───────────────────────────

class TestApiKey(EnvCase):
    def test_primary_env_name(self):
        os.environ["deepseek_env_key"] = "sk-primary"
        self.assertEqual(D.load_api_key(), "sk-primary")

    def test_documented_alias(self):
        os.environ["DEEPSEEK_API_KEY"] = "sk-alias"
        self.assertEqual(D.load_api_key(), "sk-alias")

    def test_third_alias(self):
        os.environ["DEEPSEEK_KEY"] = "sk-third"
        self.assertEqual(D.load_api_key(), "sk-third")

    def test_primary_wins_over_alias(self):
        os.environ["deepseek_env_key"] = "sk-primary"
        os.environ["DEEPSEEK_API_KEY"] = "sk-alias"
        self.assertEqual(D.load_api_key(), "sk-primary")

    def test_env_wins_over_config(self):
        os.environ["deepseek_env_key"] = "sk-env"
        with mock.patch.object(D, "_settings", return_value={"api_key": "sk-cfg"}):
            self.assertEqual(D.load_api_key(), "sk-env")

    def test_falls_back_to_agent_yaml(self):
        with mock.patch.object(D, "_settings", return_value={"api_key": "sk-cfg"}):
            self.assertEqual(D.load_api_key(), "sk-cfg")

    def test_blank_env_is_ignored(self):
        os.environ["deepseek_env_key"] = "   "
        with mock.patch.object(D, "_settings", return_value={"api_key": "sk-cfg"}):
            self.assertEqual(D.load_api_key(), "sk-cfg")

    def test_custom_env_name(self):
        os.environ["MY_OWN_KEY"] = "sk-custom"
        self.addCleanup(os.environ.pop, "MY_OWN_KEY", None)
        self.assertEqual(D.load_api_key("MY_OWN_KEY"), "sk-custom")

    def test_error_names_agent_yaml(self):
        with mock.patch.object(D, "_settings", return_value={"api_key": ""}):
            with self.assertRaises(ValueError) as ctx:
                D.load_api_key()
        message = str(ctx.exception)
        self.assertIn("conf/agent.yaml", message)
        self.assertIn("api_key", message)
        self.assertIn("setx", message)


# ─────────────────────────── 模型名 ───────────────────────────

class TestModel(EnvCase):
    def test_reads_from_agent_yaml(self):
        with mock.patch.object(D, "_settings", return_value={"model": "deepseek-flash"}):
            self.assertEqual(D.load_model(), "deepseek-flash")

    def test_env_overrides_config(self):
        os.environ["DEEPSEEK_MODEL"] = "临时换的模型"
        with mock.patch.object(D, "_settings", return_value={"model": "deepseek-flash"}):
            self.assertEqual(D.load_model(), "临时换的模型")

    def test_falls_back_to_default_when_unset(self):
        with mock.patch.object(D, "_settings", return_value={}):
            self.assertEqual(D.load_model(), D.DEFAULTS["model"])

    def test_default_is_flash(self):
        """兜底值也应该是当前模型，不能是过时的 deepseek-v4-pro"""
        self.assertEqual(D.DEFAULTS["model"], "deepseek-flash")


# ─────────────────────────── client 接线 ───────────────────────────

class TestClient(EnvCase):
    def test_uses_configured_model_and_limits(self):
        settings = {"api_key": "sk-x", "model": "某模型",
                    "base_url": "https://example.invalid", "max_tokens": 1234}
        with mock.patch.object(D, "_settings", return_value=settings):
            client = D.DeepSeekClient()
        self.assertEqual(client.default_model, "某模型")
        self.assertEqual(client.max_tokens, 1234)
        self.assertIn("example.invalid", str(client.client.base_url))


# ─────────────────────────── AgentConfig 解析 ───────────────────────────

class TestAgentConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, text: str, name: str = "agent.yaml") -> Path:
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_missing_file_uses_defaults(self):
        cfg = context.AgentConfig.load(self.tmp / "不存在.yaml")
        self.assertEqual(cfg.api_key, "")
        self.assertEqual(cfg.model, "deepseek-flash")
        self.assertEqual(cfg.base_url, "https://api.deepseek.com")
        self.assertEqual(cfg.max_tokens, 8192)

    def test_reads_file(self):
        p = self.write(
            "deepseek:\n"
            "  api_key: \"sk-abc\"\n"
            "  model: \"deepseek-flash\"\n"
        )
        cfg = context.AgentConfig.load(p)
        self.assertEqual(cfg.api_key, "sk-abc")
        self.assertEqual(cfg.model, "deepseek-flash")

    def test_empty_model_falls_back(self):
        p = self.write("deepseek:\n  model: \"\"\n")
        self.assertEqual(context.AgentConfig.load(p).model, "deepseek-flash")

    def test_missing_section(self):
        p = self.write("# 空文件\n")
        self.assertEqual(context.AgentConfig.load(p).model, "deepseek-flash")

    def test_strips_whitespace(self):
        p = self.write("deepseek:\n  api_key: \"  sk-x  \"\n  model: \"  m  \"\n")
        cfg = context.AgentConfig.load(p)
        self.assertEqual(cfg.api_key, "sk-x")
        self.assertEqual(cfg.model, "m")

    def test_optional_base_url_and_max_tokens(self):
        p = self.write(
            "deepseek:\n  model: m\n  base_url: \"https://x.invalid\"\n  max_tokens: 4096\n")
        cfg = context.AgentConfig.load(p)
        self.assertEqual(cfg.base_url, "https://x.invalid")
        self.assertEqual(cfg.max_tokens, 4096)

    def test_bad_max_tokens_raises(self):
        p = self.write("deepseek:\n  max_tokens: \"不是数字\"\n")
        with self.assertRaises(context.LocalConfigError):
            context.AgentConfig.load(p)

    def test_non_dict_section_raises(self):
        p = self.write("deepseek: 123\n")
        with self.assertRaises(context.LocalConfigError):
            context.AgentConfig.load(p)


class TestMaxTokensBudget(unittest.TestCase):
    """max_tokens 必须给推理留够额度。

    实测背景（deepseek-flash，8.7 KB / 329 行字幕）：
        prompt 5,378 + completion 12,381 = 17,759
        max_tokens=8192  → 推理吃光，正文 0 字，55 秒白跑
        max_tokens=32768 → 通
    2 小时素材约 50 KB，最坏线性外推 completion ≈ 71,000，取 1.4 倍 → 98304。
    """

    def test_example_config_is_big_enough_for_two_hours(self):
        """模板里的值不能被随手调小 —— 调小就是重新引入"白跑几分钟"的坑"""
        import re
        text = (REPO / "conf" / "agent.example.yaml").read_text(encoding="utf-8")
        match = re.search(r"^\s*max_tokens:\s*(\d+)", text, re.MULTILINE)
        self.assertIsNotNone(match, "模板里应该有 max_tokens")
        self.assertGreaterEqual(int(match.group(1)), 98304)

    def test_shipped_default_matches_requirement(self):
        self.assertGreaterEqual(context.AgentConfig().max_tokens, 1)
        self.assertEqual(D.DEFAULTS["max_tokens"], 8192)   # 兜底值可以小，配置才生效

    def test_warning_when_budget_too_small(self):
        from deal_video_agent.agent.nodes import _max_tokens_warning
        warning = _max_tokens_warning(8192, "x" * 9000)
        self.assertIsNotNone(warning)
        self.assertIn("8192", warning)
        self.assertIn("max_tokens", warning)

    def test_no_warning_when_budget_plenty(self):
        from deal_video_agent.agent.nodes import _max_tokens_warning
        self.assertIsNone(_max_tokens_warning(98304, "x" * 9000))

    def test_warning_for_huge_prompt(self):
        """2 小时级别的输入（约 17k 字符）在 32768 下该被提醒"""
        from deal_video_agent.agent.nodes import _max_tokens_warning
        self.assertIsNotNone(_max_tokens_warning(32768, "字" * 40000))

    def test_empty_prompt_is_silent(self):
        from deal_video_agent.agent.nodes import _max_tokens_warning
        self.assertIsNone(_max_tokens_warning(100, ""))

    def test_real_329_line_prompt_does_not_warn_at_98304(self):
        """真实 329 行字幕的 prompt 大约 6.3k 字符，98304 下不该告警"""
        from deal_video_agent.agent.nodes import _max_tokens_warning
        self.assertIsNone(_max_tokens_warning(98304, "字" * 6300))


# ─────────────────────────── 源码里不能再有写死的模型名 ───────────────────────────

class TestNoHardcodedModels(unittest.TestCase):
    """架构约束：模型名只能来自配置。

    防的是"以后又有人图省事写死一个模型名"。
    注意判据是**带引号的字符串字面量** —— 注释和文档里提到旧名字是好事
    （说明历史、提醒别踩回去），不该被这条测试拦住。
    """

    def read(self, rel: str) -> str:
        return (REPO / "src" / rel).read_text(encoding="utf-8")

    def test_nodes_has_no_model_constant(self):
        src = self.read("deal_video_agent/agent/nodes.py")
        self.assertNotIn("CORRECTION_MODEL", src)
        self.assertNotIn('"deepseek-chat"', src)
        self.assertNotIn('"deepseek-v4-pro"', src)

    def test_api_client_has_no_stale_model_literal(self):
        src = self.read("deal_video_agent/agent/tools/deepseek_api.py")
        self.assertNotIn('"deepseek-v4-pro"', src)
        self.assertNotIn('"deepseek-chat"', src)

    def test_logger_does_not_fake_a_model(self):
        src = self.read("deal_video_agent/agent/logger.py")
        self.assertNotIn('model: str = "deepseek-chat"', src)

    def test_default_model_is_in_one_place(self):
        """兜底值只该有一处 —— 散在多处就等于多处写死"""
        src = self.read("deal_video_agent/agent/tools/deepseek_api.py")
        self.assertEqual(src.count('"deepseek-flash"'), 1)
        cfg = self.read("vedio/context.py")
        self.assertEqual(cfg.count('"deepseek-flash"'), 1)


if __name__ == "__main__":
    unittest.main()
