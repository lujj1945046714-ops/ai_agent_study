from __future__ import annotations

import json

from agent_framework.gateway.hooks import HooksRegistry
from agent_framework.llm.mock import ScriptedChatModel, ScriptedStep
from agent_framework.llm.types import ToolCall
from agent_framework.runtime.react_engine import ReactEngine
from agent_framework.runtime.tool_dispatcher import ToolDispatcher
from agent_framework.tools.base import BaseTool
from agent_framework.tools.registry import ToolRegistry


class EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo input"

    @property
    def schema(self):
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    def execute(self, **kwargs):
        return {"echo": kwargs.get("text", "")}


def test_react_engine_executes_tool_calls():
    registry = ToolRegistry()
    registry.register(EchoTool())
    dispatcher = ToolDispatcher(registry, HooksRegistry())

    llm = ScriptedChatModel(
        [
            ScriptedStep(
                content="",
                tool_calls=[ToolCall(id="tc_1", name="echo", arguments=json.dumps({"text": "hi"}))],
            ),
            ScriptedStep(content="done", tool_calls=[]),
        ]
    )

    engine = ReactEngine(llm=llm, tool_registry=registry, tool_dispatcher=dispatcher)
    result = engine.run(system_prompt="sys", task="task", max_steps=5)

    assert result.output_text == "done"
    assert result.steps == 2
    assert any(m.get("role") == "tool" for m in result.messages)

