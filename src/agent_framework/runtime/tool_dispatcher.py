import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from agent_framework.gateway.hooks import HooksRegistry
from agent_framework.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Tool call request"""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Tool execution result"""

    tool_call_id: str
    success: bool
    output: Dict[str, Any] | None = None
    error: str | None = None


class ToolDispatcher:
    """
    Dispatch tool calls to registered tools.
    """

    def __init__(self, tool_registry: ToolRegistry, hooks: HooksRegistry):
        """
        Initialize dispatcher.

        Args:
            tool_registry: Tool registry
            hooks: Hooks registry
        """
        self.registry = tool_registry
        self.hooks = hooks

    def dispatch(self, tool_call: ToolCall) -> ToolResult:
        """
        Dispatch single tool call.

        Args:
            tool_call: Tool call request

        Returns:
            Tool result
        """
        self.hooks.trigger(
            "before_tool",
            {
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        )

        tool = self.registry.get_tool(tool_call.name)
        if tool is None:
            result = ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=f"Tool '{tool_call.name}' not found",
            )
            self.hooks.trigger(
                "after_tool",
                {
                    "tool_name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "result": result,
                },
            )
            return result

        try:
            output = tool.execute(**tool_call.arguments)
            result = ToolResult(tool_call_id=tool_call.id, success=True, output=output)
        except Exception as exc:
            logger.error("Tool %s execution failed: %s", tool_call.name, exc, exc_info=True)
            result = ToolResult(tool_call_id=tool_call.id, success=False, error=str(exc))

        self.hooks.trigger(
            "after_tool",
            {
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": result,
            },
        )
        return result

    def dispatch_batch(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """
        Dispatch multiple tool calls.

        Args:
            tool_calls: List of tool calls

        Returns:
            List of tool results
        """
        return [self.dispatch(tc) for tc in tool_calls]
