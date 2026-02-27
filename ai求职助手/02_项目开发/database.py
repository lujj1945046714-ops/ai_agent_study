import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
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


def save_raw_jobs(db_path: str, jobs: List[Dict[str, Any]]) -> None:
    if not jobs:
        return
    now = _utc_now()
    with sqlite3.connect(db_path) as conn:
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
                    job["title"],
                    job["company"],
                    job.get("city", ""),
                    job.get("salary", ""),
                    job["jd_text"],
                    now,
                    now,
                ),
            )


def list_unanalyzed_jobs(db_path: str, limit: int) -> List[Dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT job_id, title, company, city, salary, jd_text
            FROM job_records
            WHERE analysis_json IS NULL
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_enrichment(
    db_path: str,
    job_id: str,
    analysis: Dict[str, Any],
    match: Dict[str, Any],
    repos: List[Dict[str, Any]],
    suggestions: List[Dict[str, Any]],
) -> None:
    with sqlite3.connect(db_path) as conn:
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
                json.dumps(analysis, ensure_ascii=False),
                json.dumps(match, ensure_ascii=False),
                json.dumps(repos, ensure_ascii=False),
                json.dumps(suggestions, ensure_ascii=False),
                _utc_now(),
                job_id,
            ),
        )


def list_enriched_jobs(db_path: str, limit: int) -> List[Dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
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
        record["analysis"] = json.loads(record.pop("analysis_json"))
        record["match"] = json.loads(record.pop("match_json"))
        record["repos"] = json.loads(record.pop("repos_json"))
        record["suggestions"] = json.loads(record.pop("suggestions_json"))
        result.append(record)
    return result
