from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SQLiteJobStoreConfig:
    db_path: Path


class SQLiteJobStore:
    """
    SQLite persistence for job records + enrichments.

    Stores:
    - raw job (title/company/city/salary/jd_text)
    - analysis_json / match_json / repos_json / suggestions_json
    - discovery runs / discovered jobs / rankings
    """

    def __init__(self, config: SQLiteJobStoreConfig):
        self._path = Path(config.db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._path

    def _init_db(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_records (
                    job_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    city TEXT DEFAULT '',
                    salary TEXT DEFAULT '',
                    jd_text TEXT NOT NULL,
                    analysis_json TEXT,
                    match_json TEXT,
                    repos_json TEXT,
                    suggestions_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    run_id TEXT PRIMARY KEY,
                    query_key TEXT NOT NULL,
                    search_spec_json TEXT NOT NULL,
                    refresh_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL,
                    new_jobs_count INTEGER NOT NULL,
                    deduped_count INTEGER NOT NULL,
                    sources_json TEXT NOT NULL,
                    shortlist_json TEXT NOT NULL,
                    error TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovered_jobs (
                    canonical_hash TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    city TEXT DEFAULT '',
                    salary TEXT DEFAULT '',
                    jd_text TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    source_url TEXT NOT NULL,
                    post_time TEXT DEFAULT '',
                    search_query TEXT DEFAULT '',
                    fetched_at TEXT NOT NULL,
                    raw_payload_json TEXT DEFAULT '{}',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_rankings (
                    run_id TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    rank_index INTEGER NOT NULL,
                    ranking_score REAL NOT NULL,
                    match_score REAL NOT NULL,
                    analysis_json TEXT NOT NULL,
                    match_json TEXT NOT NULL,
                    recommendation_reason TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, canonical_hash)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_discovery_runs_query_key ON discovery_runs(query_key, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_discovered_jobs_last_seen ON discovered_jobs(last_seen_at DESC)"
            )

    def save_raw_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        if not jobs:
            return
        now = _utc_now()
        with sqlite3.connect(self._path) as conn:
            for job in jobs:
                conn.execute(
                    """
                    INSERT INTO job_records
                    (job_id, title, company, city, salary, jd_text, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                      title=excluded.title,
                      company=excluded.company,
                      city=excluded.city,
                      salary=excluded.salary,
                      jd_text=excluded.jd_text,
                      updated_at=excluded.updated_at
                    """,
                    (
                        job["job_id"],
                        job.get("title", ""),
                        job.get("company", ""),
                        job.get("city", ""),
                        job.get("salary", ""),
                        job.get("jd_text", ""),
                        now,
                        now,
                    ),
                )

    def save_snapshot(
        self,
        *,
        job_id: str,
        job: Dict[str, Any],
        analysis: Dict[str, Any] | None,
        match: Dict[str, Any] | None,
        repos: List[Dict[str, Any]] | None,
        suggestions: List[Dict[str, Any]] | None,
    ) -> None:
        self.save_raw_jobs([job])
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                UPDATE job_records
                SET analysis_json=?,
                    match_json=?,
                    repos_json=?,
                    suggestions_json=?,
                    updated_at=?
                WHERE job_id=?
                """,
                (
                    json.dumps(analysis or {}, ensure_ascii=False),
                    json.dumps(match or {}, ensure_ascii=False),
                    json.dumps(repos or [], ensure_ascii=False),
                    json.dumps(suggestions or [], ensure_ascii=False),
                    _utc_now(),
                    job_id,
                ),
            )

    def list_recent_enriched(self, limit: int = 20) -> List[Dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT job_id, title, company, city, salary, jd_text,
                       analysis_json, match_json, repos_json, suggestions_json, updated_at
                FROM job_records
                WHERE match_json IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result: List[Dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["analysis"] = json.loads(record.pop("analysis_json") or "{}")
            record["match"] = json.loads(record.pop("match_json") or "{}")
            record["repos"] = json.loads(record.pop("repos_json") or "[]")
            record["suggestions"] = json.loads(record.pop("suggestions_json") or "[]")
            result.append(record)
        return result

    def get_existing_discovered_hashes(self, hashes: List[str]) -> set[str]:
        unique_hashes = [value for value in dict.fromkeys(hashes) if value]
        if not unique_hashes:
            return set()
        placeholders = ",".join("?" for _ in unique_hashes)
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                f"SELECT canonical_hash FROM discovered_jobs WHERE canonical_hash IN ({placeholders})",
                tuple(unique_hashes),
            ).fetchall()
        return {row[0] for row in rows}

    def save_discovery_result(
        self,
        *,
        run_id: str,
        query_key: str,
        search_spec: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        shortlist: List[Dict[str, Any]],
        refresh_mode: str,
        sources_used: List[str],
        candidate_count: int,
        new_jobs_count: int,
        deduped_count: int,
        status: str = "success",
        error: str = "",
    ) -> None:
        now = _utc_now()
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                INSERT INTO discovery_runs
                (run_id, query_key, search_spec_json, refresh_mode, status, candidate_count,
                 new_jobs_count, deduped_count, sources_json, shortlist_json, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  query_key=excluded.query_key,
                  search_spec_json=excluded.search_spec_json,
                  refresh_mode=excluded.refresh_mode,
                  status=excluded.status,
                  candidate_count=excluded.candidate_count,
                  new_jobs_count=excluded.new_jobs_count,
                  deduped_count=excluded.deduped_count,
                  sources_json=excluded.sources_json,
                  shortlist_json=excluded.shortlist_json,
                  error=excluded.error
                """,
                (
                    run_id,
                    query_key,
                    json.dumps(search_spec, ensure_ascii=False),
                    refresh_mode,
                    status,
                    candidate_count,
                    new_jobs_count,
                    deduped_count,
                    json.dumps(sources_used, ensure_ascii=False),
                    json.dumps(shortlist, ensure_ascii=False),
                    error,
                    now,
                ),
            )

            for candidate in candidates:
                conn.execute(
                    """
                    INSERT INTO discovered_jobs
                    (canonical_hash, job_id, title, company, city, salary, jd_text, source, source_url,
                     post_time, search_query, fetched_at, raw_payload_json, first_seen_at, last_seen_at, seen_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(canonical_hash) DO UPDATE SET
                      job_id=excluded.job_id,
                      title=excluded.title,
                      company=excluded.company,
                      city=excluded.city,
                      salary=excluded.salary,
                      jd_text=excluded.jd_text,
                      source=excluded.source,
                      source_url=excluded.source_url,
                      post_time=excluded.post_time,
                      search_query=excluded.search_query,
                      fetched_at=excluded.fetched_at,
                      raw_payload_json=excluded.raw_payload_json,
                      last_seen_at=excluded.last_seen_at,
                      seen_count=discovered_jobs.seen_count + 1
                    """,
                    (
                        candidate.get("canonical_hash", ""),
                        candidate.get("job_id", ""),
                        candidate.get("title", ""),
                        candidate.get("company", ""),
                        candidate.get("city", ""),
                        candidate.get("salary", ""),
                        candidate.get("jd_text", ""),
                        candidate.get("source", ""),
                        candidate.get("source_url", ""),
                        candidate.get("post_time", ""),
                        candidate.get("search_query", ""),
                        candidate.get("fetched_at", now),
                        json.dumps(candidate.get("raw_payload", {}), ensure_ascii=False),
                        now,
                        now,
                    ),
                )

            for rank_index, job in enumerate(shortlist, start=1):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO job_rankings
                    (run_id, canonical_hash, job_id, rank_index, ranking_score, match_score,
                     analysis_json, match_json, recommendation_reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        job.get("canonical_hash", ""),
                        job.get("job_id", ""),
                        rank_index,
                        float(job.get("ranking_score", 0.0) or 0.0),
                        float(job.get("match_score", 0.0) or 0.0),
                        json.dumps(job.get("analysis", {}), ensure_ascii=False),
                        json.dumps(job.get("match", {}), ensure_ascii=False),
                        job.get("recommendation_reason", ""),
                        now,
                    ),
                )

        shortlist_jobs = [
            {
                "job_id": job.get("job_id", ""),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "city": job.get("city", ""),
                "salary": job.get("salary", ""),
                "jd_text": job.get("jd_text", ""),
            }
            for job in shortlist
        ]
        self.save_raw_jobs(shortlist_jobs)
        for job in shortlist:
            self.save_snapshot(
                job_id=job.get("job_id", ""),
                job={
                    "job_id": job.get("job_id", ""),
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "city": job.get("city", ""),
                    "salary": job.get("salary", ""),
                    "jd_text": job.get("jd_text", ""),
                },
                analysis=job.get("analysis", {}),
                match=job.get("match", {}),
                repos=None,
                suggestions=None,
            )

    def get_latest_discovery_result(self, query_key: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT run_id, search_spec_json, candidate_count, new_jobs_count, deduped_count,
                       sources_json, shortlist_json, refresh_mode, status, error, created_at
                FROM discovery_runs
                WHERE query_key=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (query_key,),
            ).fetchone()

        if row is None:
            return None
        record = dict(row)
        return {
            "run_id": record["run_id"],
            "search_spec": json.loads(record["search_spec_json"] or "{}"),
            "candidate_count": int(record["candidate_count"] or 0),
            "new_jobs_count": int(record["new_jobs_count"] or 0),
            "deduped_count": int(record["deduped_count"] or 0),
            "sources_used": json.loads(record["sources_json"] or "[]"),
            "shortlist": json.loads(record["shortlist_json"] or "[]"),
            "refresh_mode": record["refresh_mode"],
            "status": record["status"],
            "error": record["error"] or "",
            "created_at": record["created_at"],
        }
