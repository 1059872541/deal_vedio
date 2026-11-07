# -*- coding: utf-8 -*-
"""
DeepSeek API 客户端
"""
import os
from typing import Optional, Callable
from openai import OpenAI


class DeepSeekClient:
    """DeepSeek API 调用客户端"""

    def __init__(self, env_key: str = "deepseek_env_key"):
        api_key = os.environ.get(env_key)
        if not api_key:
            raise ValueError(f"未找到环境变量: {env_key}")

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
