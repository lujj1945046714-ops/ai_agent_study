from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_assistant import config
from job_assistant.agent.state import JobAssistantState
from job_assistant.agent.tools import DiscoverJobsTool
from job_assistant.job_discovery import JobPageExtractor, SearchHit, build_search_spec
from job_assistant.job_discovery.service import DuckDuckGoSearchClient, JobDiscoveryService
from job_assistant.persistence.sqlite_store import SQLiteJobStore, SQLiteJobStoreConfig


def _fixture_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "job_discovery" / name


def _patch_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORKDIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "jobs.db")


@pytest.fixture(autouse=True)
def _disable_llm_for_job_discovery(monkeypatch):
    monkeypatch.setattr("job_assistant.modules.analyzer.has_llm_configured", lambda: False)
    monkeypatch.setattr("job_assistant.modules.matcher_enhanced.has_llm_configured", lambda: False)
    monkeypatch.setattr("job_assistant.llm_runtime.has_llm_configured", lambda: False)


def _profile() -> dict:
    return {
        "skills": {
            "Python": {"level": 4, "years": 4},
            "LangChain": {"level": 3, "years": 2},
            "RAG": {"level": 3, "years": 2},
            "FastAPI": {"level": 3, "years": 2},
        },
        "experience_years": 4,
        "target_roles": ["AI Agent 工程师"],
        "preferences": {"cities": ["上海"], "salary_min_k": 20, "salary_max_k": 45},
    }


class FakeSearchClient:
    def __init__(self, hits_by_query: dict[str, list[SearchHit]]):
        self.hits_by_query = hits_by_query
        self.calls: list[str] = []

    def search(self, query: str, *, limit: int = 8):
        self.calls.append(query)
        return self.hits_by_query.get(query, [])[:limit]


class FakePageFetcher:
    def __init__(self, payloads: dict[str, str]):
        self.payloads = payloads

    def fetch(self, url: str) -> str:
        if url not in self.payloads:
            raise RuntimeError(f"missing fixture for {url}")
        return self.payloads[url]


class RaisingSearchClient:
    def search(self, query: str, *, limit: int = 8):
        raise RuntimeError("network unavailable")


def test_duckduckgo_parser_extracts_hits_from_fixture():
    parser = DuckDuckGoSearchClient()
    html_text = _fixture_path("duckduckgo_results.html").read_text(encoding="utf-8")

    hits = parser._parse_results("AI Agent 工程师 上海 招聘", html_text, limit=5)

    assert len(hits) == 2
    assert hits[0].url == "https://jobs.example.com/agent-001"
    assert "AI Agent 工程师" in hits[0].title
    assert "LangChain" in hits[0].snippet


def test_job_page_extractor_prefers_json_ld():
    extractor = JobPageExtractor()
    hit = SearchHit(
        query="AI Agent 工程师 上海 招聘",
        url="https://jobs.example.com/agent-001",
        title="AI Agent 工程师 - 星河科技 - 上海",
        snippet="上海 25-40k 招聘",
    )

    job = extractor.extract(hit, _fixture_path("job_structured.html").read_text(encoding="utf-8"), fallback_city="上海")

    assert job is not None
    assert job.title == "AI Agent 工程师"
    assert job.company == "星河科技"
    assert job.city == "上海"
    assert "LangChain" in job.jd_text


