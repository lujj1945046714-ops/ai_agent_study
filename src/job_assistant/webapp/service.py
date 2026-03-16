from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from job_assistant import config
from job_assistant.agent.job_agent import JobAssistantAgent
from job_assistant.agent.state import JobAssistantState
from job_assistant.agent.tools import AnalyzeJobTool, CreateLearningPlanTool, MatchJobTool, RecommendLearningTool, SearchGitHubTool
from job_assistant.job_discovery import JobDiscoveryService
from job_assistant.llm_runtime import complete_json, create_chat_model
from job_assistant.modules import smart_recommend_projects
from job_assistant.onboarding import extract_profile_from_resume, format_profile_summary
from job_assistant.persistence.sqlite_store import SQLiteJobStore, SQLiteJobStoreConfig
from job_assistant.repo_audit import audit_repository
from job_assistant.webapp.db import WebAppStore
from job_assistant.webapp.security import PasswordManager


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower() or "item"


def _read_text(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk", errors="replace")[:limit]


class WebAppService:
    def __init__(self, store: WebAppStore):
        self.store = store
        self.passwords = PasswordManager()
        self.shared_store = SQLiteJobStore(SQLiteJobStoreConfig(db_path=config.DB_PATH))

    def register_user(self, username: str, password: str) -> dict[str, Any]:
        username = username.strip()
        if len(username) < 3:
            raise ValueError("用户名至少需要 3 个字符")
        if len(password) < 8:
            raise ValueError("密码至少需要 8 个字符")
        if self.store.get_user_by_username(username):
            raise ValueError("用户名已存在")

        user = self.store.create_user(username, self.passwords.hash_password(password))
        self._ensure_user_dirs(user["id"])
        self._maybe_migrate_legacy_data(user["id"])
        return user

    def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.store.get_user_by_username(username.strip())
        if not user:
            return None
        if not self.passwords.verify_password(password, user["password_hash"]):
            return None
        return {"id": user["id"], "username": user["username"], "created_at": user["created_at"]}

    def create_session(self, user_id: int) -> dict[str, Any]:
        return self.store.create_session(user_id)

    def get_user_from_session(self, session_id: str) -> dict[str, Any] | None:
        return self.store.get_user_by_session(session_id)

    def logout(self, session_id: str) -> None:
        self.store.delete_session(session_id)

    def get_profile(self, user_id: int) -> dict[str, Any] | None:
        record = self.store.get_profile(user_id)
        return record["profile"] if record else None

    def save_profile(self, user_id: int, profile: dict[str, Any]) -> dict[str, Any]:
        self.store.upsert_profile(user_id, profile)
        return profile

    def extract_profile_from_resume_text(self, user_id: int, resume_text: str) -> dict[str, Any]:
        profile = extract_profile_from_resume(resume_text, llm=create_chat_model())
        self.store.upsert_profile(user_id, profile)
        return profile

    def create_thread(self, user_id: int, title: str = "新会话") -> dict[str, Any]:
        thread = self.store.create_thread(user_id, title=title)
        return self.get_thread_detail(user_id, thread["id"])

    def list_threads(self, user_id: int) -> list[dict[str, Any]]:
        return self.store.list_threads(user_id)

    def get_thread_detail(self, user_id: int, thread_id: str) -> dict[str, Any]:
        thread = self.store.get_thread(user_id, thread_id)
        if thread is None:
            raise KeyError("会话不存在")
        return {
            **thread,
            "messages": self.store.list_messages(user_id, thread_id),
            "jobs": self.store.list_job_snapshots(user_id, limit=50, thread_id=thread_id),
        }

    def post_thread_message(
        self,
        user_id: int,
        thread_id: str,
        *,
        message: str,
        jd_text: str = "",
        jd_title: str = "",
        jd_city: str = "",
    ) -> dict[str, Any]:
        profile = self.get_profile(user_id)
        if not profile:
            raise ValueError("请先建立用户画像")

        thread = self.store.get_thread(user_id, thread_id)
        if thread is None:
            raise KeyError("会话不存在")

        prompt = message.strip()
        if not prompt and jd_text.strip():
            prompt = "请分析这个职位与我的匹配度，列出匹配技能和技能缺口"
        if not prompt:
            raise ValueError("消息不能为空")

        before_files = self._collect_output_files(user_id)
        agent = self._build_agent(user_id, thread_id, profile)

        jobs = []
        if jd_text.strip():
            jobs = self._parse_jd_jobs(jd_text, jd_title=jd_title, jd_city=jd_city)
            agent.preload_jobs(jobs)

        self.store.append_message(
            user_id,
            thread_id,
            role="user",
            content=prompt,
            metadata={
                "jd_attached": bool(jd_text.strip()),
                "jd_title": jd_title.strip(),
                "jd_city": jd_city.strip(),
                "job_ids": [job["job_id"] for job in jobs],
            },
        )

        response = agent.run(prompt)

        self.store.append_message(
            user_id,
            thread_id,
            role="assistant",
            content=response,
            metadata={"job_ids": list(agent.state.job_store.keys())},
        )

        self._persist_agent_state(user_id, thread_id, agent)
        self._persist_new_artifacts(user_id, before_files)
        self._update_thread_title(user_id, thread_id, thread["title"], prompt)

        return {
            "thread": self.get_thread_detail(user_id, thread_id),
            "profile_summary": format_profile_summary(profile),
        }

    def search_jobs(
        self,
        user_id: int,
        *,
        keywords: list[str],
        cities: list[str] | None = None,
        salary_min_k: int | None = None,
        salary_max_k: int | None = None,
        max_results: int = 10,
        refresh: bool = False,
        thread_id: str = "",
    ) -> dict[str, Any]:
        profile = self.get_profile(user_id)
        if not profile:
            raise ValueError("请先建立用户画像")

        service = JobDiscoveryService(store=self.shared_store)
        result = service.discover(
            profile,
            cities=cities or None,
            keywords=keywords or None,
            salary_min_k=salary_min_k,
            salary_max_k=salary_max_k,
            max_results=max_results,
            refresh=refresh,
        )
        title = " / ".join(keywords[:3]) or "岗位搜索"
        record = self.store.save_search_run(
            user_id,
            title=title,
            query_payload={
                "keywords": keywords,
                "cities": cities or [],
                "salary_min_k": salary_min_k or 0,
                "salary_max_k": salary_max_k or 0,
                "max_results": max_results,
                "refresh": refresh,
            },
            result_payload=result,
            thread_id=thread_id,
            search_run_id=result.get("run_id") or uuid.uuid4().hex,
        )

        shortlist = list(result.get("shortlist", []))
        self.store.replace_search_results(user_id, record["id"], shortlist)
        for job in shortlist:
            self.store.upsert_job_snapshot(
                user_id,
                job_id=job.get("job_id", ""),
                job={
                    "job_id": job.get("job_id", ""),
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "city": job.get("city", ""),
                    "salary": job.get("salary", ""),
                    "jd_text": job.get("jd_text", ""),
                    "source": job.get("source", ""),
                    "source_url": job.get("source_url", ""),
                    "post_time": job.get("post_time", ""),
                },
                analysis=job.get("analysis", {}),
                match=job.get("match", {}),
                repos=[],
                suggestions=[],
                thread_id=thread_id,
                search_run_id=record["id"],
            )
        return self.store.get_search_run(user_id, record["id"]) or record

    def list_search_runs(self, user_id: int) -> list[dict[str, Any]]:
        return self.store.list_search_runs(user_id)

    def get_search_run(self, user_id: int, search_run_id: str) -> dict[str, Any]:
        record = self.store.get_search_run(user_id, search_run_id)
        if record is None:
            raise KeyError("搜索记录不存在")
        return record

    def analyze_job(self, user_id: int, job_id: str) -> dict[str, Any]:
        profile = self.get_profile(user_id)
        snapshot = self.store.get_job_snapshot(user_id, job_id)
        if not profile or not snapshot:
            raise KeyError("职位不存在")

        state = JobAssistantState(profile=profile, output_dir=self._user_output_dir(user_id))
        state.job_store[job_id] = {
            "job_id": snapshot["job_id"],
            "title": snapshot.get("title", ""),
            "company": snapshot.get("company", ""),
            "city": snapshot.get("city", ""),
            "salary": snapshot.get("salary", ""),
            "jd_text": snapshot.get("jd_text", ""),
            "source": snapshot.get("source", ""),
            "source_url": snapshot.get("source_url", ""),
        }
        if snapshot.get("analysis"):
            state.results.setdefault(job_id, {})["analysis"] = snapshot["analysis"]
        if snapshot.get("match"):
            state.results.setdefault(job_id, {})["match"] = snapshot["match"]
        if snapshot.get("repos"):
            state.results.setdefault(job_id, {})["repos"] = snapshot["repos"]

        analysis = AnalyzeJobTool(state).execute(job_id=job_id)
        match = MatchJobTool(state).execute(job_id=job_id, analysis=analysis)
        repos = snapshot.get("repos", [])
        if not repos and int(match.get("score", 0) or 0) >= 25:
            rec = RecommendLearningTool(state).execute(
                job_id=job_id,
                skill_gaps=list(match.get("skill_gaps", [])),
                top_n=config.GITHUB_TOP_N,
            )
            repos = list(rec.get("repos", []))

        self.store.upsert_job_snapshot(
            user_id,
            job_id=job_id,
            job=state.job_store[job_id],
            analysis=analysis,
            match=match,
            repos=repos,
            suggestions=snapshot.get("suggestions", []),
            thread_id=snapshot.get("thread_id", ""),
            search_run_id=snapshot.get("search_run_id", ""),
        )
        return self.store.get_job_snapshot(user_id, job_id) or snapshot

    def create_learning_plan(self, user_id: int, job_id: str, timeframe: str) -> dict[str, Any]:
        profile = self.get_profile(user_id)
        snapshot = self.store.get_job_snapshot(user_id, job_id)
        if not profile or not snapshot:
            raise KeyError("职位不存在")
        state = JobAssistantState(profile=profile, output_dir=self._user_output_dir(user_id))
        state.job_store[job_id] = {
            "job_id": snapshot["job_id"],
            "title": snapshot.get("title", ""),
            "company": snapshot.get("company", ""),
            "city": snapshot.get("city", ""),
            "salary": snapshot.get("salary", ""),
            "jd_text": snapshot.get("jd_text", ""),
        }
        state.results[job_id] = {
            "analysis": snapshot.get("analysis", {}),
            "match": snapshot.get("match", {}),
            "repos": snapshot.get("repos", []),
            "suggestions": snapshot.get("suggestions", []),
        }
        result = CreateLearningPlanTool(state).execute(job_id=job_id, timeframe=timeframe)
        return self.store.save_learning_plan(
            user_id,
            job_id=job_id,
            timeframe=timeframe,
            plan=result.get("plan", {}),
            formatted_plan=result.get("formatted_plan", ""),
        )

    def list_learning_plans(self, user_id: int) -> list[dict[str, Any]]:
        return self.store.list_learning_plans(user_id)

    def get_artifact(self, user_id: int, artifact_id: str) -> dict[str, Any]:
        artifact = self.store.get_artifact(user_id, artifact_id)
        if artifact is None:
            raise KeyError("文件不存在")
        return artifact

    def list_artifacts(self, user_id: int, *, kind: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_artifacts(user_id, kind=kind)

    def get_repo_audit(self, user_id: int, audit_id: str) -> dict[str, Any]:
        audit_record = self.store.get_repo_audit(user_id, audit_id)
        if audit_record is None:
            raise KeyError("审计记录不存在")
        return audit_record

    def list_repo_audits(self, user_id: int) -> list[dict[str, Any]]:
        return self.store.list_repo_audits(user_id)

    def get_dashboard(self, user_id: int) -> dict[str, Any]:
        profile = self.get_profile(user_id)
        recent_threads = self.store.list_threads(user_id, limit=6)
        recent_searches = self.store.list_search_runs(user_id, limit=6)
        recent_jobs = self.store.list_job_snapshots(user_id, limit=6)
        recent_plans = self.store.list_learning_plans(user_id, limit=6)
        recent_artifacts = self.store.list_artifacts(user_id, limit=8)
        recent_audits = self.store.list_repo_audits(user_id, limit=6)
        return {
            "profile": profile,
            "profile_summary": format_profile_summary(profile) if profile else "",
            "counts": {
                "threads": len(self.store.list_threads(user_id, limit=100)),
                "searches": len(self.store.list_search_runs(user_id, limit=100)),
                "jobs": len(self.store.list_job_snapshots(user_id, limit=100)),
                "plans": len(self.store.list_learning_plans(user_id, limit=100)),
                "artifacts": len(self.store.list_artifacts(user_id, limit=100)),
            },
            "recent_threads": recent_threads,
            "recent_searches": recent_searches,
            "recent_jobs": recent_jobs,
            "recent_plans": recent_plans,
            "recent_artifacts": recent_artifacts,
            "recent_audits": recent_audits,
        }

    def _ensure_user_dirs(self, user_id: int) -> Path:
        user_dir = self._user_output_dir(user_id)
        (user_dir / "traces").mkdir(parents=True, exist_ok=True)
        (user_dir / "reports").mkdir(parents=True, exist_ok=True)
        (user_dir / "repo_audits").mkdir(parents=True, exist_ok=True)
        return user_dir

    def _user_output_dir(self, user_id: int) -> Path:
        return config.USER_OUTPUT_DIR / f"user_{user_id}"

    def _build_agent(self, user_id: int, thread_id: str, profile: dict[str, Any]) -> JobAssistantAgent:
        output_dir = self._ensure_user_dirs(user_id)
        agent = JobAssistantAgent(
            user_profile=profile,
            session_id=thread_id,
            output_dir=output_dir,
            enable_phase2=True,
        )
        snapshots = self.store.list_job_snapshots(user_id, limit=100, thread_id=thread_id)
        for snapshot in snapshots:
            job_id = snapshot["job_id"]
            agent.state.job_store[job_id] = {
                "job_id": snapshot["job_id"],
                "title": snapshot.get("title", ""),
                "company": snapshot.get("company", ""),
                "city": snapshot.get("city", ""),
                "salary": snapshot.get("salary", ""),
                "jd_text": snapshot.get("jd_text", ""),
                "source": snapshot.get("source", ""),
                "source_url": snapshot.get("source_url", ""),
                "post_time": snapshot.get("post_time", ""),
            }
            agent.state.results[job_id] = {
                "analysis": snapshot.get("analysis", {}),
                "match": snapshot.get("match", {}),
                "repos": snapshot.get("repos", []),
                "suggestions": snapshot.get("suggestions", []),
            }
        return agent

    def _persist_agent_state(self, user_id: int, thread_id: str, agent: JobAssistantAgent) -> None:
        for job_id, job in agent.state.job_store.items():
            result = agent.state.results.get(job_id, {})
            self.store.upsert_job_snapshot(
                user_id,
                job_id=job_id,
                job=job,
                analysis=result.get("analysis", {}),
                match=result.get("match", {}),
                repos=result.get("repos", []),
                suggestions=result.get("suggestions", []),
                thread_id=thread_id,
            )

    def _collect_output_files(self, user_id: int) -> set[str]:
        base = self._ensure_user_dirs(user_id)
        return {str(path.resolve()) for path in base.rglob("*") if path.is_file()}

    def _persist_new_artifacts(self, user_id: int, before_files: set[str]) -> None:
        user_dir = self._ensure_user_dirs(user_id)
        after_files = self._collect_output_files(user_id)
        for raw_path in sorted(after_files - before_files):
            path = Path(raw_path)
            rel = path.relative_to(user_dir)
            if rel.parts[0] == "traces":
                self.store.save_artifact(
                    user_id,
                    kind="trace",
                    title=path.stem,
                    summary="Agent 运行轨迹",
                    file_path=str(path),
                    metadata={"relative_path": str(rel)},
                )
                continue
            if rel.parts[0] == "reports" or path.name.startswith("report_agent_"):
                summary = _read_text(path, limit=300).splitlines()
                preview = summary[0] if summary else "求职分析报告"
                self.store.save_artifact(
                    user_id,
                    kind="report",
                    title=path.stem,
                    summary=preview[:180],
                    file_path=str(path),
                    metadata={"relative_path": str(rel)},
                )
                continue
            if "repo_audits" in rel.parts and path.name == "audit.json":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                artifact = self.store.save_artifact(
                    user_id,
                    kind="audit",
                    title=payload.get("repo", {}).get("display_name", path.parent.name),
                    summary=payload.get("summary", "仓库审计结果"),
                    file_path=str(path),
                    metadata={
                        "relative_path": str(rel),
                        "artifacts": payload.get("artifacts", {}),
                        "workspace": payload.get("workspace", {}),
                    },
                )
                self.store.save_repo_audit(
                    user_id,
                    repo_url=payload.get("repo", {}).get("source", path.parent.name),
                    result=payload,
                    artifact_id=artifact["id"],
                )

    def _update_thread_title(self, user_id: int, thread_id: str, current_title: str, prompt: str) -> None:
        if current_title != "新会话":
            return
        new_title = (prompt or "新会话").strip()[:32]
        self.store.update_thread(user_id, thread_id, title=new_title or "新会话")

    def _parse_jd_jobs(self, jd_text: str, *, jd_title: str = "", jd_city: str = "") -> list[dict[str, Any]]:
        llm = create_chat_model()
        segments = self._split_jd_segments(jd_text)
        jobs: list[dict[str, Any]] = []
        missing_segments: list[int] = []
        use_manual = bool(jd_title.strip() and jd_city.strip())
        for index, segment in enumerate(segments, start=1):
            parsed = self._parse_jd_text(llm, segment, index - 1)
            if use_manual:
                parsed = parsed or {
                    "job_id": f"jd-{index:03d}",
                    "title": jd_title.strip(),
                    "company": "",
                    "city": jd_city.strip(),
                    "salary": "面议",
                    "jd_text": segment,
                }
                parsed["title"] = jd_title.strip()
                parsed["city"] = jd_city.strip()
                jobs.append(parsed)
                continue
            if parsed is None or not parsed.get("title") or not parsed.get("city"):
                missing_segments.append(index)
                continue
            jobs.append(parsed)
        if missing_segments:
            raise ValueError(f"第 {missing_segments} 段 JD 未能识别出岗位名称或城市，请手动填写岗位名称和城市后重试")
        if not jobs:
            raise ValueError("没有可分析的职位")
        return jobs

    def _split_jd_segments(self, raw: str) -> list[str]:
        normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
        return [segment.strip() for segment in re.split(r"(?m)^\s*---\s*$", normalized) if segment.strip()]

    def _parse_jd_text(self, llm: Any, jd_text: str, job_index: int) -> dict[str, Any] | None:
        try:
            prompt = f"""请从以下职位描述中提取结构化信息，返回单个 JSON 对象：
{{
  "title": "职位名称",
  "company": "公司名称",
  "city": "城市",
  "salary": "薪资范围"
}}

职位描述：
{jd_text[:3000]}

只返回 JSON，不要其他内容。"""
            parsed = complete_json([{"role": "user", "content": prompt}], llm=llm, temperature=0)
            return {
                "job_id": f"jd-{job_index + 1:03d}",
                "title": parsed.get("title", ""),
                "company": parsed.get("company", ""),
                "city": parsed.get("city", ""),
                "salary": parsed.get("salary", "面议"),
                "jd_text": jd_text,
            }
        except Exception:
            return None

    def _maybe_migrate_legacy_data(self, user_id: int) -> None:
        if self.store.get_meta("legacy_migrated_user_id"):
            return
        if self.store.count_users() != 1:
            return

        user_dir = self._ensure_user_dirs(user_id)
        profile_path = config.PROFILES_DIR / "user_profile.json"
        if profile_path.exists():
            self.store.upsert_profile(user_id, json.loads(profile_path.read_text(encoding="utf-8")))

        session_path = config.OUTPUT_DIR / "session_web_session.json"
        if session_path.exists():
            legacy_thread = self.store.create_thread(
                user_id,
                title="Legacy Web Session",
                thread_id="legacy_web_session",
                state={"legacy_source": str(session_path)},
            )
            target_session = user_dir / "session_legacy_web_session.json"
            shutil.copy2(session_path, target_session)
            session_data = json.loads(session_path.read_text(encoding="utf-8"))
            for turn in session_data.get("conversation_history", []):
                if turn.get("user"):
                    self.store.append_message(
                        user_id,
                        legacy_thread["id"],
                        role="user",
                        content=turn.get("user", ""),
                        metadata=turn.get("metadata", {}),
                        created_at=turn.get("timestamp"),
                    )
                if turn.get("agent"):
                    self.store.append_message(
                        user_id,
                        legacy_thread["id"],
                        role="assistant",
                        content=turn.get("agent", ""),
                        metadata=turn.get("metadata", {}),
                        created_at=turn.get("timestamp"),
                    )

        for report in sorted(config.OUTPUT_DIR.glob("report_agent_*.md")):
            target = user_dir / "reports" / report.name
            if not target.exists():
                shutil.copy2(report, target)
            lines = _read_text(target, limit=300).splitlines()
            self.store.save_artifact(
                user_id,
                kind="report",
                title=target.stem,
                summary=(lines[0] if lines else "历史报告")[:180],
                file_path=str(target),
                metadata={"legacy": True},
            )

        repo_audit_root = config.OUTPUT_DIR / "repo_audits"
        if repo_audit_root.exists():
            for audit_dir in sorted(repo_audit_root.iterdir()):
                if not audit_dir.is_dir():
                    continue
                target_dir = user_dir / "repo_audits" / audit_dir.name
                if not target_dir.exists():
                    shutil.copytree(audit_dir, target_dir)
                audit_json = target_dir / "audit.json"
                if not audit_json.exists():
                    continue
                try:
                    payload = json.loads(audit_json.read_text(encoding="utf-8"))
                except Exception:
                    continue
                artifact = self.store.save_artifact(
                    user_id,
                    kind="audit",
                    title=payload.get("repo", {}).get("display_name", audit_dir.name),
                    summary=payload.get("summary", "历史仓库审计"),
                    file_path=str(audit_json),
                    metadata={"legacy": True, "artifacts": payload.get("artifacts", {})},
                )
                self.store.save_repo_audit(
                    user_id,
                    repo_url=payload.get("repo", {}).get("source", audit_dir.name),
                    result=payload,
                    artifact_id=artifact["id"],
                )

        if config.DB_PATH.exists():
            self._migrate_legacy_job_data(user_id, config.DB_PATH)

        self.store.set_meta("legacy_migrated_user_id", str(user_id))

    def _migrate_legacy_job_data(self, user_id: int, db_path: Path) -> None:
        try:
            recent_jobs = self.shared_store.list_recent_enriched(limit=200)
        except Exception:
            recent_jobs = []
        for job in recent_jobs:
            self.store.upsert_job_snapshot(
                user_id,
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
                repos=job.get("repos", []),
                suggestions=job.get("suggestions", []),
                thread_id="legacy_web_session",
            )

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT run_id, search_spec_json, shortlist_json, refresh_mode, status, error, created_at
                FROM discovery_runs
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
        for row in rows:
            record = dict(row)
            query_payload = json.loads(record.get("search_spec_json") or "{}")
            result_payload = {
                "refresh_mode": record.get("refresh_mode", ""),
                "status": record.get("status", ""),
                "error": record.get("error", ""),
                "shortlist": json.loads(record.get("shortlist_json") or "[]"),
            }
            saved = self.store.save_search_run(
                user_id,
                title=" / ".join(query_payload.get("keywords", [])[:3]) or "历史岗位搜索",
                query_payload=query_payload,
                result_payload=result_payload,
                thread_id="legacy_web_session",
                search_run_id=record.get("run_id", _safe_slug(uuid.uuid4().hex)),
                created_at=record.get("created_at"),
            )
            jobs = result_payload.get("shortlist", [])
            self.store.replace_search_results(user_id, saved["id"], jobs)
            for job in jobs:
                self.store.upsert_job_snapshot(
                    user_id,
                    job_id=job.get("job_id", ""),
                    job={
                        "job_id": job.get("job_id", ""),
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "city": job.get("city", ""),
                        "salary": job.get("salary", ""),
                        "jd_text": job.get("jd_text", ""),
                        "source": job.get("source", ""),
                        "source_url": job.get("source_url", ""),
                        "post_time": job.get("post_time", ""),
                    },
                    analysis=job.get("analysis", {}),
                    match=job.get("match", {}),
                    repos=job.get("repos", []),
                    suggestions=job.get("suggestions", []),
                    thread_id="legacy_web_session",
                    search_run_id=saved["id"],
                    created_at=record.get("created_at"),
                )

    def search_github_projects(
        self,
        user_id: int,
        *,
        user_query: str,
        min_stars: int = 1000,
        top_n: int = 5,
        include_audit: bool = False,
        include_similar: bool = True,
        use_profile: bool = False,
        user_choice: str | None = None,
        retry_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行 GitHub 项目搜索"""
        # 根据 use_profile 决定是否使用用户画像
        if use_profile:
            profile = self.get_profile(user_id) or {}
        else:
            profile = {}  # 传递空画像,实现独立搜索

        # 从用户查询中提取技能关键词作为 skill_gaps
        skill_gaps = [user_query]

        # 调用 smart_recommend_projects
        result = smart_recommend_projects(
            skill_gaps=skill_gaps,
            profile=profile,
            analysis={},
            top_n=top_n,
            user_choice=user_choice,
            retry_context=retry_context,
            audit_top_repo=include_audit,
            audit_expected_capabilities=[],
            audit_allow_light_run=True,
            audit_keep_workspace=False,
        )

        # 保存搜索记录
        search_record = self.store.save_github_search(
            user_id,
            user_query=user_query,
            min_stars=min_stars,
            top_n=top_n,
            include_audit=include_audit,
            include_similar=include_similar,
            status=result.get("status", "success"),
            repos=result.get("repos", []),
            replan_options=result.get("replan_options", []),
            retry_context=result.get("retry_context", {}),
        )

        return search_record

    def get_github_search(self, user_id: int, search_id: str) -> dict[str, Any] | None:
        """获取 GitHub 搜索记录"""
        return self.store.get_github_search(user_id, search_id)

    def list_github_searches(self, user_id: int) -> list[dict[str, Any]]:
        """列出 GitHub 搜索历史"""
        return self.store.list_github_searches(user_id)

    def audit_github_repo(
        self,
        user_id: int,
        *,
        owner: str,
        repo: str,
        expected_capabilities: list[str] | None = None,
        allow_light_run: bool = True,
        keep_workspace: bool = False,
    ) -> dict[str, Any]:
        """审计 GitHub 仓库"""
        repo_url = f"https://github.com/{owner}/{repo}"
        return self._audit_repo_from_url(
            user_id,
            repo_url,
            expected_capabilities=expected_capabilities or [],
            allow_light_run=allow_light_run,
            keep_workspace=keep_workspace,
        )

    def _audit_repo_from_url(
        self,
        user_id: int,
        repo_url: str,
        expected_capabilities: list[str] | None = None,
        allow_light_run: bool = True,
        keep_workspace: bool = False,
    ) -> dict[str, Any]:
        """从 URL 审计仓库的内部方法"""
        user_dir = self._ensure_user_dirs(user_id)
        audit_output_dir = user_dir / "repo_audits"

        before_files = self._collect_output_files(user_id)

        result = audit_repository(
            repo_url,
            expected_capabilities=expected_capabilities or [],
            output_dir=audit_output_dir,
            allow_light_run=allow_light_run,
            keep_workspace=keep_workspace,
        )

        self._persist_new_artifacts(user_id, before_files)

        return result
