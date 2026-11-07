# -*- coding: utf-8 -*-
"""API key 读取的单元测试

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v

背景：字幕纠错第一次跑直接报 `未找到环境变量: deepseek_env_key`。
key 只在 Machine 级，而 DSH 这类常驻进程启动早于它被设置，读不到。
另外 `conf/本机.example.yaml` 文档里写的是 `DEEPSEEK_API_KEY`，
代码读的是 `deepseek_env_key` —— 两处长期不一致。

所以现在：三个环境变量名都认，并且可以从 conf/本机.yaml 读。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from deal_video_agent.agent.tools import deepseek_api as D  # noqa: E402
from vedio import context  # noqa: E402


def clean_env() -> dict:
    """把三个候选环境变量都摘掉，避免受本机影响"""
    return mock.patch.dict(os.environ, {}, clear=False)


class TestEnvKey(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in D.ENV_KEYS}
        for k in D.ENV_KEYS:
            os.environ.pop(k, None)
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_primary_env_name(self):
        os.environ["deepseek_env_key"] = "sk-primary"
        self.assertEqual(D.load_api_key(), "sk-primary")

    def test_documented_alias(self):
        """conf/本机.example.yaml 里写过的名字要认"""
        os.environ["DEEPSEEK_API_KEY"] = "sk-alias"
        self.assertEqual(D.load_api_key(), "sk-alias")

    def test_third_alias(self):
        os.environ["DEEPSEEK_KEY"] = "sk-third"
        self.assertEqual(D.load_api_key(), "sk-third")

    def test_primary_wins_over_alias(self):
        os.environ["deepseek_env_key"] = "sk-primary"
        os.environ["DEEPSEEK_API_KEY"] = "sk-alias"
        self.assertEqual(D.load_api_key(), "sk-primary")

    def test_blank_env_is_ignored(self):
        os.environ["deepseek_env_key"] = "   "
        with mock.patch.object(D, "_key_from_local_config", return_value="sk-config"):
            self.assertEqual(D.load_api_key(), "sk-config")

    def test_custom_env_name(self):
        os.environ["MY_OWN_KEY"] = "sk-custom"
        self.addCleanup(os.environ.pop, "MY_OWN_KEY", None)
        self.assertEqual(D.load_api_key("MY_OWN_KEY"), "sk-custom")


class TestConfigKey(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in D.ENV_KEYS}
        for k in D.ENV_KEYS:
            os.environ.pop(k, None)
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_falls_back_to_config(self):
        with mock.patch.object(D, "_key_from_local_config", return_value="sk-config"):
            self.assertEqual(D.load_api_key(), "sk-config")

    def test_env_beats_config(self):
        os.environ["deepseek_env_key"] = "sk-env"
        with mock.patch.object(D, "_key_from_local_config", return_value="sk-config"):
            self.assertEqual(D.load_api_key(), "sk-env")

    def test_error_message_is_actionable(self):
        """报错要说清该填哪，而不是甩一个变量名让人猜"""
        with mock.patch.object(D, "_key_from_local_config", return_value=""):
            with self.assertRaises(ValueError) as ctx:
                D.load_api_key()
        message = str(ctx.exception)
        self.assertIn("conf/本机.yaml", message)
        self.assertIn("api:", message)
        self.assertIn("deepseek_key", message)
        self.assertIn("setx", message)

    def test_local_config_reader_never_raises(self):
        """缺配置 / 主流程没导入 vedio 时都要安静返回空串"""
        with mock.patch.dict(sys.modules, {"vedio.context": None}):
            self.assertIsInstance(D._key_from_local_config(), str)


class TestLocalConfigField(unittest.TestCase):
    def base(self, **extra):
        data = {"workspace": {"root": "D:/ws"}}
        data.update(extra)
        return data

    def test_reads_deepseek_key(self):
        cfg = context.LocalConfig.from_dict(self.base(api={"deepseek_key": "sk-abc"}))
        self.assertEqual(cfg.deepseek_key, "sk-abc")

    def test_missing_api_section(self):
        cfg = context.LocalConfig.from_dict(self.base())
        self.assertEqual(cfg.deepseek_key, "")

    def test_none_api_section(self):
        cfg = context.LocalConfig.from_dict(self.base(api=None))
        self.assertEqual(cfg.deepseek_key, "")

    def test_strips_whitespace(self):
        cfg = context.LocalConfig.from_dict(self.base(api={"deepseek_key": "  sk-x  "}))
        self.assertEqual(cfg.deepseek_key, "sk-x")


if __name__ == "__main__":
    unittest.main()
