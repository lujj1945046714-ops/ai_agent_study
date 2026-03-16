from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

from agent_framework.llm.types import LLMCompletion, Message, OnToken, ToolCall as LLMToolCall
from agent_framework.runtime.tool_dispatcher import ToolCall, ToolDispatcher
from agent_framework.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ChatModel(Protocol):
    def complete(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        stream: bool = False,
        on_token: Optional[OnToken] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> LLMCompletion: ...


@dataclass(frozen=True)
class ReactRunResult:
    output_text: str
    steps: int
    messages: List[Message]


class ReactEngine:
    """
    Generic ReAct reasoning loop:
    Think (LLM) -> Act (tools) -> Observe (tool results) -> repeat.
    """

    def __init__(
        self,
        *,
        llm: ChatModel,
        tool_registry: ToolRegistry,
        tool_dispatcher: ToolDispatcher,
    ):
        self._llm = llm
        self._tools = tool_registry
        self._dispatcher = tool_dispatcher

    def run(
        self,
        *,
        system_prompt: str,
        task: str,
        max_steps: int = 30,
        stream: bool = False,
        on_token: Optional[OnToken] = None,
    ) -> ReactRunResult:
        messages: List[Message] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        tool_schemas = self._tools.get_schemas()

        for step in range(1, max_steps + 1):
            completion = self._llm.complete(
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
                stream=stream,
                on_token=on_token,
            )

            assistant_msg: Message = {"role": "assistant", "content": completion.content}
            if completion.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in completion.tool_calls
                ]
            messages.append(assistant_msg)

            if not completion.tool_calls:
                return ReactRunResult(output_text=completion.content or "", steps=step, messages=messages)

            for tc in completion.tool_calls:
                tool_result_payload = self._execute_tool_call(tc)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result_payload, ensure_ascii=False),
                    }
                )

        return ReactRunResult(output_text="已达到最大步骤数，分析终止", steps=max_steps, messages=messages)

    def _execute_tool_call(self, tc: LLMToolCall) -> Dict[str, Any]:
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except json.JSONDecodeError:
            args = {}

        dispatch_result = self._dispatcher.dispatch(ToolCall(id=tc.id, name=tc.name, arguments=args))
        if dispatch_result.success:
            return dispatch_result.output or {}
        return {"error": dispatch_result.error or "tool execution failed"}

