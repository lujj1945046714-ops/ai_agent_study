import pytest
from abc import ABC
from agent_framework.tools.base import BaseTool


def test_base_tool_is_abstract():
    """BaseTool cannot be instantiated directly"""
    with pytest.raises(TypeError):
        BaseTool()


def test_base_tool_requires_name():
    """Subclass must implement name property"""
    class IncompleteTool(BaseTool):
        @property
        def description(self):
            return "test"

        @property
        def schema(self):
            return {}

        def execute(self, **kwargs):
            return {}

    with pytest.raises(TypeError):
        IncompleteTool()


def test_base_tool_requires_all_methods():
    """Subclass must implement all abstract methods"""
    class CompleteTool(BaseTool):
        @property
        def name(self):
            return "test_tool"

        @property
        def description(self):
            return "A test tool"

        @property
        def schema(self):
            return {
                "type": "object",
                "properties": {},
                "required": []
            }

        def execute(self, **kwargs):
            return {"status": "success"}

    tool = CompleteTool()
    assert tool.name == "test_tool"
    assert tool.description == "A test tool"
    assert isinstance(tool.schema, dict)
    assert tool.execute() == {"status": "success"}
