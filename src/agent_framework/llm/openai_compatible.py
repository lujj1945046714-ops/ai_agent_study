from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from agent_framework.llm.types import LLMCompletion, Message, OnToken, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    api_key: str
    model: str
    base_url: Optional[str] = None


class OpenAICompatibleChatModel:
    """
    Adapter for OpenAI-compatible Chat Completions APIs.

    Works with:
    - OpenAI (default base_url)
    - DeepSeek / other providers exposing OpenAI-compatible endpoints (via base_url)
    """

    def __init__(self, config: OpenAICompatibleConfig):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime dependent
            raise RuntimeError("Missing dependency: openai") from exc

        self._model = config.model
        self._client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        tool_choice: str = "auto",
        stream: bool = False,
        on_token: Optional[OnToken] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> LLMCompletion:
        if stream:
            return self._complete_streaming(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                on_token=on_token,
                temperature=temperature,
                response_format=response_format,
            )

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            response_format=response_format,
        )
        msg = resp.choices[0].message
        tool_calls: List[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    )
                )
        return LLMCompletion(content=msg.content or "", tool_calls=tool_calls)

    def _complete_streaming(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[ToolSchema]],
        tool_choice: str,
        on_token: Optional[OnToken],
        temperature: Optional[float],
        response_format: Optional[Dict[str, Any]],
    ) -> LLMCompletion:
        full_content = ""
        tool_calls_buffer: Dict[int, Dict[str, str]] = {}

        with self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            temperature=temperature,
            response_format=response_format,
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta

                if delta.content:
                    full_content += delta.content
                    if on_token is not None:
                        try:
                            on_token(delta.content)
                        except Exception:  # pragma: no cover - callback dependent
                            logger.warning("on_token callback failed", exc_info=True)

                if not delta.tool_calls:
                    continue

                for tc in delta.tool_calls:
                    idx = tc.index
                    buf = tool_calls_buffer.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        buf["id"] = tc.id
                    if tc.function and tc.function.name:
                        buf["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        buf["arguments"] += tc.function.arguments

        tool_calls: List[ToolCall] = []
        for buf in tool_calls_buffer.values():
            tool_calls.append(ToolCall(id=buf["id"], name=buf["name"], arguments=buf["arguments"]))

        return LLMCompletion(content=full_content, tool_calls=tool_calls)

