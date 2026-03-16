from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

Message = Dict[str, Any]
ToolSchema = Dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    tool_calls: List[ToolCall]
    metadata: Optional[Dict[str, Any]] = None


OnToken = Callable[[str], None]
