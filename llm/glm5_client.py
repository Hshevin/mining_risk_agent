"""
GLM-5 大模型客户端
OpenAI 兼容模式接入，支持异步文本生成与结构化 JSON 输出
"""

import asyncio
import json
import os
from typing import Any, Dict, Optional, Type

from openai import AsyncOpenAI
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_API_KEY = "b58406e37c1247a78ff5e01e093d7370.1lBWG4vQJtQbPxAF"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_MODEL = "glm-5"


class GLM5Client:
    """
    GLM-5 异步客户端

    特性：
    - 优先读取环境变量 GLM5_API_KEY
    - 支持普通文本生成与强制 JSON 模式
    - 3 次重试 + 指数退避
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("GLM5_API_KEY", DEFAULT_API_KEY)
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        system_message: Optional[str] = None,
    ) -> str:
        """
        异步文本生成

        Args:
            prompt: 用户提示词
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            system_message: 可选系统消息

        Returns:
            生成的文本内容
        """
        messages: list[dict] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        last_exception: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                logger.info(f"GLM-5 生成成功 (attempt {attempt + 1})")
                return content
            except Exception as e:
                last_exception = e
                wait_time = 2 ** attempt
                logger.warning(
                    f"GLM-5 生成失败 (attempt {attempt + 1}/3): {e}, "
                    f"{wait_time}s 后重试"
                )
                if attempt < 2:
                    await asyncio.sleep(wait_time)

        raise RuntimeError(
            f"GLM-5 生成失败，已重试 3 次: {last_exception}"
        ) from last_exception

    async def generate_json(
        self,
        prompt: str,
        output_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.3,
        system_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        异步 JSON 结构化生成

        Args:
            prompt: 用户提示词
            output_schema: 可选 Pydantic 模型，用于校验输出
            temperature: 采样温度
            system_message: 可选系统消息

        Returns:
            解析后的 JSON 字典
        """
        messages: list[dict] = []
        sys_msg = system_message or (
            "你是一个结构化输出助手。请严格按照用户要求的 JSON 格式返回，"
            "不要包含任何 markdown 代码块标记或其他解释性文字。"
        )
        messages.append({"role": "system", "content": sys_msg})
        messages.append({"role": "user", "content": prompt})

        last_exception: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=8192,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or "{}"
                parsed = json.loads(content)

                if output_schema is not None:
                    parsed = output_schema(**parsed).model_dump()

                logger.info(f"GLM-5 JSON 生成成功 (attempt {attempt + 1})")
                return parsed
            except Exception as e:
                last_exception = e
                wait_time = 2 ** attempt
                logger.warning(
                    f"GLM-5 JSON 生成失败 (attempt {attempt + 1}/3): {e}, "
                    f"{wait_time}s 后重试"
                )
                if attempt < 2:
                    await asyncio.sleep(wait_time)

        raise RuntimeError(
            f"GLM-5 JSON 生成失败，已重试 3 次: {last_exception}"
        ) from last_exception
