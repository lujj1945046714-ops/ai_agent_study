from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class RepoSpec:
    original: str
    source_type: str
    url: str
    display_name: str
    owner: str = ""
    name: str = ""
    ref: str = ""
    local_path: Optional[Path] = None
    clone_url: str = ""
    archive_urls: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(self)


@dataclass
class RepoAuditResult:
    task_id: str
    repo: Dict[str, Any]
    verdict: str
    summary: str
    usable_modules: List[Dict[str, Any]]
    highlights: List[str]
    run_summary: Dict[str, Any]
    risks: List[str]
    artifacts: Dict[str, Any]
    workspace: Dict[str, Any]
    cleanup: Dict[str, Any]
    static_analysis: Dict[str, Any]
    expected_capabilities: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(self)
