import pytest
from agent_framework.tools.registry import ToolRegistry
from agent_framework.tools.base import BaseTool


class MockTool(BaseTool):
    """Mock tool for testing"""
    @property
    def name(self):
        return "mock_tool"

    @property
    def description(self):
        return "A mock tool"

    @property
    def schema(self):
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            },
            "required": ["input"]
        }

    def execute(self, **kwargs):
        return {"result": kwargs.get("input", "")}


def test_registry_register_tool():
    """Can register a tool"""
    registry = ToolRegistry()
    tool = MockTool()

    registry.register(tool)

    assert "mock_tool" in registry.list_tools()


def test_registry_get_tool():
    """Can retrieve registered tool"""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    retrieved = registry.get_tool("mock_tool")

    assert retrieved is tool
    assert retrieved.name == "mock_tool"


def test_registry_get_nonexistent_tool():
    """Returns None for nonexistent tool"""
    registry = ToolRegistry()

    result = registry.get_tool("nonexistent")

    assert result is None


def test_registry_unregister_tool():
    """Can unregister a tool"""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    registry.unregister("mock_tool")

    assert "mock_tool" not in registry.list_tools()
    assert registry.get_tool("mock_tool") is None


def test_registry_get_schemas():
    """Can get all tool schemas for LLM"""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    schemas = registry.get_schemas()

    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "mock_tool"
    assert schemas[0]["function"]["description"] == "A mock tool"
    assert "parameters" in schemas[0]["function"]


def test_registry_duplicate_registration():
    """Registering same tool twice replaces the old one"""
    registry = ToolRegistry()
    tool1 = MockTool()
    tool2 = MockTool()

    registry.register(tool1)
    registry.register(tool2)

    assert len(registry.list_tools()) == 1
    assert registry.get_tool("mock_tool") is tool2