def test_discovery_service_caches_and_persists(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    search_spec = build_search_spec(profile)

    hits = {
        search_spec["queries"][0]["query"]: [
            SearchHit(
                query=search_spec["queries"][0]["query"],
                url="https://jobs.example.com/agent-001",
                title="AI Agent 工程师 - 星河科技 - 上海",
                snippet="上海 25-40k 招聘，负责 LangChain / RAG / Agent 工作流设计。",
            ),
            SearchHit(
                query=search_spec["queries"][0]["query"],
                url="https://jobs.example.com/agent-002",
                title="LLM 应用开发工程师 - 蓝海智能 - 上海",
                snippet="上海 22-35k，负责企业 AI 助手、FastAPI、RAG 系统开发。",
            ),
        ]
    }
    pages = {
        "https://jobs.example.com/agent-001": _fixture_path("job_structured.html").read_text(encoding="utf-8"),
        "https://jobs.example.com/agent-002": _fixture_path("job_generic.html").read_text(encoding="utf-8"),
    }

    store = SQLiteJobStore(SQLiteJobStoreConfig(db_path=config.DB_PATH))
    search_client = FakeSearchClient(hits)
    service = JobDiscoveryService(
        search_client=search_client,
        page_fetcher=FakePageFetcher(pages),
        store=store,
    )

    first = service.discover(profile, max_results=5, refresh=False)
    first_call_count = len(search_client.calls)
    cached = service.discover(profile, max_results=5, refresh=False)

    assert first["status"] == "success"
    assert first["candidate_count"] >= 2
    assert first["new_jobs_count"] >= 2
    assert first["shortlist"][0]["match_score"] >= 0
    assert cached["refresh_mode"] == "cached"
    assert first_call_count >= 1
    assert len(search_client.calls) == first_call_count

    stored = store.get_latest_discovery_result(search_spec["query_key"])
    assert stored is not None
    assert stored["candidate_count"] >= 2
    assert stored["shortlist"]


def test_discover_jobs_tool_updates_state(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    store = SQLiteJobStore(SQLiteJobStoreConfig(db_path=config.DB_PATH))
    state = JobAssistantState(profile=profile, output_dir=config.OUTPUT_DIR)
    tool = DiscoverJobsTool(state, store)

    expected = {
        "status": "success",
        "run_id": "discover-demo",
        "search_spec": {"query_key": "demo"},
        "candidate_count": 1,
        "new_jobs_count": 1,
        "deduped_count": 0,
        "sources_used": ["jobs.example.com"],
        "refresh_mode": "initial",
        "shortlist": [
            {
                "job_id": "disc-demo001",
                "canonical_hash": "demo001",
                "title": "AI Agent 工程师",
                "company": "星河科技",
                "city": "上海",
                "salary": "25-40k",
                "jd_text": "负责基于 LLM 的 Agent 工作流设计与开发，熟悉 Python、LangChain、RAG。",
                "source": "jobs.example.com",
                "source_url": "https://jobs.example.com/agent-001",
                "post_time": "2026-03-10",
                "ranking_score": 88.0,
                "match_score": 84.0,
                "recommendation_reason": "匹配技能：Python, LangChain",
                "analysis": {"required_skills": ["Python", "LangChain"], "summary": "岗位核心是开发 Agent。"},
                "match": {"score": 84, "matched_skills": ["Python", "LangChain"], "skill_gaps": ["Docker"]},
            }
        ],
    }
    monkeypatch.setattr(tool._service, "discover", lambda *args, **kwargs: json.loads(json.dumps(expected)))

    result = tool.execute(max_results=5)

    assert result["status"] == "success"
    assert "disc-demo001" in state.job_store
    assert state.results["disc-demo001"]["match"]["score"] == 84
    assert state.discovered_jobs["disc-demo001"]["title"] == "AI Agent 工程师"


def test_discovery_service_falls_back_when_live_search_fails(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()

    service = JobDiscoveryService(
        search_client=RaisingSearchClient(),
        page_fetcher=FakePageFetcher({}),
        store=None,
    )
    result = service.discover(profile, max_results=5, refresh=True)

    assert result["status"] == "fallback_required"
    assert result["shortlist"] == []
    assert result["error"]


def test_job_page_extractor_skips_blocked_pages():
    extractor = JobPageExtractor()
    hit = SearchHit(
        query="上海 AI Agent 工程师 招聘",
        url="https://www.zhipin.com/job_detail/demo.html",
        title="AI Agent 工程师 - 某公司 - 上海",
        snippet="上海 25-40k 招聘",
    )

    html_text = _fixture_path("job_blocked_zhipin.html").read_text(encoding="utf-8")

    assert extractor.blocked_reason(hit, html_text)
    assert extractor.extract(hit, html_text, fallback_city="上海") is None


def test_discovery_service_relaxes_query_when_boolean_variant_has_no_hits(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    search_spec = build_search_spec(profile)
    query_info = search_spec["queries"][0]

    service = JobDiscoveryService(search_client=FakeSearchClient({}), page_fetcher=FakePageFetcher({}), store=None)
    variants = service._query_variants(query_info)
    assert len(variants) >= 2

    fallback_query = variants[1]
    hits = {
        fallback_query: [
            SearchHit(
                query=fallback_query,
                url="https://jobs.example.com/agent-001",
                title="AI Agent 工程师 - 星河科技 - 上海",
                snippet="上海 25-40k 招聘，负责 LangChain / RAG / Agent 工作流设计。",
            )
        ]
    }
    pages = {
        "https://jobs.example.com/agent-001": _fixture_path("job_structured.html").read_text(encoding="utf-8"),
    }

    service = JobDiscoveryService(
        search_client=FakeSearchClient(hits),
        page_fetcher=FakePageFetcher(pages),
        store=None,
    )
    result = service.discover(profile, max_results=5, refresh=True)

    assert result["status"] == "success"
    assert result["candidate_count"] >= 1
    assert result["diagnostics"]["search"]["variant_count"] >= 2
    assert fallback_query in service._search_client.calls


def test_company_query_accepts_official_job_url_without_job_words_in_title():
    service = JobDiscoveryService(search_client=FakeSearchClient({}), page_fetcher=FakePageFetcher({}), store=None)
    hit = SearchHit(
        query="上海 LLM 官网 招聘",
        url="https://careers.example.com/recruit/social?jobId=123",
        title="Example Inc",
        snippet="上海",
    )

    assert service._looks_like_job_hit(hit, kind="company") is True


def test_job_page_extractor_site_specific_zhaopin_extracts_embedded_json():
    extractor = JobPageExtractor()
    hit = SearchHit(
        query="上海 AI Agent 工程师 招聘",
        url="https://www.zhaopin.com/jobs/demo.html",
        title="AI Agent 工程师-星河科技-上海-智联招聘",
        snippet="上海 25-40k 招聘",
    )

    html_text = _fixture_path("job_zhaopin_embedded.html").read_text(encoding="utf-8")
    job = extractor.extract(hit, html_text, fallback_city="上海")

    assert job is not None
    assert job.title == "AI Agent 工程师"
    assert job.company == "星河科技"
    assert job.city == "上海"
    assert "LangChain" in job.jd_text


def test_job_page_extractor_site_specific_nowcoder_extracts_embedded_json():
    extractor = JobPageExtractor()
    hit = SearchHit(
        query="上海 AI Agent 工程师 招聘",
        url="https://www.nowcoder.com/jobs/demo.html",
        title="AI Agent 工程师-星河科技-上海-牛客网",
        snippet="上海 25-40k 招聘",
    )

    html_text = _fixture_path("job_nowcoder_embedded.html").read_text(encoding="utf-8")
    job = extractor.extract(hit, html_text, fallback_city="上海")

    assert job is not None
    assert job.title == "AI Agent 工程师"
    assert job.company == "星河科技"
    assert job.city == "上海"
    assert "RAG" in job.jd_text


def test_discovery_service_filters_blocked_pages(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    search_spec = build_search_spec(profile)

    query = search_spec["queries"][0]["query"]
    hits = {
        query: [
            SearchHit(query=query, url="https://www.zhipin.com/job_detail/demo.html", title="请稍候", snippet=""),
            SearchHit(
                query=query,
                url="https://jobs.example.com/agent-001",
                title="AI Agent 工程师 - 星河科技 - 上海",
                snippet="上海 25-40k 招聘，负责 LangChain / RAG / Agent 工作流设计。",
            ),
        ]
    }
    pages = {
        "https://www.zhipin.com/job_detail/demo.html": _fixture_path("job_blocked_zhipin.html").read_text(encoding="utf-8"),
        "https://jobs.example.com/agent-001": _fixture_path("job_structured.html").read_text(encoding="utf-8"),
    }

    service = JobDiscoveryService(
        search_client=FakeSearchClient(hits),
        page_fetcher=FakePageFetcher(pages),
        store=None,
    )

    result = service.discover(profile, max_results=5, refresh=True)

    assert result["status"] == "success"
    assert result["candidate_count"] >= 1
    assert result["diagnostics"]["fetch"]["blocked"] >= 1
    assert all(job["title"] != "请稍候" for job in result["shortlist"])


def test_discovery_service_follows_listing_pages(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    search_spec = build_search_spec(profile)

    query = search_spec["queries"][0]["query"]
    hits = {
        query: [
            SearchHit(
                query=query,
                url="https://jobs.example.com/careers/listing",
                title="加入我们 - 星河科技 Careers",
                snippet="",
            )
        ]
    }
    pages = {
        "https://jobs.example.com/careers/listing": _fixture_path("job_listing_company.html").read_text(encoding="utf-8"),
        "https://jobs.example.com/agent-001": _fixture_path("job_structured.html").read_text(encoding="utf-8"),
        "https://jobs.example.com/agent-002": _fixture_path("job_generic.html").read_text(encoding="utf-8"),
        "https://jobs.example.com/agent-003": "<html><head><title>RAG 工程师 - 星河科技 - 上海</title></head><body>职位描述：负责 RAG / 向量数据库 / 检索增强生成系统建设。</body></html>",
    }

    service = JobDiscoveryService(
        search_client=FakeSearchClient(hits),
        page_fetcher=FakePageFetcher(pages),
        store=None,
    )
    result = service.discover(profile, max_results=5, refresh=True)

    assert result["status"] == "success"
    assert result["candidate_count"] >= 2
    assert result["diagnostics"]["fetch"]["listing_follow"]["listing_followed"] >= 1
    assert any(job.get("raw_payload", {}).get("followed_from") for job in result["shortlist"])


def test_discovery_service_falls_back_to_company_sites_when_job_boards_blocked(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    search_spec = build_search_spec(profile)

    balanced_queries = [q["query"] for q in search_spec["queries"] if q.get("kind") == "balanced"]
    company_queries = [q["query"] for q in search_spec["queries"] if q.get("kind") == "company"]
    assert balanced_queries and company_queries

    hits: dict[str, list[SearchHit]] = {}
    for query in balanced_queries:
        hits[query] = [
            SearchHit(
                query=query,
                url="https://www.zhipin.com/job_detail/demo.html",
                title="请稍候",
                snippet="",
            )
        ]

    for query in company_queries:
        hits[query] = [
            SearchHit(
                query=query,
                url="https://jobs.example.com/agent-001",
                title="AI Agent 工程师 - 星河科技 - 上海",
                snippet="上海 25-40k 招聘",
            )
        ]

    pages = {
        "https://www.zhipin.com/job_detail/demo.html": _fixture_path("job_blocked_zhipin.html").read_text(encoding="utf-8"),
        "https://jobs.example.com/agent-001": _fixture_path("job_structured.html").read_text(encoding="utf-8"),
    }

    service = JobDiscoveryService(
        search_client=FakeSearchClient(hits),
        page_fetcher=FakePageFetcher(pages),
        store=None,
    )
    result = service.discover(profile, max_results=5, refresh=True)

    assert result["status"] == "success"
    assert result["candidate_count"] >= 1
    assert result["diagnostics"]["phases"]["phase2"]["triggered"] is True


def test_discovery_service_dedupes_across_sites(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    search_spec = build_search_spec(profile)

    query = search_spec["queries"][0]["query"]
    hits = {
        query: [
            SearchHit(
                query=query,
                url="https://jobs.example.com/agent-001",
                title="AI Agent 工程师 - 星河科技 - 上海",
                snippet="上海 25-40k 招聘",
            ),
            SearchHit(
                query=query,
                url="https://www.zhaopin.com/jobs/demo.html",
                title="AI Agent 工程师-星河科技-上海-智联招聘",
                snippet="上海 25-40k 招聘",
            ),
        ]
    }
    pages = {
        "https://jobs.example.com/agent-001": _fixture_path("job_structured.html").read_text(encoding="utf-8"),
        "https://www.zhaopin.com/jobs/demo.html": _fixture_path("job_zhaopin_embedded.html").read_text(encoding="utf-8"),
    }

    service = JobDiscoveryService(
        search_client=FakeSearchClient(hits),
        page_fetcher=FakePageFetcher(pages),
        store=None,
    )
    result = service.discover(profile, max_results=5, refresh=True)

    assert result["status"] == "success"
    assert result["deduped_count"] >= 1
    assert result["candidate_count"] == 1


def test_discovery_service_limits_deep_analysis_budget(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    monkeypatch.setattr(config, "MAX_DEEP_ANALYSIS", 3)
    monkeypatch.setattr("job_assistant.llm_runtime.has_llm_configured", lambda: True)

    calls = {"analyze": 0, "match": 0}

    def _fake_analyze(text: str):
        calls["analyze"] += 1
        return {"required_skills": ["Python"], "nice_to_have": [], "core_work": [], "tech_stack": ["Python"], "job_level": "中级", "summary": "ok"}

    def _fake_match(profile_obj, analysis_obj):
        calls["match"] += 1
        return {"score": 80, "matched_skills": ["Python"], "skill_gaps": []}

    monkeypatch.setattr("job_assistant.job_discovery.service.analyze_jd", _fake_analyze)
    monkeypatch.setattr("job_assistant.job_discovery.service.match_job_enhanced", _fake_match)

    search_spec = build_search_spec(profile)
    query = search_spec["queries"][0]["query"]

    hits_list = []
    pages = {}
    for i in range(8):
        url = f"https://jobs.example.com/agent-{i:03d}"
        hits_list.append(
            SearchHit(
                query=query,
                url=url,
                title=f"AI Agent 工程师 - 公司{i} - 上海",
                snippet="上海 25-40k 招聘，负责 Python / LangChain / RAG。",
            )
        )
        pages[url] = f"<html><head><title>AI Agent 工程师 - 公司{i} - 上海</title></head><body>职位描述：Python LangChain RAG</body></html>"

    hits = {query: hits_list}
    service = JobDiscoveryService(
        search_client=FakeSearchClient(hits),
        page_fetcher=FakePageFetcher(pages),
        store=None,
    )

    result = service.discover(profile, max_results=5, refresh=True)

    assert result["status"] == "success"
    assert calls["analyze"] == 3
    assert calls["match"] == 3


def test_discovery_service_emits_progress_callback(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    profile = _profile()
    search_spec = build_search_spec(profile)
    query = search_spec["queries"][0]["query"]

    hits = {
        query: [
            SearchHit(
                query=query,
                url="https://jobs.example.com/agent-001",
                title="AI Agent 工程师 - 星河科技 - 上海",
                snippet="上海 25-40k 招聘，负责 LangChain / RAG / Agent 工作流设计。",
            )
        ]
    }
    pages = {"https://jobs.example.com/agent-001": _fixture_path("job_structured.html").read_text(encoding="utf-8")}

    events: list[tuple[str, float, str]] = []

    def _cb(stage: str, progress: float, message: str) -> None:
        events.append((stage, progress, message))

    service = JobDiscoveryService(search_client=FakeSearchClient(hits), page_fetcher=FakePageFetcher(pages), store=None)
    result = service.discover(profile, max_results=5, refresh=True, progress_callback=_cb)

    assert result["status"] == "success"
    stages = {item[0] for item in events}
    assert {"search", "fetch", "rank", "done"} & stages
