from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from job_assistant import config
from job_assistant.agent.state import JobAssistantState
from job_assistant.webapp.app import create_app


def _patch_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORKDIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "USER_OUTPUT_DIR", tmp_path / "output" / "users")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "jobs.db")
    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "data" / "app.db")


class FakeDiscoveryService:
    def __init__(self, store=None):
        self.store = store

    def discover(self, profile, **kwargs):
        return {
            "run_id": "run_demo",
            "status": "success",
            "shortlist": [
                {
                    "job_id": "disc-001",
                    "title": "AI Agent 工程师",
                    "company": "示例公司",
                    "city": "上海",
                    "salary": "30-45K",
                    "jd_text": "负责 Agent 系统开发",
                    "source": "example.com",
                    "source_url": "https://example.com/job/1",
                    "post_time": "今天",
                    "analysis": {"summary": "Agent 工程岗位", "job_level": "中级"},
                    "match": {"score": 81, "skill_gaps": ["RAG"], "matched_skills": ["Python"]},
                }
            ],
        }


class FakeAgent:
    def __init__(self, *, user_profile, output_dir, session_id, enable_phase2=True, max_steps=30):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "traces").mkdir(parents=True, exist_ok=True)
        self.state = JobAssistantState(profile=user_profile, output_dir=self.output_dir)
        self.session_id = session_id
        self.enable_phase2 = enable_phase2
        self.conversation_memory = None
        self.last_run_result = None

    def preload_jobs(self, jobs):
        for job in jobs:
            self.state.job_store[job["job_id"]] = job

    def run(self, task, **kwargs):
        if self.state.job_store:
            for job_id, job in self.state.job_store.items():
                self.state.results[job_id] = {
                    "analysis": {"summary": f"分析 {job.get('title', job_id)}", "job_level": "中级"},
                    "match": {"score": 78, "skill_gaps": ["RAG"], "matched_skills": ["Python", "Agent"]},
                    "repos": [],
                    "suggestions": [],
                }
        trace_file = self.output_dir / "traces" / f"{self.session_id}_trace.jsonl"
        trace_file.write_text('{"event":"fake"}\n', encoding="utf-8")
        return f"assistant::{task}"


def test_api_isolates_users_and_persists_searches(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    config.ensure_dirs()
    monkeypatch.setattr("job_assistant.webapp.service.JobDiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr("job_assistant.webapp.service.JobAssistantAgent", FakeAgent)

    app = create_app()
    alice = TestClient(app)
    bob = TestClient(app)

    register_alice = alice.post("/api/auth/register", json={"username": "alice", "password": "password123"})
    assert register_alice.status_code == 200
    alice.put(
        "/api/profile",
        json={
            "profile": {
                "name": "Alice",
                "skills": {"Python": {"level": 4, "years": 4}},
                "experience_years": 4,
                "target_roles": ["AI Agent 工程师"],
                "preferences": {"cities": ["上海"], "salary_min_k": 30, "salary_max_k": 45},
            }
        },
    )

    created_thread = alice.post("/api/threads", json={"title": "Alice Thread"})
    thread_id = created_thread.json()["id"]
    sent = alice.post(
        f"/api/threads/{thread_id}/messages",
        json={"message": "继续分析"},
    )
    assert sent.status_code == 200
    assert sent.json()["thread"]["messages"][-1]["content"] == "assistant::继续分析"

    search = alice.post(
        "/api/searches",
        json={"keywords": ["AI Agent 工程师"], "cities": ["上海"], "maxResults": 5, "refresh": False},
    )
    assert search.status_code == 200
    assert search.json()["jobs"][0]["title"] == "AI Agent 工程师"

    register_bob = bob.post("/api/auth/register", json={"username": "bob", "password": "password123"})
    assert register_bob.status_code == 200
    bob.put(
        "/api/profile",
        json={
            "profile": {
                "name": "Bob",
                "skills": {"Python": {"level": 2, "years": 1}},
                "experience_years": 1,
                "target_roles": ["Python 工程师"],
                "preferences": {"cities": ["杭州"], "salary_min_k": 15, "salary_max_k": 25},
            }
        },
    )

    bob_threads = bob.get("/api/threads").json()["items"]
    bob_searches = bob.get("/api/searches").json()["items"]
    alice_threads = alice.get("/api/threads").json()["items"]
    alice_searches = alice.get("/api/searches").json()["items"]

    assert len(alice_threads) == 1
    assert len(alice_searches) == 1
    assert bob_threads == []
    assert bob_searches == []


def test_root_serves_static_shell(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    app = create_app()
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "AI Job Assistant Control Deck" in response.text
