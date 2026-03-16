from job_assistant.job_discovery.models import DiscoveryJob, DiscoveryRunResult, SearchHit
from job_assistant.job_discovery.service import (
    DuckDuckGoSearchClient,
    JobDiscoveryService,
    JobPageExtractor,
    RequestsPageFetcher,
    build_search_spec,
)

__all__ = [
    "DiscoveryJob",
    "DiscoveryRunResult",
    "DuckDuckGoSearchClient",
    "JobDiscoveryService",
    "JobPageExtractor",
    "RequestsPageFetcher",
    "SearchHit",
    "build_search_spec",
]
