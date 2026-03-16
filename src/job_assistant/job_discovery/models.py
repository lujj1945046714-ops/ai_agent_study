from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class SearchHit:
    query: str
    url: str
    title: str
    snippet: str = ""
    source: str = "web_search"

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(self)


@dataclass
class DiscoveryJob:
    canonical_hash: str
    job_id: str
    title: str
    company: str
    city: str
    salary: str
    jd_text: str
    source: str
    source_url: str
    post_time: str
    search_query: str
    fetched_at: str
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    ranking_score: float = 0.0
    match_score: float = 0.0
    recommendation_reason: str = ""
    analysis: Dict[str, Any] = field(default_factory=dict)
    match: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(self)


@dataclass
class DiscoveryRunResult:
    status: str
    run_id: str
    search_spec: Dict[str, Any]
    candidate_count: int
    new_jobs_count: int
    deduped_count: int
    sources_used: List[str]
    refresh_mode: str
    shortlist: List[Dict[str, Any]]
    error: str = ""
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(self)
