from typing import Dict, List, Optional

from agent_framework.tools.base import BaseTool


class ToolRegistry:
    """
    Registry for managing tools dynamically.

    Supports:
    - Register/unregister tools
    - Query tools by name
    - Generate schemas for LLM
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool instance to register
        """
        self._tools[tool.name] = tool

    def unregister(self, tool_name: str) -> None:
        """
        Unregister a tool.

        Args:
            tool_name: Name of tool to unregister
        """
        self._tools.pop(tool_name, None)

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """
        Get tool by name.

        Args:
            tool_name: Tool name

        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """
        List all registered tool names.

        Returns:
            List of tool names
        """
        return list(self._tools.keys())

    def get_schemas(self) -> List[Dict]:
        """
        Get all tool schemas in OpenAI function calling format.

        Returns:
            List of tool schemas
        """
        schemas: List[Dict] = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.schema,
                    },
                }
            )
        return schemas

