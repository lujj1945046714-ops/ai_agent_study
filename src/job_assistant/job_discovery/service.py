from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
import logging
import os
import re
import threading
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from job_assistant import config
from job_assistant.job_discovery.models import DiscoveryJob, DiscoveryRunResult, SearchHit
from job_assistant.llm_runtime import has_llm_configured
from job_assistant.modules.analyzer import analyze_jd
from job_assistant.modules.matcher_enhanced import match_job_enhanced

logger = logging.getLogger(__name__)

_ROLE_EXPANSIONS = {
    "agent": ["AI Agent 工程师", "智能体工程师", "Agent 平台工程师", "多 Agent 工程师"],
    "llm": ["LLM 应用开发工程师", "大模型应用工程师", "AI 应用工程师"],
    "rag": ["RAG 工程师", "知识库问答工程师"],
    "backend": ["后端工程师", "平台工程师"],
}
_JOB_HINTS = (
    "招聘",
    "职位",
    "工程师",
    "岗位",
    "job",
    "jobs",
    "career",
    "careers",
    "hiring",
)
_SPLIT_SEPARATORS = ("|", "-", "_", "·", "—")
_CITY_FALLBACKS = ("北京", "上海", "深圳", "广州", "杭州", "成都", "苏州", "武汉", "南京", "Remote")

JOB_BOARD_DOMAINS: set[str] = {
    "zhipin.com",
    "zhaopin.com",
    "51job.com",
    "liepin.com",
    "lagou.com",
    "kanzhun.com",
}

