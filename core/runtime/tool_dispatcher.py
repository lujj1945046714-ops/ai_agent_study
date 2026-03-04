import logging
from typing import List, Dict, Any
from dataclasses import dataclass
from core.tools.registry import ToolRegistry
from core.gateway.hooks import HooksRegistry

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
    output: Dict[str, Any] = None
    error: str = None


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
        # Trigger before_tool hook
        self.hooks.trigger("before_tool", {
            "tool_name": tool_call.name,
            "arguments": tool_call.arguments
        })

        # Get tool
        tool = self.registry.get_tool(tool_call.name)
        if tool is None:
            result = ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=f"Tool '{tool_call.name}' not found"
            )
            self.hooks.trigger("after_tool", {"result": result})
            return result

        # Execute tool
        try:
            output = tool.execute(**tool_call.arguments)
            result = ToolResult(
                tool_call_id=tool_call.id,
                success=True,
                output=output
            )
        except Exception as e:
            logger.error(f"Tool {tool_call.name} execution failed: {e}", exc_info=True)
            result = ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=str(e)
            )

        # Trigger after_tool hook
        self.hooks.trigger("after_tool", {"result": result})

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
