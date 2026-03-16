from __future__ import annotations

import json
from pathlib import Path

from job_assistant import config
from job_assistant.webapp.db import WebAppStore
from job_assistant.webapp.service import WebAppService


def _patch_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORKDIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "USER_OUTPUT_DIR", tmp_path / "output" / "users")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "jobs.db")
    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "data" / "app.db")


def test_first_user_migrates_legacy_profile_session_and_reports(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    config.ensure_dirs()

    legacy_profile = {
        "name": "旧用户",
        "skills": {"Python": {"level": 4, "years": 5}},
        "experience_years": 5,
        "target_roles": ["AI Agent 工程师"],
        "preferences": {"cities": ["上海"], "salary_min_k": 35, "salary_max_k": 55},
    }
    (config.PROFILES_DIR / "user_profile.json").write_text(
        json.dumps(legacy_profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (config.OUTPUT_DIR / "session_web_session.json").write_text(
        json.dumps(
            {
                "conversation_history": [
                    {
                        "user": "帮我分析岗位",
                        "agent": "这是旧会话里的回答",
                        "timestamp": "2026-03-14T12:00:00",
                        "metadata": {"source": "legacy"},
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (config.OUTPUT_DIR / "report_agent_20260314_120000.md").write_text(
        "# 历史报告\n\n这是旧版生成的报告。",
        encoding="utf-8",
    )

    store = WebAppStore(config.APP_DB_PATH)
    service = WebAppService(store)
    user = service.register_user("alice", "password123")

    profile = service.get_profile(user["id"])
    assert profile["name"] == "旧用户"

    threads = service.list_threads(user["id"])
    assert any(thread["id"] == "legacy_web_session" for thread in threads)

    thread = service.get_thread_detail(user["id"], "legacy_web_session")
    assert thread["messages"][0]["content"] == "帮我分析岗位"
    assert thread["messages"][1]["content"] == "这是旧会话里的回答"

    artifacts = service.list_artifacts(user["id"])
    assert any(item["kind"] == "report" for item in artifacts)
    assert store.get_meta("legacy_migrated_user_id") == str(user["id"])
