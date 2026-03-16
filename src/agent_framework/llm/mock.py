from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent_framework.llm.types import LLMCompletion, Message, OnToken, ToolCall, ToolSchema


@dataclass(frozen=True)
class ScriptedStep:
    content: str = ""
    tool_calls: List[ToolCall] | None = None


class ScriptedChatModel:
    """
    Deterministic LLM stub for tests and offline harness runs.
    """

    def __init__(self, steps: List[ScriptedStep]):
        self._steps = list(steps)
        self._i = 0

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
        if self._i >= len(self._steps):
            return LLMCompletion(content="", tool_calls=[])

        step = self._steps[self._i]
        self._i += 1

        if stream and on_token is not None and step.content:
            on_token(step.content)

        return LLMCompletion(content=step.content, tool_calls=list(step.tool_calls or []))

