from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class JobAssistantState:
    profile: Dict[str, Any]
    output_dir: Path
    job_store: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    repo_audits: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    discovered_jobs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    discovery_runs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
