from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """
    Abstract base class for all tools.

    All tools must implement:
    - name: Tool identifier
    - description: Human-readable description
    - schema: OpenAI function calling schema
    - execute: Tool execution logic
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (unique identifier)"""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM"""
        raise NotImplementedError

    @property
    @abstractmethod
    def schema(self) -> Dict[str, Any]:
        """
        OpenAI function calling schema.

        Format:
        {
            "type": "object",
            "properties": {
                "param_name": {
                    "type": "string",
                    "description": "..."
                }
            },
            "required": ["param_name"]
        }
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool parameters matching schema

        Returns:
            Dict with execution result
        """
        raise NotImplementedError

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """
        Validate parameters against schema (optional override).

        Args:
            params: Parameters to validate

        Returns:
            True if valid, False otherwise
        """
        required = self.schema.get("required", [])
        return all(key in params for key in required)

