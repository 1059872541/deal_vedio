# -*- coding: utf-8 -*-
"""
DeepSeek API 客户端
"""
import os
from pathlib import Path
from typing import Optional, Callable
from openai import OpenAI

#: 环境变量名（历史约定，保留兼容）
ENV_KEY = "deepseek_env_key"

#: 依次尝试的环境变量名。
#: `deepseek_env_key` 是代码里一直在用的；`DEEPSEEK_API_KEY` 是
#: conf/本机.example.yaml 里写过的 —— 两者长期不一致，这里都认。
ENV_KEYS = ("deepseek_env_key", "DEEPSEEK_API_KEY", "DEEPSEEK_KEY")


def _candidate_env_names(env_key: Optional[str]) -> list[str]:
    names: list[str] = []
    for name in (env_key, *ENV_KEYS):
        if name and name not in names:
            names.append(name)
    return names


def load_api_key(env_key: Optional[str] = None) -> str:
    """按优先级取 API key，取不到就抛一条人话错误。

    1. 环境变量（老办法；三个常见名字都认）
    2. `conf/本机.yaml` 的 `api.deepseek_key`（推荐 —— 这个文件 gitignored，
       本来就是放"每台机器不一样"的东西；而且环境变量在进程启动后就改不了了，
       实测 DSH 这类常驻进程会读不到后来用 setx 设的变量）

    两条都没有时，错误信息要说清"该填哪、填哪儿"，而不是甩一个变量名让人猜。
    """
    for name in _candidate_env_names(env_key):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value

    value = _key_from_local_config()
    if value:
        return value

    raise ValueError(
        "没有找到 DeepSeek API key。两种填法（任选一种，推荐 ①）：\n"
        "  ① conf/本机.yaml 里加（这个文件不进 git）：\n"
        "       api:\n"
        "         deepseek_key: sk-...\n"
        "  ② 系统环境变量（设完要重开终端 / 重启程序）：\n"
        "       setx deepseek_env_key sk-...\n"
        "     （DEEPSEEK_API_KEY / DEEPSEEK_KEY 也认）"
    )


def _key_from_local_config() -> str:
    """从 conf/本机.yaml 读 key。读不到就返回空串（不抛异常）。"""
    # 首选 vedio.context —— 目录约定只有它一份实现
    try:
        from vedio.context import LocalConfig
        key = LocalConfig.load().deepseek_key
        if key:
            return key
    except Exception:          # noqa: BLE001 - 缺配置 / 结构不对都不该炸在这里
        pass

    # 兜底：直接读。旧脚本单独跑时 sys.path 里可能没有 src，import 会失败
    try:
        import yaml
        path = Path(__file__).resolve().parents[4] / "conf" / "本机.yaml"
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return str((data.get("api") or {}).get("deepseek_key") or "").strip()
    except Exception:          # noqa: BLE001
        pass
    return ""


class DeepSeekClient:
    """DeepSeek API 调用客户端"""

    def __init__(self, env_key: Optional[str] = None):
        api_key = load_api_key(env_key)

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )
        self.default_model = "deepseek-v4-pro"

    def _extract_usage(self, chunk) -> dict:
        """从流式响应 chunk 中提取 usage 数据"""
        if hasattr(chunk, 'usage') and chunk.usage:
            return {
                "prompt_tokens": getattr(chunk.usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(chunk.usage, 'completion_tokens', 0),
                "total_tokens": getattr(chunk.usage, 'total_tokens', 0),
                "prompt_cache_hit_tokens": getattr(chunk.usage, 'prompt_cache_hit_tokens', 0),
                "prompt_cache_miss_tokens": getattr(chunk.usage, 'prompt_cache_miss_tokens', 0),
            }
        return {}

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 8192
    ) -> tuple[str, dict]:
        """
        调用 DeepSeek API 进行对话（非流式）

        Returns:
            (回复内容, usage 字典)
        """
        model = model or self.default_model

        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=max_tokens
        )

        content = response.choices[0].message.content or ""
        usage = {}
        if hasattr(response, 'usage') and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
                "prompt_cache_hit_tokens": getattr(response.usage, 'prompt_cache_hit_tokens', 0),
                "prompt_cache_miss_tokens": getattr(response.usage, 'prompt_cache_miss_tokens', 0),
            }

        return content, usage

    def stream_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        on_chunk: Optional[Callable[[str], None]] = None
    ) -> tuple[str, dict]:
        """
        调用 DeepSeek API 进行流式对话

        Returns:
            (完整回复内容, usage 字典)
        """
        model = model or self.default_model

        full_content = ""
        usage_data = {}

        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True}
        )

        finish_reason = None
        for chunk in response:
            # 捕获 usage（最后一条 chunk 会携带）
            if hasattr(chunk, 'usage') and chunk.usage:
                usage_data = self._extract_usage(chunk)

            # 提取内容（usage-only chunk 的 choices 为空）
            if chunk.choices:
                choice = chunk.choices[0]
                if choice.delta.content:
                    content = choice.delta.content
                    full_content += content
                    if on_chunk:
                        on_chunk(content)
                # finish_reason 是判断"推理吃光额度、正文没吐出来"的唯一依据
                if getattr(choice, 'finish_reason', None):
                    finish_reason = choice.finish_reason

        if finish_reason:
            usage_data['finish_reason'] = finish_reason
        return full_content, usage_data

    def stream_chat_with_progress(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        show_progress: bool = True
    ) -> tuple[str, dict]:
        """
        带进度显示的流式对话

        Returns:
            (完整回复内容, usage 字典)
        """
        if not show_progress:
            return self.stream_chat(system_prompt, user_prompt, model, max_tokens)

        full_content = ""
        usage_data = {}
        print("开始生成回复...")

        def on_chunk(chunk: str):
            nonlocal full_content
            full_content += chunk
            print(chunk, end="", flush=True)

        print()
        result, usage_data = self.stream_chat(
            system_prompt,
            user_prompt,
            model,
            max_tokens,
            on_chunk
        )
        print("\n生成完成")

        return result, usage_data

    def chat_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        **kwargs
    ) -> tuple[str, dict]:
        """
        带重试机制的 API 调用（非流式）

        Returns:
            (回复内容, usage 字典)
        """
        for attempt in range(max_retries):
            try:
                return self.chat(system_prompt, user_prompt, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                print(f"API调用失败，尝试重试 ({attempt + 1}/{max_retries}): {e}")

        raise RuntimeError("API调用失败次数超过最大重试次数")

    def stream_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
        **kwargs
    ) -> tuple[str, dict]:
        """
        带重试机制的流式 API 调用

        Returns:
            (回复内容, usage 字典)
        """
        for attempt in range(max_retries):
            try:
                return self.stream_chat(system_prompt, user_prompt, on_chunk=on_chunk, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                print(f"API调用失败，尝试重试 ({attempt + 1}/{max_retries}): {e}")

        raise RuntimeError("API调用失败次数超过最大重试次数")


if __name__ == "__main__":
    client = DeepSeekClient()

    # 测试非流式
    response, usage = client.chat(
        system_prompt="你是AI助手",
        user_prompt="你好，请介绍一下自己"
    )
    print("非流式测试:", response)
    print("Usage:", usage)

    # 测试流式
    print("\n流式测试:")
    response, usage = client.stream_chat_with_progress(
        system_prompt="你是AI助手",
        user_prompt="用一句话介绍你自己",
        show_progress=True
    )
    print("Usage:", usage)
