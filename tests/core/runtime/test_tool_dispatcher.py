import pytest
from unittest.mock import Mock
from agent_framework.runtime.tool_dispatcher import ToolDispatcher, ToolCall, ToolResult
from agent_framework.tools.registry import ToolRegistry
from agent_framework.tools.base import BaseTool
from agent_framework.gateway.hooks import HooksRegistry


class MockTool(BaseTool):
    @property
    def name(self):
        return "mock_tool"

    @property
    def description(self):
        return "Mock"

    @property
    def schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return {"result": "success", "input": kwargs}


def test_dispatch_tool_call():
    """Can dispatch tool call"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(MockTool())
    dispatcher = ToolDispatcher(registry, hooks)

    tool_call = ToolCall(id="call_1", name="mock_tool", arguments={"arg": "value"})
    result = dispatcher.dispatch(tool_call)

    assert isinstance(result, ToolResult)
    assert result.tool_call_id == "call_1"
    assert result.success is True
    assert result.output["result"] == "success"


def test_dispatch_nonexistent_tool():
    """Handles nonexistent tool gracefully"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    dispatcher = ToolDispatcher(registry, hooks)

    tool_call = ToolCall(id="call_2", name="nonexistent", arguments={})
    result = dispatcher.dispatch(tool_call)

    assert result.success is False
    assert "not found" in result.error.lower()


def test_dispatch_tool_error():
    """Handles tool execution error"""
    class ErrorTool(BaseTool):
        @property
        def name(self):
            return "error_tool"

        @property
        def description(self):
            return "Error"

        @property
        def schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            raise ValueError("Tool error")

    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(ErrorTool())
    dispatcher = ToolDispatcher(registry, hooks)

    tool_call = ToolCall(id="call_3", name="error_tool", arguments={})
    result = dispatcher.dispatch(tool_call)

    assert result.success is False
    assert "Tool error" in result.error


def test_dispatch_triggers_hooks():
    """Dispatching triggers before/after hooks"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(MockTool())
    dispatcher = ToolDispatcher(registry, hooks)

    called_hooks = []

    def before_hook(ctx):
        called_hooks.append("before")

    def after_hook(ctx):
        called_hooks.append("after")

    hooks.register("before_tool", before_hook)
    hooks.register("after_tool", after_hook)

    tool_call = ToolCall(id="call_4", name="mock_tool", arguments={})
    dispatcher.dispatch(tool_call)

    assert called_hooks == ["before", "after"]


def test_dispatch_batch():
    """Can dispatch multiple tool calls"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(MockTool())
    dispatcher = ToolDispatcher(registry, hooks)

    tool_calls = [
        ToolCall(id="call_5", name="mock_tool", arguments={"n": 1}),
        ToolCall(id="call_6", name="mock_tool", arguments={"n": 2})
    ]
    results = dispatcher.dispatch_batch(tool_calls)

    assert len(results) == 2
    assert all(r.success for r in results)