ATS_DOMAINS: set[str] = {
    "ashbyhq.com",
    "greenhouse.io",
    "icims.com",
    "lever.co",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "taleo.net",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _strip_tags(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", value)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    return _normalize_spaces(html.unescape(cleaned))


def _salary_overlap(salary_text: str, min_k: int, max_k: int) -> bool:
    normalized = (salary_text or "").lower().replace(" ", "")
    match = re.search(r"(\d{1,3})(?:k|千)?[-~至](\d{1,3})(?:k|千)?", normalized)
    if not match:
        return True
    low = int(match.group(1))
    high = int(match.group(2))
    return not (high < min_k or low > max_k)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    path = parsed.path.rstrip("/")
    return f"{scheme}://{parsed.netloc.lower()}{path}"


def _build_canonical_hash(title: str, company: str, city: str, url: str) -> str:
    base = "|".join(
        [
            _normalize_spaces(title).lower(),
            _normalize_spaces(company).lower(),
            _normalize_spaces(city).lower(),
            _normalize_url(url),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _build_identity_key(title: str, company: str, city: str) -> str:
    """Cross-site dedupe key (intentionally ignores URL)."""
    base = "|".join(
        [
            _normalize_spaces(title).lower(),
            _normalize_spaces(company).lower(),
            _normalize_spaces(city).lower(),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _job_quality_score(job: DiscoveryJob) -> float:
    """Prefer richer pages when deduping."""
    score = 0.0
    score += min(float(len(job.jd_text or "")), 4000.0)
    if job.company and job.company not in {"未知公司", "未知"}:
        score += 250.0
    if job.city and job.city not in {"未知", ""}:
        score += 150.0
    if job.salary and job.salary not in {"面议", ""}:
        score += 120.0
    if job.post_time:
        score += 80.0
    return score


def _job_id_from_hash(canonical_hash: str) -> str:
    return f"disc-{canonical_hash[:12]}"


def _infer_source(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc or "unknown"


def _build_query_key(search_spec: Dict[str, Any]) -> str:
    normalized = json.dumps(search_spec, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _domain_matches(domain: str, base_domain: str) -> bool:
    domain = (domain or "").lower()
    base_domain = (base_domain or "").lower()
    if not domain or not base_domain:
        return False
    return domain == base_domain or domain.endswith(f".{base_domain}")


def _domain_in(domain: str, base_domains: set[str]) -> bool:
    return any(_domain_matches(domain, base) for base in base_domains)


def _format_site_exclusions(domains: set[str], *, max_sites: int = 6) -> str:
    if not domains:
        return ""
    selected = sorted(domains)[: max(0, int(max_sites))]
    return " ".join(f"-site:{domain}" for domain in selected if domain)


def _expand_role_keywords(keywords: Sequence[str], profile: Dict[str, Any]) -> List[str]:
    normalized = [_normalize_spaces(keyword) for keyword in keywords if _normalize_spaces(keyword)]
    expanded: List[str] = []

    def _push(value: str) -> None:
        if value and value not in expanded:
            expanded.append(value)

    for keyword in normalized:
        _push(keyword)
        low = keyword.lower()
        for key, values in _ROLE_EXPANSIONS.items():
            if key in low:
                for value in values:
                    _push(value)

    if not expanded:
        skills = " ".join(str(skill) for skill in profile.get("skills", {})).lower()
        if "agent" in skills or "langchain" in skills or "llamaindex" in skills:
            for value in _ROLE_EXPANSIONS["agent"]:
                _push(value)
        if "rag" in skills or "向量" in skills:
            for value in _ROLE_EXPANSIONS["rag"]:
                _push(value)
        if "fastapi" in skills or "backend" in skills:
            for value in _ROLE_EXPANSIONS["backend"]:
                _push(value)

    if not expanded:
        expanded = ["AI Agent 工程师", "LLM 应用开发工程师", "Agent 平台工程师"]

    return expanded[:6]


def build_search_spec(
    profile: Dict[str, Any],
    *,
    cities: Sequence[str] | None = None,
    keywords: Sequence[str] | None = None,
    salary_min_k: int | None = None,
    salary_max_k: int | None = None,
) -> Dict[str, Any]:
    preferences = profile.get("preferences", {})
    resolved_cities = [_normalize_spaces(city) for city in (cities or preferences.get("cities", [])) if _normalize_spaces(city)]
    resolved_keywords = _expand_role_keywords(keywords or profile.get("target_roles", []), profile)
    salary_min = int(salary_min_k if salary_min_k is not None else preferences.get("salary_min_k", 0) or 0)
    salary_max = int(salary_max_k if salary_max_k is not None else preferences.get("salary_max_k", 999) or 999)
    experience_years = int(profile.get("experience_years", 0) or 0)

    def _quote_term(value: str) -> str:
        cleaned = _normalize_spaces(value).replace('"', "")
        if not cleaned:
            return ""
        return f'"{cleaned}"'

    def _or_group(values: Sequence[str]) -> str:
        quoted = [_quote_term(val) for val in values if _quote_term(val)]
        if not quoted:
            return ""
        if len(quoted) == 1:
            return quoted[0]
        return f"({' OR '.join(quoted)})"

    query_pairs: List[Dict[str, Any]] = []
    seen_queries: set[str] = set()
    cities_for_queries = resolved_cities[:2] or [""]
    keyword_group = _or_group(resolved_keywords[:3])
    company_keyword_group = _or_group(resolved_keywords[:2] or resolved_keywords[:1])
    exclusions = _format_site_exclusions(JOB_BOARD_DOMAINS, max_sites=6)

    for city in cities_for_queries:
        city_token = _normalize_spaces(city)

        balanced_tokens = [
            city_token,
            keyword_group,
            "(招聘 OR 职位 OR 岗位 OR hiring)",
        ]
        balanced_query = " ".join(token for token in balanced_tokens if token)
        if balanced_query and balanced_query not in seen_queries:
            seen_queries.add(balanced_query)
            query_pairs.append(
                {
                    "query": balanced_query,
                    "city": city_token,
                    "kind": "balanced",
                    "keywords": list(resolved_keywords[:3]),
                }
            )

        company_tokens = [
            city_token,
            company_keyword_group,
            '("加入我们" OR "人才招聘" OR careers OR jobs)',
            exclusions,
        ]
        company_query = " ".join(token for token in company_tokens if token)
        if company_query and company_query not in seen_queries:
            seen_queries.add(company_query)
            query_pairs.append(
                {
                    "query": company_query,
                    "city": city_token,
                    "kind": "company",
                    "keywords": list(resolved_keywords[:2] or resolved_keywords[:1]),
                }
            )

        if len(query_pairs) >= 4:
            break

    search_spec = {
        "cities": resolved_cities,
        "keywords": resolved_keywords,
        "salary_min_k": salary_min,
        "salary_max_k": salary_max,
        "experience_years": experience_years,
        "queries": query_pairs,
    }
    search_spec["query_key"] = _build_query_key(search_spec)
    return search_spec


class DuckDuckGoSearchClient:
    search_endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self, *, session: requests.Session | None = None):
        self._session = session or requests.Session()

    def search(self, query: str, *, limit: int = 8) -> List[SearchHit]:
        response = self._session.get(
            self.search_endpoint,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=(config.DISCOVERY_FETCH_CONNECT_TIMEOUT_S, config.DISCOVERY_FETCH_READ_TIMEOUT_S),
            proxies=_get_proxies(),
        )
        response.raise_for_status()
        return self._parse_results(query, response.text, limit=limit)

    def _parse_results(self, query: str, html_text: str, *, limit: int) -> List[SearchHit]:
        results: List[SearchHit] = []
        anchor_pattern = re.compile(r'(?is)<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>')
        matches = list(anchor_pattern.finditer(html_text))
        for index, match in enumerate(matches):
            href = self._resolve_ddg_redirect(match.group("href"))
            title = _strip_tags(match.group("title"))
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(html_text)
            body = html_text[match.end() : next_start]
            snippet_match = re.search(r'(?is)<(?:a|div)[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|div)>', body)
            snippet = _strip_tags(snippet_match.group("snippet")) if snippet_match else ""
            if not href or not title:
                continue
            results.append(SearchHit(query=query, url=href, title=title, snippet=snippet))
            if len(results) >= limit:
                break
        return results

    def _resolve_ddg_redirect(self, href: str) -> str:
        candidate = html.unescape(href)
        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        parsed = urlparse(candidate)
        query = parse_qs(parsed.query)
        if "uddg" in query:
            return query["uddg"][0]
        if candidate.startswith("/l/?"):
            query = parse_qs(candidate.split("?", 1)[1])
            return query.get("uddg", [""])[0]
        return candidate


class RequestsPageFetcher:
    def __init__(self, *, session: requests.Session | None = None):
        self._session = session
        self._local = threading.local()

    def _get_session(self) -> requests.Session:
        if self._session is not None:
            return self._session
        cached = getattr(self._local, "session", None)
        if cached is None:
            cached = requests.Session()
            setattr(self._local, "session", cached)
        return cached

    def fetch(self, url: str) -> str:
        response = self._get_session().get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=(config.DISCOVERY_FETCH_CONNECT_TIMEOUT_S, config.DISCOVERY_FETCH_READ_TIMEOUT_S),
            proxies=_get_proxies(),
        )
        response.raise_for_status()
        return response.text


class JobPageExtractor:
    def extract(self, hit: SearchHit, html_text: str, *, fallback_city: str = "") -> DiscoveryJob | None:
        if self.blocked_reason(hit, html_text):
            return None
        structured = self._extract_json_ld(hit, html_text, fallback_city=fallback_city)
        if structured is not None:
            return structured
        specialized = self._extract_site_specific(hit, html_text, fallback_city=fallback_city)
        if specialized is not None:
            return specialized
        return self._extract_heuristic(hit, html_text, fallback_city=fallback_city)

    def blocked_reason(self, hit: SearchHit, html_text: str) -> str:
        """Detect anti-bot / login interstitial pages and return a short reason key."""
        url_low = (hit.url or "").lower()
        if any(token in url_low for token in ("login", "verify", "captcha", "security-check")):
            return "blocked_url"

        title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
        page_title = _strip_tags(title_match.group(1)) if title_match else ""
        title_low = page_title.lower()

        title_markers = (
            "请稍候",
            "访问验证",
            "安全验证",
            "验证码",
            "验证",
            "robot",
            "blocked",
            "forbidden",
        )
        if any(marker.lower() in title_low for marker in title_markers):
            return "blocked_title"

        head_preview = (html_text or "")[:10000].lower()
        if any(widget in head_preview for widget in ("geetest", "g-recaptcha", "cf-turnstile")):
            return "blocked_captcha_widget"
        if "访问过于频繁" in head_preview or "system busy" in head_preview:
            return "blocked_rate_limited"
        if "扫码登录" in head_preview and "zhipin.com" in url_low:
            return "blocked_login_required"
        return ""

    def _extract_site_specific(self, hit: SearchHit, html_text: str, *, fallback_city: str = "") -> DiscoveryJob | None:
        netloc = urlparse(hit.url).netloc.lower()
        if "zhipin.com" in netloc:
            return self._extract_zhipin(hit, html_text, fallback_city=fallback_city)
        if "zhaopin.com" in netloc:
            return self._extract_zhaopin(hit, html_text, fallback_city=fallback_city)
        if "nowcoder.com" in netloc:
            return self._extract_nowcoder(hit, html_text, fallback_city=fallback_city)
        return None

    def _extract_json_ld(self, hit: SearchHit, html_text: str, *, fallback_city: str = "") -> DiscoveryJob | None:
        for payload in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html_text):
            parsed = self._parse_json_payload(payload)
            for item in self._iter_json_nodes(parsed):
                type_value = item.get("@type") or item.get("type")
                if type_value == "JobPosting":
                    title = _normalize_spaces(str(item.get("title", ""))) or self._fallback_title(hit.title)
                    company = self._company_from_json(item) or self._company_from_text(hit.title, hit.snippet)
                    city = self._city_from_json(item) or fallback_city or self._city_from_text(hit.title, hit.snippet)
                    salary = self._salary_from_json(item) or self._salary_from_text(hit.snippet)
                    description = _strip_tags(str(item.get("description", ""))) or hit.snippet or hit.title
                    post_time = _normalize_spaces(str(item.get("datePosted", "")))
                    if not title:
                        continue
                    canonical_hash = _build_canonical_hash(title, company, city, hit.url)
                    return DiscoveryJob(
                        canonical_hash=canonical_hash,
                        job_id=_job_id_from_hash(canonical_hash),
                        title=title,
                        company=company or "未知公司",
                        city=city or "未知",
                        salary=salary or "面议",
                        jd_text=description[:4000],
                        source=_infer_source(hit.url),
                        source_url=hit.url,
                        post_time=post_time,
                        search_query=hit.query,
                        fetched_at=_utc_now(),
                        raw_payload={"search_hit": hit.to_dict(), "structured_job": item},
                    )
        return None

    def _extract_heuristic(self, hit: SearchHit, html_text: str, *, fallback_city: str = "") -> DiscoveryJob | None:
        page_title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
        page_title = _strip_tags(page_title_match.group(1)) if page_title_match else ""
        title = self._fallback_title(page_title or hit.title)
        company = self._company_from_text(page_title or hit.title, _strip_tags(html_text[:4000]) or hit.snippet)
        city = fallback_city or self._city_from_text(page_title, hit.snippet, html_text)
        salary = self._salary_from_text(html_text, hit.snippet)
        description = self._description_from_html(html_text, hit.snippet)
        if not title:
            return None
        canonical_hash = _build_canonical_hash(title, company, city, hit.url)
        return DiscoveryJob(
            canonical_hash=canonical_hash,
            job_id=_job_id_from_hash(canonical_hash),
            title=title,
            company=company or "未知公司",
            city=city or "未知",
            salary=salary or "面议",
            jd_text=description[:4000],
            source=_infer_source(hit.url),
            source_url=hit.url,
            post_time=self._post_time_from_text(html_text, hit.snippet),
            search_query=hit.query,
            fetched_at=_utc_now(),
            raw_payload={"search_hit": hit.to_dict()},
        )

    def _extract_embedded_json_string(self, html_text: str, key: str) -> str:
        pattern = re.compile(r'"%s"\s*:\s*"(?P<val>(?:\\.|[^"\\])*)"' % re.escape(key))
        match = pattern.search(html_text)
        if not match:
            return ""
        raw = match.group("val")
        try:
            return _normalize_spaces(str(json.loads(f'"{raw}"')))
        except Exception:
            return _normalize_spaces(raw.replace("\\n", "\n").replace("\\t", "\t"))

    def _extract_zhipin(self, hit: SearchHit, html_text: str, *, fallback_city: str = "") -> DiscoveryJob | None:
        title = (
            self._extract_embedded_json_string(html_text, "jobName")
            or self._extract_embedded_json_string(html_text, "jobTitle")
        )
        company = (
            self._extract_embedded_json_string(html_text, "brandName")
            or self._extract_embedded_json_string(html_text, "companyName")
        )
        city = (
            self._extract_embedded_json_string(html_text, "cityName")
            or self._extract_embedded_json_string(html_text, "city")
        )
        salary = (
            self._extract_embedded_json_string(html_text, "salaryDesc")
            or self._extract_embedded_json_string(html_text, "salary")
        )
        description = (
            self._extract_embedded_json_string(html_text, "jobDescription")
            or self._extract_embedded_json_string(html_text, "description")
        )

        page_title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
        page_title = _strip_tags(page_title_match.group(1)) if page_title_match else ""

        title = _normalize_spaces(title) or self._fallback_title(page_title or hit.title)
        company = _normalize_spaces(company) or self._company_from_text(page_title or hit.title, hit.snippet)
        city = _normalize_spaces(city) or fallback_city or self._city_from_text(page_title, hit.snippet)
        salary = _normalize_spaces(salary) or self._salary_from_text(html_text, hit.snippet)
        if not description:
            description = self._description_from_html(html_text, hit.snippet)
        else:
            description = _strip_tags(description)

        if not title:
            return None
        canonical_hash = _build_canonical_hash(title, company, city, hit.url)
        return DiscoveryJob(
            canonical_hash=canonical_hash,
            job_id=_job_id_from_hash(canonical_hash),
            title=title,
            company=company or "未知公司",
            city=city or "未知",
            salary=salary or "面议",
            jd_text=description[:4000],
            source=_infer_source(hit.url),
            source_url=hit.url,
            post_time=self._post_time_from_text(html_text, hit.snippet),
            search_query=hit.query,
            fetched_at=_utc_now(),
            raw_payload={"search_hit": hit.to_dict(), "site_extractor": "zhipin"},
        )

    def _extract_zhaopin(self, hit: SearchHit, html_text: str, *, fallback_city: str = "") -> DiscoveryJob | None:
        title = (
            self._extract_embedded_json_string(html_text, "jobName")
            or self._extract_embedded_json_string(html_text, "jobTitle")
        )
        company = (
            self._extract_embedded_json_string(html_text, "companyName")
            or self._extract_embedded_json_string(html_text, "company")
        )
        city = (
            self._extract_embedded_json_string(html_text, "cityName")
            or self._extract_embedded_json_string(html_text, "workCity")
            or self._extract_embedded_json_string(html_text, "city")
        )
        salary = (
            self._extract_embedded_json_string(html_text, "salary")
            or self._extract_embedded_json_string(html_text, "salaryDesc")
        )
        description = (
            self._extract_embedded_json_string(html_text, "jobDescription")
            or self._extract_embedded_json_string(html_text, "jobDesc")
            or self._extract_embedded_json_string(html_text, "description")
        )
        post_time = (
            self._extract_embedded_json_string(html_text, "publishTime")
            or self._extract_embedded_json_string(html_text, "datePosted")
        )

        page_title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
        page_title = _strip_tags(page_title_match.group(1)) if page_title_match else ""

        title = _normalize_spaces(title) or self._fallback_title(page_title or hit.title)
        company = _normalize_spaces(company) or self._company_from_text(page_title or hit.title, hit.snippet)
        city = _normalize_spaces(city) or fallback_city or self._city_from_text(page_title, hit.snippet)
        salary = _normalize_spaces(salary) or self._salary_from_text(html_text, hit.snippet)
        if not description:
            description = self._description_from_html(html_text, hit.snippet)
        else:
            description = _strip_tags(description)

        if not title:
            return None
        canonical_hash = _build_canonical_hash(title, company, city, hit.url)
        return DiscoveryJob(
            canonical_hash=canonical_hash,
            job_id=_job_id_from_hash(canonical_hash),
            title=title,
            company=company or "未知公司",
            city=city or "未知",
            salary=salary or "面议",
            jd_text=description[:4000],
            source=_infer_source(hit.url),
            source_url=hit.url,
            post_time=_normalize_spaces(post_time),
            search_query=hit.query,
            fetched_at=_utc_now(),
            raw_payload={"search_hit": hit.to_dict(), "site_extractor": "zhaopin"},
        )

    def _extract_nowcoder(self, hit: SearchHit, html_text: str, *, fallback_city: str = "") -> DiscoveryJob | None:
        title = (
            self._extract_embedded_json_string(html_text, "jobName")
            or self._extract_embedded_json_string(html_text, "jobTitle")
        )
        company = (
            self._extract_embedded_json_string(html_text, "companyName")
            or self._extract_embedded_json_string(html_text, "company")
        )
        city = (
            self._extract_embedded_json_string(html_text, "cityName")
            or self._extract_embedded_json_string(html_text, "location")
            or self._extract_embedded_json_string(html_text, "city")
        )
        salary = (
            self._extract_embedded_json_string(html_text, "salary")
            or self._extract_embedded_json_string(html_text, "salaryDesc")
        )
        description = (
            self._extract_embedded_json_string(html_text, "jobDescription")
            or self._extract_embedded_json_string(html_text, "jobDesc")
            or self._extract_embedded_json_string(html_text, "description")
            or self._extract_embedded_json_string(html_text, "content")
        )
        post_time = (
            self._extract_embedded_json_string(html_text, "publishTime")
            or self._extract_embedded_json_string(html_text, "updateTime")
        )

        page_title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
        page_title = _strip_tags(page_title_match.group(1)) if page_title_match else ""

        title = _normalize_spaces(title) or self._fallback_title(page_title or hit.title)
        company = _normalize_spaces(company) or self._company_from_text(page_title or hit.title, hit.snippet)
        city = _normalize_spaces(city) or fallback_city or self._city_from_text(page_title, hit.snippet)
        salary = _normalize_spaces(salary) or self._salary_from_text(html_text, hit.snippet)
        if not description:
            description = self._description_from_html(html_text, hit.snippet)
        else:
            description = _strip_tags(description)

        if not title:
            return None
        canonical_hash = _build_canonical_hash(title, company, city, hit.url)
        return DiscoveryJob(
            canonical_hash=canonical_hash,
            job_id=_job_id_from_hash(canonical_hash),
            title=title,
            company=company or "未知公司",
            city=city or "未知",
            salary=salary or "面议",
            jd_text=description[:4000],
            source=_infer_source(hit.url),
            source_url=hit.url,
            post_time=_normalize_spaces(post_time),
            search_query=hit.query,
            fetched_at=_utc_now(),
            raw_payload={"search_hit": hit.to_dict(), "site_extractor": "nowcoder"},
        )

    def _parse_json_payload(self, payload: str) -> Any:
        cleaned = html.unescape(payload).strip()
        if not cleaned:
            return {}
        try:
            return json.loads(cleaned)
        except Exception:
            cleaned = re.sub(r",\s*}", "}", cleaned)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                return json.loads(cleaned)
            except Exception:
                return {}

    def _iter_json_nodes(self, payload: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item
        elif isinstance(payload, dict):
            graph = payload.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict):
                        yield item
            yield payload

    def _fallback_title(self, raw_title: str) -> str:
        title = _normalize_spaces(raw_title)
        for separator in _SPLIT_SEPARATORS:
            if separator in title:
                parts = [part.strip() for part in title.split(separator) if part.strip()]
                for part in parts:
                    if any(marker in part for marker in ("工程师", "专家", "开发", "算法", "Agent", "LLM", "AI")):
                        return part
        return title

    def _company_from_json(self, item: Dict[str, Any]) -> str:
        organization = item.get("hiringOrganization")
        if isinstance(organization, dict):
            return _normalize_spaces(str(organization.get("name", "")))
        return ""

    def _city_from_json(self, item: Dict[str, Any]) -> str:
        location = item.get("jobLocation")
        if isinstance(location, list):
            for entry in location:
                city = self._city_from_json({"jobLocation": entry})
                if city:
                    return city
        if isinstance(location, dict):
            address = location.get("address")
            if isinstance(address, dict):
                return _normalize_spaces(str(address.get("addressLocality", "") or address.get("addressRegion", "")))
        return ""

    def _salary_from_json(self, item: Dict[str, Any]) -> str:
        salary = item.get("baseSalary")
        if isinstance(salary, dict):
            value = salary.get("value")
            if isinstance(value, dict):
                minimum = value.get("minValue")
                maximum = value.get("maxValue")
                currency = value.get("currency", "")
                if minimum and maximum:
                    return f"{minimum}-{maximum}{currency}".strip()
        return ""

    def _company_from_text(self, *chunks: str) -> str:
        text = " ".join(_normalize_spaces(chunk) for chunk in chunks if chunk)

        def _looks_like_job_title(value: str) -> bool:
            low = (value or "").lower()
            markers = (
                "工程师",
                "开发",
                "算法",
                "专家",
                "实习",
                "agent",
                "llm",
                "rag",
                "backend",
                "frontend",
                "engineer",
                "developer",
                "research",
                "scientist",
                "intern",
            )
            return any(marker in low for marker in markers)

        patterns = [
            r"公司[:：]\s*([^\s|/-]{2,30})",
            r"企业[:：]\s*([^\s|/-]{2,30})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        for separator in _SPLIT_SEPARATORS:
            if separator in text:
                parts = [part.strip() for part in text.split(separator) if part.strip()]
                if len(parts) >= 2:
                    for part in parts:
                        if any(marker in part for marker in ("有限公司", "科技", "智能", "信息", "网络", "Tech", "AI")):
                            if _looks_like_job_title(part):
                                continue
                            return part
                    return parts[1]
        return ""

    def _city_from_text(self, *chunks: str) -> str:
        text = " ".join(_normalize_spaces(chunk) for chunk in chunks if chunk)
        match = re.search(r"(北京|上海|深圳|广州|杭州|成都|苏州|武汉|南京|西安|Remote|远程)", text, re.IGNORECASE)
        if match:
            return match.group(1)
        for city in _CITY_FALLBACKS:
            if city.lower() in text.lower():
                return city
        return ""

    def _salary_from_text(self, *chunks: str) -> str:
        text = " ".join(_normalize_spaces(chunk) for chunk in chunks if chunk)
        match = re.search(r"(\d{1,3}\s*[-~至]\s*\d{1,3}\s*[kK千])", text)
        if match:
            return _normalize_spaces(match.group(1)).replace(" ", "")
        match = re.search(r"(\d{1,3}\s*[-~至]\s*\d{1,3}\s*万/月)", text)
        if match:
            return _normalize_spaces(match.group(1)).replace(" ", "")
        return ""

    def _description_from_html(self, html_text: str, snippet: str) -> str:
        text = _strip_tags(html_text)
        description_patterns = [
            r"(岗位职责[:：].{80,1200})",
            r"(职位描述[:：].{80,1200})",
            r"(Job Description.{80,1200})",
        ]
        for pattern in description_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return _normalize_spaces(match.group(1))
        return _normalize_spaces(" ".join(part for part in [snippet, text[:2000]] if part))

    def _post_time_from_text(self, *chunks: str) -> str:
        text = " ".join(_normalize_spaces(chunk) for chunk in chunks if chunk)
        match = re.search(r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}日?)", text)
        if match:
            return match.group(1)
        match = re.search(r"(今天|昨日|昨天|\d+\s*天前|\d+\s*小时前)", text)
        if match:
            return match.group(1)
        return ""


class JobDiscoveryService:
    def __init__(
        self,
        *,
        search_client: Any | None = None,
        page_fetcher: Any | None = None,
        extractor: JobPageExtractor | None = None,
        store: Any | None = None,
    ):
        self._search_client = search_client or DuckDuckGoSearchClient()
        self._page_fetcher = page_fetcher or RequestsPageFetcher()
        self._extractor = extractor or JobPageExtractor()
        self._store = store

    def discover(
        self,
        profile: Dict[str, Any],
        *,
        cities: Sequence[str] | None = None,
        keywords: Sequence[str] | None = None,
        salary_min_k: int | None = None,
        salary_max_k: int | None = None,
        max_results: int = 20,
        refresh: bool = False,
        progress_callback: Any | None = None,
    ) -> Dict[str, Any]:
        def _emit(stage: str, progress: float, message: str) -> None:
            cb = progress_callback
            if cb is None:
                return
            try:
                if callable(cb):
                    cb(stage, float(progress), str(message))
                    return
                fn = getattr(cb, "on_stage", None)
                if callable(fn):
                    fn(stage, float(progress), str(message))
            except Exception:
                return

        shortlist_limit = max(1, min(int(max_results or 10), 10))
        search_spec = build_search_spec(
            profile,
            cities=cities,
            keywords=keywords,
            salary_min_k=salary_min_k,
            salary_max_k=salary_max_k,
        )
        diagnostics: Dict[str, Any] = {"query_key": search_spec.get("query_key", "")}

        if self._store is not None and not refresh:
            _emit("cache", 0.02, "检查是否有可复用的历史岗位结果")
            cached = self._store.get_latest_discovery_result(search_spec["query_key"])
            if cached is not None:
                diagnostics.update({"mode": "cached", "cached_run_id": cached.get("run_id", "")})
                result = DiscoveryRunResult(
                    status=str(cached.get("status") or "success"),
                    run_id=cached["run_id"],
                    search_spec=cached["search_spec"],
                    candidate_count=cached["candidate_count"],
                    new_jobs_count=0,
                    deduped_count=cached["deduped_count"],
                    sources_used=cached["sources_used"],
                    refresh_mode="cached",
                    shortlist=cached["shortlist"][:shortlist_limit],
                    error=str(cached.get("error") or ""),
                    diagnostics=diagnostics,
                )
                return result.to_dict()

        try:
            fetch_limit = min(config.MAX_FETCH_JOBS, max(shortlist_limit * 2, 8))
            _emit("search", 0.12, "开始搜索公开网页岗位")
            extracted_jobs, discovery_error, live_diag = self._collect_live_jobs(
                search_spec,
                limit=fetch_limit,
                shortlist_limit=shortlist_limit,
                emit=_emit,
            )
            diagnostics.update(live_diag)
            if not extracted_jobs:
                diagnostics["failure"] = self._diagnose_failure(search_spec, diagnostics)
                return self._fallback_result(
                    search_spec,
                    refresh_mode="live",
                    error=discovery_error or "未找到公开岗位结果",
                    diagnostics=diagnostics,
                )

            raw_candidate_count = len(extracted_jobs)
            unique_jobs = self._dedupe_jobs(extracted_jobs)
            if not unique_jobs:
                diagnostics["failure"] = self._diagnose_failure(search_spec, diagnostics)
                return self._fallback_result(
                    search_spec,
                    refresh_mode="live",
                    error="岗位页面解析失败",
                    diagnostics=diagnostics,
                )

            deduped_count = max(raw_candidate_count - len(unique_jobs), 0)
            diagnostics["dedupe"] = {
                "before": raw_candidate_count,
                "after": len(unique_jobs),
                "deduped": deduped_count,
            }

            _emit("rank", 0.72, f"解析成功 {len(unique_jobs)} 个职位，开始计算匹配度")
            ranked_jobs, rank_diag = self._rank_jobs(unique_jobs, profile, search_spec, shortlist_limit=shortlist_limit)
            diagnostics["ranking"] = rank_diag
            shortlist = [job.to_dict() for job in ranked_jobs[:shortlist_limit]]
            run_id = f"discover-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{search_spec['query_key'][:8]}"
            sources_used = sorted({job.source for job in ranked_jobs if job.source})
            new_jobs_count = 0

            if self._store is not None:
                existing = self._store.get_existing_discovered_hashes([job.canonical_hash for job in ranked_jobs])
                new_jobs_count = sum(1 for job in ranked_jobs if job.canonical_hash not in existing)
                self._store.save_discovery_result(
                    run_id=run_id,
                    query_key=search_spec["query_key"],
                    search_spec=search_spec,
                    candidates=[job.to_dict() for job in ranked_jobs],
                    shortlist=shortlist,
                    refresh_mode="live" if refresh else "initial",
                    sources_used=sources_used,
                    candidate_count=len(ranked_jobs),
                    new_jobs_count=new_jobs_count,
                    deduped_count=deduped_count,
                )

            _emit("done", 1.0, f"完成：推荐 {len(shortlist)} 个职位")
            return DiscoveryRunResult(
                status="success",
                run_id=run_id,
                search_spec=search_spec,
                candidate_count=len(ranked_jobs),
                new_jobs_count=new_jobs_count,
                deduped_count=deduped_count,
                sources_used=sources_used,
                refresh_mode="live" if refresh else "initial",
                shortlist=shortlist,
                diagnostics=diagnostics,
            ).to_dict()
        except Exception as exc:
            logger.warning("Live job discovery failed: %s", exc, exc_info=True)
            diagnostics["exception"] = str(exc)
            return self._fallback_result(search_spec, refresh_mode="live", error=str(exc), diagnostics=diagnostics)

    def _collect_live_jobs(
        self,
        search_spec: Dict[str, Any],
        *,
        limit: int,
        shortlist_limit: int,
        emit: Callable[[str, float, str], None] | None = None,
    ) -> tuple[List[DiscoveryJob], str, Dict[str, Any]]:
        queries = list(search_spec.get("queries", []) or [])
        phase1_queries = [q for q in queries if str(q.get("kind") or "balanced") == "balanced"]
        phase2_base_queries = [q for q in queries if str(q.get("kind") or "") == "company"]

        follow_budget: threading.BoundedSemaphore | None = None
        total_follow = max(0, int(getattr(config, "DISCOVERY_FOLLOW_TOTAL", 0) or 0))
        if total_follow > 0:
            follow_budget = threading.BoundedSemaphore(total_follow)
        follow_per_listing = max(0, int(getattr(config, "DISCOVERY_FOLLOW_PER_LISTING", 0) or 0))

        phase1_hits, phase1_search_diag = self._collect_search_hits(phase1_queries, limit=limit, emit=emit)
        if emit is not None and phase1_hits:
            emit("fetch", 0.28, f"找到 {len(phase1_hits)} 个候选页面，开始抓取与解析")
        phase1_jobs, phase1_fetch_diag = self._collect_jobs_from_hits(
            phase1_hits,
            cities=search_spec["cities"],
            salary_min_k=search_spec["salary_min_k"],
            salary_max_k=search_spec["salary_max_k"],
            follow_budget=follow_budget,
            follow_per_listing=follow_per_listing,
        )

        quality_jobs = [
            job
            for job in phase1_jobs
            if not bool((job.raw_payload or {}).get("fallback"))
            and len(job.jd_text or "") >= 300
        ]
        blocked = int(phase1_fetch_diag.get("blocked", 0) or 0)
        attempted = int(phase1_fetch_diag.get("attempted", 0) or 0)
        blocked_ratio = float(blocked / max(attempted, 1))

        phase2_trigger_reasons: List[str] = []
        quality_threshold = max(3, int(shortlist_limit or 0))
        if len(quality_jobs) < quality_threshold:
            phase2_trigger_reasons.append("quality_low")
        if blocked_ratio >= 0.35:
            phase2_trigger_reasons.append("blocked_high")

        phase2_triggered = bool(phase2_base_queries and phase2_trigger_reasons)
        phase2_trigger_reason = "+".join(phase2_trigger_reasons)
        phase2_seed_companies: List[str] = []
        phase2_domain_blacklist: List[str] = []
        phase2_hits: List[SearchHit] = []
        phase2_jobs: List[DiscoveryJob] = []
        phase2_search_diag: Dict[str, Any] = {}
        phase2_fetch_diag: Dict[str, Any] = {}

        if phase2_triggered:
            if emit is not None:
                emit("search", 0.26, "部分页面被拦截/质量不足，切换到公司官网/ATS 搜索")

            blocked_by_domain = phase1_fetch_diag.get("blocked_by_domain", {})
            blocked_domains = {
                domain
                for domain, count in (blocked_by_domain.items() if isinstance(blocked_by_domain, dict) else [])
                if int(count or 0) > 0
            }
            domain_blacklist = set(JOB_BOARD_DOMAINS)
            domain_blacklist.update(blocked_domains)
            phase2_domain_blacklist = sorted(domain_blacklist)

            seen_urls = {hit.url for hit in phase1_hits if hit.url}
            phase2_seed_companies = self._seed_companies_from_hits(phase1_hits, max_companies=4)
            seed_queries = self._build_seed_company_queries(phase2_seed_companies, search_spec["keywords"])
            phase2_queries = [*phase2_base_queries, *seed_queries]

            remaining_limit = max(0, int(limit) - len(phase1_hits))
            phase2_limit = max(6, remaining_limit) if remaining_limit else max(6, min(10, int(limit)))
            phase2_hits, phase2_search_diag = self._collect_search_hits(
                phase2_queries,
                limit=phase2_limit,
                emit=emit,
                domain_blacklist=domain_blacklist,
                seen_urls=seen_urls,
            )
            if emit is not None and phase2_hits:
                emit("fetch", 0.36, f"公司官网候选 {len(phase2_hits)} 个，开始抓取与解析")
            phase2_jobs, phase2_fetch_diag = self._collect_jobs_from_hits(
                phase2_hits,
                cities=search_spec["cities"],
                salary_min_k=search_spec["salary_min_k"],
                salary_max_k=search_spec["salary_max_k"],
                follow_budget=follow_budget,
                follow_per_listing=follow_per_listing,
            )

        all_hits = [*phase1_hits, *phase2_hits]
        all_jobs = [*phase1_jobs, *phase2_jobs]
        diagnostics: Dict[str, Any] = {
            "search": self._merge_search_diags(phase1_search_diag, phase2_search_diag),
            "fetch": self._merge_fetch_diags(phase1_fetch_diag, phase2_fetch_diag),
            "phases": {
                "phase1": {"search": phase1_search_diag, "fetch": phase1_fetch_diag},
                "phase2": {
                    "triggered": bool(phase2_triggered),
                    "reason": phase2_trigger_reason,
                    "seed_companies": phase2_seed_companies,
                    "domain_blacklist": phase2_domain_blacklist,
                    "search": phase2_search_diag,
                    "fetch": phase2_fetch_diag,
                },
            },
            "quality": {
                "phase1_quality_jobs": int(len(quality_jobs)),
                "quality_threshold": int(quality_threshold),
                "phase1_blocked_ratio": round(blocked_ratio, 4),
            },
        }

        if all_jobs:
            return all_jobs, "", diagnostics
        if all_hits:
            return [], "公开网页岗位解析失败", diagnostics
        return [], "未找到公开岗位结果", diagnostics

    def _collect_search_hits(
        self,
        queries: Sequence[Dict[str, Any]],
        *,
        limit: int,
        emit: Callable[[str, float, str], None] | None = None,
        domain_blacklist: set[str] | None = None,
        seen_urls: set[str] | None = None,
    ) -> tuple[List[SearchHit], Dict[str, Any]]:
        results: List[SearchHit] = []
        already_seen: set[str] = set(seen_urls or set())
        domain_counts: Counter[str] = Counter()
        per_query_limit = max(3, min(limit, 8))
        per_domain_cap = max(2, min(4, per_query_limit))

        errors: List[Dict[str, Any]] = []
        skipped_blacklist: Counter[str] = Counter()
        kinds_used: Counter[str] = Counter()
        query_list = list(queries or [])
        raw_hit_count = 0
        variant_count = 0

        for index, query_info in enumerate(query_list):
            kind = str(query_info.get("kind", "") or "")
            if kind:
                kinds_used[kind] += 1
            accepted_for_query = 0
            for query in self._query_variants(query_info):
                variant_count += 1
                if emit is not None and query_list:
                    emit("search", 0.12 + 0.12 * (index / max(len(query_list), 1)), f"搜索：{query}")
                try:
                    hits = self._search_client.search(query, limit=per_query_limit)
                except Exception as exc:
                    logger.warning("Search query failed for %s: %s", query, exc)
                    errors.append({"query": query, "error": str(exc)})
                    continue

                raw_hit_count += len(hits)

                for hit in hits:
                    if hit.url in already_seen or not self._looks_like_job_hit(hit, kind=kind):
                        continue
                    domain = _infer_source(hit.url)
                    if domain_blacklist and _domain_in(domain, domain_blacklist):
                        skipped_blacklist[domain] += 1
                        continue
                    if domain_counts[domain] >= per_domain_cap:
                        continue
                    domain_counts[domain] += 1
                    already_seen.add(hit.url)
                    results.append(hit)
                    accepted_for_query += 1
                    if len(results) >= limit:
                        break
                if accepted_for_query > 0 or len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        diag = {
            "query_count": len(query_list),
            "variant_count": int(variant_count),
            "per_query_limit": per_query_limit,
            "per_domain_cap": per_domain_cap,
            "raw_hit_count": int(raw_hit_count),
            "hit_count": len(results),
            "hits_by_domain": dict(domain_counts),
            "skipped_by_blacklist": dict(skipped_blacklist),
            "kinds_used": dict(kinds_used),
            "errors": errors,
        }
        return results, diag

    def _merge_search_diags(self, *diags: Dict[str, Any]) -> Dict[str, Any]:
        merged_domains: Counter[str] = Counter()
        merged_skipped: Counter[str] = Counter()
        merged_kinds: Counter[str] = Counter()
        errors: List[Dict[str, Any]] = []
        query_count = 0
        variant_count = 0
        per_query_limit = 0
        per_domain_cap = 0
        raw_hit_count = 0
        hit_count = 0

        for diag in diags:
            if not isinstance(diag, dict):
                continue
            query_count += int(diag.get("query_count", 0) or 0)
            variant_count += int(diag.get("variant_count", 0) or 0)
            per_query_limit = max(per_query_limit, int(diag.get("per_query_limit", 0) or 0))
            per_domain_cap = max(per_domain_cap, int(diag.get("per_domain_cap", 0) or 0))
            raw_hit_count += int(diag.get("raw_hit_count", 0) or 0)
            hit_count += int(diag.get("hit_count", 0) or 0)
            merged_domains.update({str(k): int(v or 0) for k, v in (diag.get("hits_by_domain", {}) or {}).items()})
            merged_skipped.update({str(k): int(v or 0) for k, v in (diag.get("skipped_by_blacklist", {}) or {}).items()})
            merged_kinds.update({str(k): int(v or 0) for k, v in (diag.get("kinds_used", {}) or {}).items()})
            errors.extend(list(diag.get("errors", []) or []))

        return {
            "query_count": int(query_count),
            "variant_count": int(variant_count),
            "per_query_limit": int(per_query_limit),
            "per_domain_cap": int(per_domain_cap),
            "raw_hit_count": int(raw_hit_count),
            "hit_count": int(hit_count),
            "hits_by_domain": dict(merged_domains),
            "skipped_by_blacklist": dict(merged_skipped),
            "kinds_used": dict(merged_kinds),
            "errors": errors,
        }

    def _merge_fetch_diags(self, *diags: Dict[str, Any]) -> Dict[str, Any]:
        counters: Counter[str] = Counter()
        blocked_by_domain: Counter[str] = Counter()
        listing_follow: Counter[str] = Counter()
        errors: List[Dict[str, Any]] = []
        max_workers = 0

        for diag in diags:
            if not isinstance(diag, dict):
                continue
            for key in (
                "attempted",
                "extracted",
                "blocked",
                "skipped_domain",
                "fallback_used",
                "filtered_city",
                "filtered_salary",
            ):
                counters[key] += int(diag.get(key, 0) or 0)
            blocked_by_domain.update({str(k): int(v or 0) for k, v in (diag.get("blocked_by_domain", {}) or {}).items()})
            listing_follow.update({str(k): int(v or 0) for k, v in (diag.get("listing_follow", {}) or {}).items()})
            errors.extend(list(diag.get("errors", []) or []))
            max_workers = max(max_workers, int(diag.get("max_workers", 0) or 0))

        return {
            "attempted": int(counters.get("attempted", 0)),
            "extracted": int(counters.get("extracted", 0)),
            "blocked": int(counters.get("blocked", 0)),
            "skipped_domain": int(counters.get("skipped_domain", 0)),
            "fallback_used": int(counters.get("fallback_used", 0)),
            "filtered_city": int(counters.get("filtered_city", 0)),
            "filtered_salary": int(counters.get("filtered_salary", 0)),
            "blocked_by_domain": dict(blocked_by_domain),
            "listing_follow": dict(listing_follow),
            "errors": errors[:10],
            "max_workers": int(max_workers),
        }

    def _seed_companies_from_hits(self, hits: Sequence[SearchHit], *, max_companies: int) -> List[str]:
        counts: Counter[str] = Counter()
        for hit in hits:
            company = _normalize_spaces(self._extractor._company_from_text(hit.title or "", hit.snippet or ""))
            if not company or company in {"未知", "未知公司"}:
                continue
            if len(company) < 2 or len(company) > 30:
                continue
            counts[company] += 1
        return [name for name, _ in counts.most_common(max(0, int(max_companies)))]

    def _build_seed_company_queries(self, companies: Sequence[str], keywords: Sequence[str]) -> List[Dict[str, str]]:
        def _quote_term(value: str) -> str:
            cleaned = _normalize_spaces(value).replace('"', "")
            if not cleaned:
                return ""
            return f'"{cleaned}"'

        def _or_group(values: Sequence[str]) -> str:
            quoted = [_quote_term(val) for val in values if _quote_term(val)]
            if not quoted:
                return ""
            if len(quoted) == 1:
                return quoted[0]
            return f"({' OR '.join(quoted)})"

        keyword_group = _or_group(list(keywords or [])[:2])
        exclusions = _format_site_exclusions(JOB_BOARD_DOMAINS, max_sites=6)

        queries: List[Dict[str, str]] = []
        for company in companies:
            company_term = _quote_term(company)
            tokens = [
                company_term,
                keyword_group,
                '(招聘 OR careers OR jobs OR "加入我们")',
                exclusions,
            ]
            query = " ".join(token for token in tokens if token)
            if not query:
                continue
            queries.append(
                {
                    "query": query,
                    "kind": "seed_company",
                    "company": company,
                    "keywords": list(keywords[:2]),
                }
            )
        return queries

    def _simplify_search_query(self, query: str) -> str:
        simplified = re.sub(r"-site:\S+", " ", query or "", flags=re.IGNORECASE)
        simplified = re.sub(r"\bOR\b", " ", simplified, flags=re.IGNORECASE)
        simplified = simplified.replace("(", " ").replace(")", " ").replace('"', " ")
        simplified = re.sub(r"\s+", " ", simplified)
        return simplified.strip()

    def _query_variants(self, query_info: Dict[str, Any]) -> List[str]:
        base_query = _normalize_spaces(str(query_info.get("query", "") or ""))
        kind = str(query_info.get("kind", "") or "")
        city = _normalize_spaces(str(query_info.get("city", "") or ""))
        company = _normalize_spaces(str(query_info.get("company", "") or ""))
        keywords = [_normalize_spaces(str(item)) for item in (query_info.get("keywords", []) or []) if _normalize_spaces(str(item))]

        variants: List[str] = []
        seen: set[str] = set()

        def _push(candidate: str) -> None:
            normalized = _normalize_spaces(candidate)
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            variants.append(normalized)

        _push(base_query)
        _push(self._simplify_search_query(base_query))

        primary = keywords[0] if keywords else ""

        if kind == "balanced":
            if city and primary:
                _push(f"{city} {primary} 招聘")
                _push(f"{city} {primary} 职位")
                _push(f"{city} {primary}")
            elif primary:
                _push(f"{primary} 招聘")

        if kind == "company":
            if city and primary:
                _push(f"{city} {primary} 官网 招聘")
                _push(f"{city} {primary} 加入我们")
                _push(f"{city} {primary} careers jobs")
            elif primary:
                _push(f"{primary} 官网 招聘")
                _push(f"{primary} 加入我们")

        if kind == "seed_company":
            if company and primary:
                _push(f"{company} {primary} 招聘")
                _push(f"{company} {primary} 加入我们")
            if company:
                _push(f"{company} careers")
                _push(f"{company} jobs")

        return variants

    def _collect_jobs_from_hits(
        self,
        hits: Sequence[SearchHit],
        *,
        cities: Sequence[str],
        salary_min_k: int,
        salary_max_k: int,
        follow_budget: threading.BoundedSemaphore | None = None,
        follow_per_listing: int = 0,
    ) -> tuple[List[DiscoveryJob], Dict[str, Any]]:
        hits_to_fetch = list(hits[: int(config.MAX_FETCH_JOBS)])
        max_workers = max(2, min(8, len(hits_to_fetch))) if hits_to_fetch else 0
        follow_per_listing = max(0, int(follow_per_listing or 0))

        counters: Counter[str] = Counter()
        blocked_by_domain: Counter[str] = Counter()
        follow_counters: Counter[str] = Counter()
        errors: List[Dict[str, Any]] = []
        jobs: List[DiscoveryJob] = []

        runtime_blocklist: set[str] = set()
        runtime_lock = threading.Lock()
        blocked_seen: Counter[str] = Counter()

        def _is_runtime_blocked(domain: str) -> bool:
            with runtime_lock:
                return domain in runtime_blocklist

        def _record_blocked(domain: str) -> None:
            with runtime_lock:
                blocked_seen[domain] += 1
                if blocked_seen[domain] >= 2:
                    runtime_blocklist.add(domain)

        listing_title_markers = (
            "加入我们",
            "人才招聘",
            "社会招聘",
            "校园招聘",
            "职位列表",
            "在招",
            "open positions",
            "careers",
            "jobs",
        )
        job_text_markers = (
            "工程师",
            "开发",
            "算法",
            "研究",
            "产品",
            "设计",
            "engineer",
            "developer",
            "research",
            "data",
            "ai",
            "llm",
            "agent",
        )
        url_job_markers = re.compile(
            r"(job|jobs|career|careers|position|recruit|join|talent|jobid|positionid)",
            re.IGNORECASE,
        )

        def _page_title(html_text: str) -> str:
            title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text or "")
            return _strip_tags(title_match.group(1)) if title_match else ""

        def _extract_same_domain_job_links(html_text: str, base_url: str) -> List[tuple[str, str]]:
            base_netloc = urlparse(base_url).netloc.lower()
            if not base_netloc:
                return []

            results: List[tuple[str, str]] = []
            seen: set[str] = set()
            anchor_pattern = re.compile(
                r'(?is)<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<text>.*?)</a>'
            )
            for match in anchor_pattern.finditer(html_text or ""):
                href = html.unescape(match.group("href")).strip()
                if not href or href.startswith(("#", "javascript:", "mailto:")):
                    continue

                abs_url = urljoin(base_url, href)
                parsed = urlparse(abs_url)
                if parsed.scheme not in {"http", "https"}:
                    continue
                if parsed.netloc.lower() != base_netloc:
                    continue

                normalized_url = _normalize_url(abs_url)
                if normalized_url in seen:
                    continue

                link_text = _strip_tags(match.group("text") or "")
                haystack = f"{parsed.path}?{parsed.query}".lower()
                if any(token in haystack for token in ("privacy", "terms", "cookie", "login", "signup")):
                    continue

                text_low = link_text.lower()
                if not (url_job_markers.search(haystack) or any(marker in text_low for marker in job_text_markers)):
                    continue

                seen.add(normalized_url)
                results.append((abs_url, link_text))
                if len(results) >= 50:
                    break
            return results

        def _follow_listing_links(hit: SearchHit, links: Sequence[tuple[str, str]], *, city_hint: str) -> tuple[List[DiscoveryJob], Dict[str, int]]:
            diag = {
                "listing_detected": 1,
                "listing_followed": 0,
                "link_candidates": int(len(links)),
                "link_attempted": 0,
                "link_extracted": 0,
                "link_blocked": 0,
                "link_error": 0,
            }
            if not links or follow_per_listing <= 0 or follow_budget is None:
                return [], diag

            selected = list(links)[: min(len(links), follow_per_listing)]
            extracted: List[DiscoveryJob] = []
            for link_url, link_text in selected:
                if not follow_budget.acquire(blocking=False):
                    break
                diag["link_attempted"] += 1
                child_hit = SearchHit(
                    query=hit.query,
                    url=link_url,
                    title=link_text or hit.title,
                    snippet=hit.snippet,
                )
                try:
                    child_html = self._page_fetcher.fetch(link_url)
                except Exception:
                    diag["link_error"] += 1
                    continue

                child_blocked = self._extractor.blocked_reason(child_hit, child_html)
                if child_blocked:
                    diag["link_blocked"] += 1
                    continue

                try:
                    child_job = self._extractor.extract(child_hit, child_html, fallback_city=city_hint)
                except Exception:
                    diag["link_error"] += 1
                    continue

                if child_job is None:
                    continue

                payload = dict(child_job.raw_payload or {})
                payload["followed_from"] = hit.url
                child_job = replace(child_job, raw_payload=payload)
                extracted.append(child_job)
                diag["link_extracted"] += 1

            if extracted:
                diag["listing_followed"] = 1
            return extracted, diag

        def _process_hit(hit: SearchHit) -> Dict[str, Any]:
            domain = _infer_source(hit.url)
            city_hint = next((city for city in cities if city and city in hit.query), "")
            follow_diag = {
                "listing_detected": 0,
                "listing_followed": 0,
                "link_candidates": 0,
                "link_attempted": 0,
                "link_extracted": 0,
                "link_blocked": 0,
                "link_error": 0,
            }

            if _is_runtime_blocked(domain):
                return {
                    "status": "skipped_domain",
                    "domain": domain,
                    "url": hit.url,
                    "jobs": [],
                    "follow_diag": follow_diag,
                }

            try:
                html_text = self._page_fetcher.fetch(hit.url)
            except Exception as exc:
                job = self._fallback_job_from_hit(hit, fallback_city=city_hint)
                return {
                    "status": "fetch_error",
                    "domain": domain,
                    "url": hit.url,
                    "error": str(exc),
                    "jobs": [job] if job is not None else [],
                    "follow_diag": follow_diag,
                }

            blocked_reason = self._extractor.blocked_reason(hit, html_text)
            if blocked_reason:
                _record_blocked(domain)
                return {
                    "status": "blocked",
                    "domain": domain,
                    "url": hit.url,
                    "blocked_reason": blocked_reason,
                    "follow_diag": follow_diag,
                }

            try:
                job = self._extractor.extract(hit, html_text, fallback_city=city_hint)
            except Exception as exc:
                return {
                    "status": "parse_error",
                    "domain": domain,
                    "url": hit.url,
                    "error": str(exc),
                    "jobs": [
                        fallback
                        for fallback in [self._fallback_job_from_hit(hit, fallback_city=city_hint)]
                        if fallback is not None
                    ],
                    "follow_diag": follow_diag,
                }

            if not _domain_in(domain, JOB_BOARD_DOMAINS) and follow_per_listing > 0 and follow_budget is not None:
                jd_len = len(job.jd_text or "") if job is not None else 0
                if job is None or jd_len < 200:
                    page_title = _page_title(html_text)
                    title_low = page_title.lower()
                    links = _extract_same_domain_job_links(html_text, hit.url)
                    looks_listing = any(marker.lower() in title_low for marker in listing_title_markers)
                    if len(links) >= 3 and (looks_listing or job is None):
                        follow_jobs, listing_diag = _follow_listing_links(hit, links, city_hint=city_hint)
                        follow_diag = listing_diag
                        if follow_jobs:
                            return {
                                "status": "ok",
                                "domain": domain,
                                "url": hit.url,
                                "jobs": follow_jobs,
                                "follow_diag": follow_diag,
                            }

            if job is None:
                job = self._fallback_job_from_hit(hit, fallback_city=city_hint)
                return {
                    "status": "extraction_failed",
                    "domain": domain,
                    "url": hit.url,
                    "jobs": [job] if job is not None else [],
                    "follow_diag": follow_diag,
                }

            return {"status": "ok", "domain": domain, "url": hit.url, "jobs": [job], "follow_diag": follow_diag}

        if not hits_to_fetch:
            return (
                [],
                {
                    "attempted": 0,
                    "extracted": 0,
                    "blocked": 0,
                    "skipped_domain": 0,
                    "fallback_used": 0,
                    "filtered_city": 0,
                    "filtered_salary": 0,
                    "blocked_by_domain": {},
                    "listing_follow": {},
                    "errors": [],
                    "max_workers": 0,
                },
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_process_hit, hit) for hit in hits_to_fetch]
            for future in as_completed(futures):
                record = future.result()
                status = str(record.get("status", ""))
                domain = str(record.get("domain", "unknown") or "unknown")
                counters["attempted"] += 1

                follow_diag = record.get("follow_diag", {})
                if isinstance(follow_diag, dict):
                    follow_counters.update({str(k): int(v or 0) for k, v in follow_diag.items()})

                if status == "skipped_domain":
                    counters["skipped_domain"] += 1
                    continue

                if status == "blocked":
                    counters["blocked"] += 1
                    blocked_by_domain[domain] += 1
                    continue

                if status.endswith("error"):
                    counters["errors"] += 1
                    errors.append(
                        {
                            "status": status,
                            "domain": domain,
                            "url": record.get("url", ""),
                            "error": record.get("error", ""),
                        }
                    )

                record_jobs = record.get("jobs") or []
                if not isinstance(record_jobs, list):
                    continue

                if status in {"fetch_error", "parse_error", "extraction_failed"}:
                    counters["fallback_used"] += 1

                for job in record_jobs:
                    if job is None:
                        continue

                    if cities and job.city not in {"未知", ""} and job.city not in cities:
                        counters["filtered_city"] += 1
                        continue

                    if not _salary_overlap(job.salary, salary_min_k, salary_max_k):
                        counters["filtered_salary"] += 1
                        continue

                    counters["extracted"] += 1
                    jobs.append(job)

        diag = {
            "attempted": int(counters.get("attempted", 0)),
            "extracted": int(counters.get("extracted", 0)),
            "blocked": int(counters.get("blocked", 0)),
            "skipped_domain": int(counters.get("skipped_domain", 0)),
            "fallback_used": int(counters.get("fallback_used", 0)),
            "filtered_city": int(counters.get("filtered_city", 0)),
            "filtered_salary": int(counters.get("filtered_salary", 0)),
            "blocked_by_domain": dict(blocked_by_domain),
            "listing_follow": dict(follow_counters),
            "errors": errors[:10],
            "max_workers": int(max_workers),
        }
        return jobs, diag

    def _dedupe_jobs(self, jobs: Sequence[DiscoveryJob]) -> List[DiscoveryJob]:
        deduped: Dict[str, DiscoveryJob] = {}
        for job in jobs:
            key = _build_identity_key(job.title, job.company, job.city)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = job
                continue
            if _job_quality_score(job) > _job_quality_score(existing):
                deduped[key] = job
        return list(deduped.values())

    def _rank_jobs(
        self,
        jobs: Sequence[DiscoveryJob],
        profile: Dict[str, Any],
        search_spec: Dict[str, Any],
        *,
        shortlist_limit: int,
    ) -> tuple[List[DiscoveryJob], Dict[str, Any]]:
        llm_enabled = has_llm_configured()

        quick_scored: List[tuple[DiscoveryJob, float]] = []
        for job in jobs:
            quick_scored.append((job, self._quick_score(job, profile, search_spec)))
        quick_scored.sort(key=lambda item: (item[1], len(item[0].jd_text)), reverse=True)

        coarse_limit = min(len(quick_scored), max(shortlist_limit, int(config.MAX_COARSE_FILTER)))
        selected = quick_scored[:coarse_limit]

        deep_budget = len(selected)
        if llm_enabled:
            deep_budget = max(0, min(int(config.MAX_DEEP_ANALYSIS), len(selected)))

        ranked: List[DiscoveryJob] = []
        quick_score_by_hash: Dict[str, float] = {job.canonical_hash: score for job, score in selected}
        deep_done = 0

        for index, (job, quick_score) in enumerate(selected):
            if index < deep_budget:
                analysis = analyze_jd(job.jd_text)
                match = match_job_enhanced(profile, analysis)
                keyword_bonus = self._keyword_bonus(job, search_spec["keywords"])
                freshness_bonus = (
                    5.0
                    if job.post_time
                    and any(token in job.post_time for token in ("今天", "小时", "1天", "2天", str(datetime.now().year)))
                    else 0.0
                )
                completeness_bonus = min(len(job.jd_text) / 400.0, 8.0)
                match_score = float(match.get("score", 0) or 0.0)
                ranking_score = round(min(match_score + keyword_bonus + freshness_bonus + completeness_bonus, 100.0), 2)
                recommendation_reason = self._build_recommendation_reason(job, analysis, match)
                ranked.append(
                    replace(
                        job,
                        ranking_score=ranking_score,
                        match_score=match_score,
                        recommendation_reason=recommendation_reason,
                        analysis=analysis,
                        match=match,
                    )
                )
                deep_done += 1
                continue

            quick_match = self._quick_match(job, profile, search_spec)
            ranked.append(
                replace(
                    job,
                    ranking_score=round(min(float(quick_score), 100.0), 2),
                    match_score=float(quick_match.get("score", 0) or 0.0),
                    recommendation_reason=str(quick_match.get("reason", "")),
                    analysis={"summary": "快速评估（未做深度分析）"},
                    match={
                        "score": int(quick_match.get("score", 0) or 0),
                        "matched_skills": list(quick_match.get("matched_skills", []) or []),
                        "skill_gaps": list(quick_match.get("skill_gaps", []) or []),
                        "_approx": True,
                    },
                )
            )

        ranked.sort(
            key=lambda item: (
                item.ranking_score,
                item.match_score,
                quick_score_by_hash.get(item.canonical_hash, 0.0),
                len(item.jd_text),
            ),
            reverse=True,
        )
        diag = {
            "llm_enabled": bool(llm_enabled),
            "input_jobs": len(jobs),
            "coarse_limit": int(coarse_limit),
            "deep_budget": int(deep_budget),
            "deep_analyzed": int(deep_done),
        }
        return ranked, diag

    def _quick_score(self, job: DiscoveryJob, profile: Dict[str, Any], search_spec: Dict[str, Any]) -> float:
        haystack = f"{job.title} {job.jd_text}".lower()
        score = 0.0

        keywords = list(search_spec.get("keywords", []) or [])[:6]
        score += 6.0 * sum(1 for kw in keywords if str(kw).lower() in haystack)

        user_skills = list((profile.get("skills", {}) or {}).keys())
        matched_skills = [skill for skill in user_skills if str(skill).lower() in haystack]
        score += min(len(matched_skills) * 12.0, 60.0)

        cities = set(str(city) for city in (search_spec.get("cities", []) or []) if str(city).strip())
        if cities and job.city in cities:
            score += 10.0

        if job.salary and job.salary not in {"面议", ""}:
            score += 5.0

        if job.post_time and any(token in job.post_time for token in ("今天", "小时", "1天", "2天")):
            score += 3.0

        score += min(len(job.jd_text) / 300.0, 10.0)
        if bool((job.raw_payload or {}).get("fallback")):
            score = min(score * 0.4, 55.0)
        return float(min(score, 100.0))

    def _quick_match(self, job: DiscoveryJob, profile: Dict[str, Any], search_spec: Dict[str, Any]) -> Dict[str, Any]:
        haystack = f"{job.title} {job.jd_text}".lower()
        user_skills = list((profile.get("skills", {}) or {}).keys())
        matched = [skill for skill in user_skills if str(skill).lower() in haystack]
        score = self._quick_score(job, profile, search_spec)
        reason = f"快速匹配技能：{', '.join(matched[:4])}" if matched else "快速匹配：未命中明显技能关键词"
        return {"score": int(round(score)), "matched_skills": matched[:6], "skill_gaps": [], "reason": reason}

    def _keyword_bonus(self, job: DiscoveryJob, keywords: Sequence[str]) -> float:
        haystack = f"{job.title} {job.jd_text}".lower()
        matched = sum(1 for keyword in keywords[:4] if keyword.lower() in haystack)
        return matched * 4.0

    def _build_recommendation_reason(self, job: DiscoveryJob, analysis: Dict[str, Any], match: Dict[str, Any]) -> str:
        matched_skills = list(match.get("matched_skills", [])[:3])
        skill_gaps = list(match.get("skill_gaps", [])[:3])
        reasons = []
        if matched_skills:
            reasons.append(f"匹配技能：{', '.join(matched_skills)}")
        if analysis.get("summary"):
            reasons.append(str(analysis["summary"]))
        if skill_gaps:
            reasons.append(f"主要缺口：{', '.join(skill_gaps)}")
        return "；".join(reasons) or "岗位与当前画像相关，建议进入进一步分析"

    def _looks_like_job_hit(self, hit: SearchHit, *, kind: str = "") -> bool:
        haystack = f"{hit.title} {hit.snippet} {hit.url}".lower()
        if any(marker.lower() in haystack for marker in _JOB_HINTS):
            return True

        domain = _infer_source(hit.url)
        parsed = urlparse(hit.url)
        path_haystack = f"{parsed.path} {parsed.query}".lower()
        path_markers = (
            "career",
            "careers",
            "job",
            "jobs",
            "position",
            "positions",
            "recruit",
            "join-us",
            "join_us",
            "talent",
            "opening",
            "open-position",
            "workday",
            "apply",
        )
        title_markers = ("加入我们", "人才招聘", "社会招聘", "校园招聘", "在招", "open positions")

        if _domain_in(domain, ATS_DOMAINS):
            return True
        if any(marker in path_haystack for marker in path_markers):
            return True
        if any(marker.lower() in haystack for marker in title_markers):
            return True
        if kind in {"company", "seed_company"} and not _domain_in(domain, JOB_BOARD_DOMAINS):
            return any(marker in path_haystack for marker in ("career", "job", "join", "recruit"))
        return False

    def _fallback_job_from_hit(self, hit: SearchHit, *, fallback_city: str = "") -> DiscoveryJob | None:
        title = self._extractor._fallback_title(hit.title)
        if not title:
            return None
        company = self._extractor._company_from_text(hit.title, hit.snippet) or "未知公司"
        city = fallback_city or self._extractor._city_from_text(hit.title, hit.snippet) or "未知"
        salary = self._extractor._salary_from_text(hit.title, hit.snippet) or "面议"
        jd_text = _normalize_spaces(" ".join(part for part in [hit.title, hit.snippet] if part))
        canonical_hash = _build_canonical_hash(title, company, city, hit.url)
        return DiscoveryJob(
            canonical_hash=canonical_hash,
            job_id=_job_id_from_hash(canonical_hash),
            title=title,
            company=company,
            city=city,
            salary=salary,
            jd_text=jd_text[:2000],
            source=_infer_source(hit.url),
            source_url=hit.url,
            post_time=self._extractor._post_time_from_text(hit.snippet),
            search_query=hit.query,
            fetched_at=_utc_now(),
            raw_payload={"search_hit": hit.to_dict(), "fallback": True},
        )

    def _diagnose_failure(self, search_spec: Dict[str, Any], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        search_diag = diagnostics.get("search", {}) if isinstance(diagnostics.get("search"), dict) else {}
        fetch_diag = diagnostics.get("fetch", {}) if isinstance(diagnostics.get("fetch"), dict) else {}

        hit_count = int(search_diag.get("hit_count", 0) or 0)
        extracted = int(fetch_diag.get("extracted", 0) or 0)
        blocked = int(fetch_diag.get("blocked", 0) or 0)

        if hit_count <= 0:
            return {
                "reason": "搜索无结果",
                "suggestions": [
                    "尝试更通用的关键词（例如把“AI Agent”换成“Python 后端/LLM 应用开发”）",
                    "扩大城市范围或允许远程",
                    "检查网络/代理是否影响搜索请求",
                ],
            }

        if extracted <= 0 and blocked > 0:
            return {
                "reason": "页面被反爬/登录拦截",
                "blocked_by_domain": fetch_diag.get("blocked_by_domain", {}),
                "suggestions": [
                    "优先使用未强登录的网站来源（搜索结果里跳过需要登录的网站）",
                    "降低抓取频率或更换网络出口（必要时使用代理）",
                    "如果某站点长期拦截，后续可增加该站点的专用解析或直接换数据源",
                ],
            }

        if extracted <= 0:
            return {
                "reason": "页面解析失败",
                "suggestions": [
                    "搜索结果可能不是标准招聘页（含聚合页/列表页/跳转页），可增加关键词如“职位描述/岗位职责”",
                    "对高频域名增加站点专用解析器（zhaopin/nowcoder 等）",
                    "必要时开启 LLM 辅助抽取（成本更高）",
                ],
            }

        return {"reason": "未知原因", "suggestions": ["查看 diagnostics.search / diagnostics.fetch 获取更多细节。"]}

    def _fallback_result(
        self,
        search_spec: Dict[str, Any],
        *,
        refresh_mode: str,
        error: str,
        diagnostics: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return DiscoveryRunResult(
            status="fallback_required",
            run_id="",
            search_spec=search_spec,
            candidate_count=0,
            new_jobs_count=0,
            deduped_count=0,
            sources_used=[],
            refresh_mode=refresh_mode,
            shortlist=[],
            error=error,
            diagnostics=diagnostics or {},
        ).to_dict()


def _get_proxies() -> Dict[str, str]:
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or getattr(config, "HTTP_PROXY", "")
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}
