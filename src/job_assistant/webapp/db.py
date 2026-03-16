from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class WebAppStore:
    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS web_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS chat_threads (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(thread_id) REFERENCES chat_threads(id)
                );

                CREATE TABLE IF NOT EXISTS user_search_runs (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    thread_id TEXT DEFAULT '',
                    title TEXT NOT NULL,
                    query_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS user_search_results (
                    search_run_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    rank_index INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (search_run_id, job_id),
                    FOREIGN KEY(search_run_id) REFERENCES user_search_runs(id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS user_job_snapshots (
                    user_id INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    thread_id TEXT DEFAULT '',
                    search_run_id TEXT DEFAULT '',
                    job_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL DEFAULT '{}',
                    match_json TEXT NOT NULL DEFAULT '{}',
                    repos_json TEXT NOT NULL DEFAULT '[]',
                    suggestions_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, job_id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS user_learning_plans (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    formatted_plan TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS user_artifacts (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS user_repo_audits (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    repo_url TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    artifact_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS user_github_searches (
                    search_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    user_query TEXT NOT NULL,
                    keywords TEXT,
                    min_stars INTEGER,
                    top_n INTEGER,
                    include_audit INTEGER DEFAULT 0,
                    include_similar INTEGER DEFAULT 1,
                    status TEXT,
                    repos TEXT,
                    replan_options TEXT,
                    retry_context TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON web_sessions(user_id, expires_at);
                CREATE INDEX IF NOT EXISTS idx_threads_user_updated ON chat_threads(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON chat_messages(thread_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_search_runs_user_created ON user_search_runs(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_job_snapshots_user_updated ON user_job_snapshots(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_learning_plans_user_created ON user_learning_plans(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_artifacts_user_created ON user_artifacts(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_repo_audits_user_created ON user_repo_audits(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_github_searches_user_created ON user_github_searches(user_id, created_at DESC);
                """
            )

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"] if row else 0)

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_meta(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def create_user(self, username: str, password_hash: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users(username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (username, password_hash, now),
            )
            user_id = int(cur.lastrowid)
        return {"id": user_id, "username": username, "created_at": now}

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username=?",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_session(self, user_id: int, *, ttl_days: int = 30) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        session_id = uuid.uuid4().hex
        created_at = now.isoformat(timespec="seconds")
        expires_at = (now + timedelta(days=ttl_days)).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO web_sessions(session_id, user_id, created_at, expires_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, user_id, created_at, expires_at, created_at),
            )
        return {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": created_at,
            "expires_at": expires_at,
        }

    def get_user_by_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.username, u.created_at, s.expires_at
                FROM web_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.session_id=?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            if str(row["expires_at"]) <= _utc_now():
                conn.execute("DELETE FROM web_sessions WHERE session_id=?", (session_id,))
                return None
            conn.execute(
                "UPDATE web_sessions SET last_seen_at=? WHERE session_id=?",
                (_utc_now(), session_id),
            )
        return {"id": row["id"], "username": row["username"], "created_at": row["created_at"]}

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM web_sessions WHERE session_id=?", (session_id,))

    def upsert_profile(self, user_id: int, profile: dict[str, Any]) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles(user_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  profile_json=excluded.profile_json,
                  updated_at=excluded.updated_at
                """,
                (user_id, _json_dumps(profile), now),
            )

    def get_profile(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json, updated_at FROM user_profiles WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return {"profile": _json_loads(row["profile_json"], {}), "updated_at": row["updated_at"]}

    def create_thread(
        self,
        user_id: int,
        *,
        title: str = "新会话",
        thread_id: str | None = None,
        state: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        thread_id = thread_id or uuid.uuid4().hex
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_threads(id, user_id, title, state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (thread_id, user_id, title, _json_dumps(state or {}), now, now),
            )
        return {
            "id": thread_id,
            "user_id": user_id,
            "title": title,
            "state": state or {},
            "created_at": now,
            "updated_at": now,
        }

    def update_thread(
        self,
        user_id: int,
        thread_id: str,
        *,
        title: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        fields: list[str] = ["updated_at=?"]
        values: list[Any] = [_utc_now()]
        if title is not None:
            fields.append("title=?")
            values.append(title)
        if state is not None:
            fields.append("state_json=?")
            values.append(_json_dumps(state))
        values.extend([thread_id, user_id])
        with self._connect() as conn:
            conn.execute(
                f"UPDATE chat_threads SET {', '.join(fields)} WHERE id=? AND user_id=?",
                tuple(values),
            )

    def get_thread(self, user_id: int, thread_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, title, state_json, created_at, updated_at
                FROM chat_threads
                WHERE id=? AND user_id=?
                """,
                (thread_id, user_id),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["state"] = _json_loads(record.pop("state_json"), {})
        return record

    def list_threads(self, user_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, state_json, created_at, updated_at
                FROM chat_threads
                WHERE user_id=?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["state"] = _json_loads(record.pop("state_json"), {})
            result.append(record)
        return result

    def append_message(
        self,
        user_id: int,
        thread_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        message_id = uuid.uuid4().hex
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages(id, user_id, thread_id, role, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, user_id, thread_id, role, content, _json_dumps(metadata or {}), now),
            )
            conn.execute(
                "UPDATE chat_threads SET updated_at=? WHERE id=? AND user_id=?",
                (now, thread_id, user_id),
            )
        return {
            "id": message_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": now,
        }

    def list_messages(self, user_id: int, thread_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, metadata_json, created_at
                FROM chat_messages
                WHERE user_id=? AND thread_id=?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (user_id, thread_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["metadata"] = _json_loads(record.pop("metadata_json"), {})
            result.append(record)
        return result

    def save_search_run(
        self,
        user_id: int,
        *,
        title: str,
        query_payload: dict[str, Any],
        result_payload: dict[str, Any],
        thread_id: str = "",
        search_run_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        search_run_id = search_run_id or uuid.uuid4().hex
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_search_runs(id, user_id, thread_id, title, query_json, result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  query_json=excluded.query_json,
                  result_json=excluded.result_json,
                  thread_id=excluded.thread_id,
                  updated_at=excluded.updated_at
                """,
                (
                    search_run_id,
                    user_id,
                    thread_id,
                    title,
                    _json_dumps(query_payload),
                    _json_dumps(result_payload),
                    now,
                    now,
                ),
            )
        return {
            "id": search_run_id,
            "title": title,
            "thread_id": thread_id,
            "query": query_payload,
            "result": result_payload,
            "created_at": now,
            "updated_at": now,
        }

    def replace_search_results(self, user_id: int, search_run_id: str, jobs: Iterable[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM user_search_results WHERE user_id=? AND search_run_id=?",
                (user_id, search_run_id),
            )
            for index, job in enumerate(jobs, start=1):
                conn.execute(
                    """
                    INSERT INTO user_search_results(search_run_id, user_id, job_id, rank_index, snapshot_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (search_run_id, user_id, job.get("job_id", ""), index, _json_dumps(job)),
                )

    def get_search_run(self, user_id: int, search_run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, thread_id, title, query_json, result_json, created_at, updated_at
                FROM user_search_runs
                WHERE id=? AND user_id=?
                """,
                (search_run_id, user_id),
            ).fetchone()
            result_rows = conn.execute(
                """
                SELECT snapshot_json
                FROM user_search_results
                WHERE search_run_id=? AND user_id=?
                ORDER BY rank_index ASC
                """,
                (search_run_id, user_id),
            ).fetchall()
        if row is None:
            return None
        record = dict(row)
        record["query"] = _json_loads(record.pop("query_json"), {})
        record["result"] = _json_loads(record.pop("result_json"), {})
        record["jobs"] = [_json_loads(item["snapshot_json"], {}) for item in result_rows]
        return record

    def list_search_runs(self, user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, thread_id, title, query_json, result_json, created_at, updated_at
                FROM user_search_runs
                WHERE user_id=?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["query"] = _json_loads(record.pop("query_json"), {})
            record["result"] = _json_loads(record.pop("result_json"), {})
            result.append(record)
        return result

    def upsert_job_snapshot(
        self,
        user_id: int,
        *,
        job_id: str,
        job: dict[str, Any],
        analysis: dict[str, Any] | None = None,
        match: dict[str, Any] | None = None,
        repos: list[dict[str, Any]] | None = None,
        suggestions: list[dict[str, Any]] | None = None,
        thread_id: str = "",
        search_run_id: str = "",
        created_at: str | None = None,
    ) -> None:
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_job_snapshots(
                    user_id, job_id, thread_id, search_run_id, job_json, analysis_json,
                    match_json, repos_json, suggestions_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, job_id) DO UPDATE SET
                  thread_id=excluded.thread_id,
                  search_run_id=excluded.search_run_id,
                  job_json=excluded.job_json,
                  analysis_json=excluded.analysis_json,
                  match_json=excluded.match_json,
                  repos_json=excluded.repos_json,
                  suggestions_json=excluded.suggestions_json,
                  updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    job_id,
                    thread_id,
                    search_run_id,
                    _json_dumps(job),
                    _json_dumps(analysis or {}),
                    _json_dumps(match or {}),
                    _json_dumps(repos or []),
                    _json_dumps(suggestions or []),
                    now,
                    now,
                ),
            )

    def get_job_snapshot(self, user_id: int, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, thread_id, search_run_id, job_json, analysis_json, match_json,
                       repos_json, suggestions_json, created_at, updated_at
                FROM user_job_snapshots
                WHERE user_id=? AND job_id=?
                """,
                (user_id, job_id),
            ).fetchone()
        if row is None:
            return None
        return self._snapshot_from_row(dict(row))

    def list_job_snapshots(
        self,
        user_id: int,
        *,
        limit: int = 20,
        thread_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT job_id, thread_id, search_run_id, job_json, analysis_json, match_json,
                   repos_json, suggestions_json, created_at, updated_at
            FROM user_job_snapshots
            WHERE user_id=?
        """
        params: list[Any] = [user_id]
        if thread_id is not None:
            query += " AND thread_id=?"
            params.append(thread_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._snapshot_from_row(dict(row)) for row in rows]

    def _snapshot_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        job = _json_loads(row.pop("job_json"), {})
        return {
            **job,
            "thread_id": row["thread_id"],
            "search_run_id": row["search_run_id"],
            "analysis": _json_loads(row.pop("analysis_json"), {}),
            "match": _json_loads(row.pop("match_json"), {}),
            "repos": _json_loads(row.pop("repos_json"), []),
            "suggestions": _json_loads(row.pop("suggestions_json"), []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_learning_plan(
        self,
        user_id: int,
        *,
        job_id: str,
        timeframe: str,
        plan: dict[str, Any],
        formatted_plan: str,
        plan_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        plan_id = plan_id or uuid.uuid4().hex
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_learning_plans(id, user_id, job_id, timeframe, plan_json, formatted_plan, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (plan_id, user_id, job_id, timeframe, _json_dumps(plan), formatted_plan, now),
            )
        return {
            "id": plan_id,
            "job_id": job_id,
            "timeframe": timeframe,
            "plan": plan,
            "formatted_plan": formatted_plan,
            "created_at": now,
        }

    def list_learning_plans(self, user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, job_id, timeframe, plan_json, formatted_plan, created_at
                FROM user_learning_plans
                WHERE user_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["plan"] = _json_loads(record.pop("plan_json"), {})
            result.append(record)
        return result

    def get_learning_plan(self, user_id: int, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, job_id, timeframe, plan_json, formatted_plan, created_at
                FROM user_learning_plans
                WHERE user_id=? AND id=?
                """,
                (user_id, plan_id),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["plan"] = _json_loads(record.pop("plan_json"), {})
        return record

    def save_artifact(
        self,
        user_id: int,
        *,
        kind: str,
        title: str,
        summary: str,
        file_path: str,
        metadata: dict[str, Any] | None = None,
        artifact_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        artifact_id = artifact_id or uuid.uuid4().hex
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_artifacts(id, user_id, kind, title, summary, file_path, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, user_id, kind, title, summary, file_path, _json_dumps(metadata or {}), now),
            )
        return {
            "id": artifact_id,
            "kind": kind,
            "title": title,
            "summary": summary,
            "file_path": file_path,
            "metadata": metadata or {},
            "created_at": now,
        }

    def list_artifacts(self, user_id: int, *, limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT id, kind, title, summary, file_path, metadata_json, created_at
            FROM user_artifacts
            WHERE user_id=?
        """
        params: list[Any] = [user_id]
        if kind is not None:
            query += " AND kind=?"
            params.append(kind)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["metadata"] = _json_loads(record.pop("metadata_json"), {})
            result.append(record)
        return result

    def get_artifact(self, user_id: int, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, title, summary, file_path, metadata_json, created_at
                FROM user_artifacts
                WHERE user_id=? AND id=?
                """,
                (user_id, artifact_id),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["metadata"] = _json_loads(record.pop("metadata_json"), {})
        return record

    def save_repo_audit(
        self,
        user_id: int,
        *,
        repo_url: str,
        result: dict[str, Any],
        artifact_id: str = "",
        audit_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        audit_id = audit_id or uuid.uuid4().hex
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_repo_audits(id, user_id, repo_url, verdict, summary, result_json, artifact_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    user_id,
                    repo_url,
                    result.get("verdict", ""),
                    result.get("summary", ""),
                    _json_dumps(result),
                    artifact_id,
                    now,
                ),
            )
        return {
            "id": audit_id,
            "repo_url": repo_url,
            "verdict": result.get("verdict", ""),
            "summary": result.get("summary", ""),
            "result": result,
            "artifact_id": artifact_id,
            "created_at": now,
        }

    def get_repo_audit(self, user_id: int, audit_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, repo_url, verdict, summary, result_json, artifact_id, created_at
                FROM user_repo_audits
                WHERE user_id=? AND id=?
                """,
                (user_id, audit_id),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["result"] = _json_loads(record.pop("result_json"), {})
        return record

    def list_repo_audits(self, user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, repo_url, verdict, summary, result_json, artifact_id, created_at
                FROM user_repo_audits
                WHERE user_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["result"] = _json_loads(record.pop("result_json"), {})
            result.append(record)
        return result

    def save_github_search(
        self,
        user_id: int,
        *,
        search_id: str | None = None,
        user_query: str,
        keywords: list[str] | None = None,
        min_stars: int = 1000,
        top_n: int = 5,
        include_audit: bool = False,
        include_similar: bool = True,
        status: str = "success",
        repos: list[dict[str, Any]] | None = None,
        replan_options: list[str] | None = None,
        retry_context: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        search_id = search_id or f"search_{uuid.uuid4().hex[:12]}"
        now = created_at or _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_github_searches(
                    search_id, user_id, user_query, keywords, min_stars, top_n,
                    include_audit, include_similar, status, repos, replan_options,
                    retry_context, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    search_id,
                    user_id,
                    user_query,
                    _json_dumps(keywords or []),
                    min_stars,
                    top_n,
                    1 if include_audit else 0,
                    1 if include_similar else 0,
                    status,
                    _json_dumps(repos or []),
                    _json_dumps(replan_options or []),
                    _json_dumps(retry_context or {}),
                    now,
                ),
            )
        return {
            "search_id": search_id,
            "user_query": user_query,
            "keywords": keywords or [],
            "min_stars": min_stars,
            "top_n": top_n,
            "include_audit": include_audit,
            "include_similar": include_similar,
            "status": status,
            "repos": repos or [],
            "replan_options": replan_options or [],
            "retry_context": retry_context or {},
            "created_at": now,
        }

    def get_github_search(self, user_id: int, search_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT search_id, user_query, keywords, min_stars, top_n,
                       include_audit, include_similar, status, repos,
                       replan_options, retry_context, created_at
                FROM user_github_searches
                WHERE user_id=? AND search_id=?
                """,
                (user_id, search_id),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["keywords"] = _json_loads(record["keywords"], [])
        record["include_audit"] = bool(record["include_audit"])
        record["include_similar"] = bool(record["include_similar"])
        record["repos"] = _json_loads(record["repos"], [])
        record["replan_options"] = _json_loads(record["replan_options"], [])
        record["retry_context"] = _json_loads(record["retry_context"], {})
        return record

    def list_github_searches(self, user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT search_id, user_query, keywords, min_stars, top_n,
                       include_audit, include_similar, status, repos,
                       replan_options, retry_context, created_at
                FROM user_github_searches
                WHERE user_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["keywords"] = _json_loads(record["keywords"], [])
            record["include_audit"] = bool(record["include_audit"])
            record["include_similar"] = bool(record["include_similar"])
            record["repos"] = _json_loads(record["repos"], [])
            record["replan_options"] = _json_loads(record["replan_options"], [])
            record["retry_context"] = _json_loads(record["retry_context"], {})
            result.append(record)
        return result
