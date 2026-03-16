from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from job_assistant import config
from job_assistant.modules.github_recommender import recommend_projects, smart_recommend_projects
from job_assistant.repo_audit import audit_repository


def _fixture_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "repo_audit" / name


def _patch_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORKDIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "jobs.db")


def test_audit_python_repo_runs_and_cleans(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)

    result = audit_repository(
        str(_fixture_dir("python_agent")),
        expected_capabilities=["agent", "cli"],
        allow_light_run=True,
        keep_workspace=False,
    )

    assert result["verdict"] in {"strong_match", "partial_match"}
    assert result["run_summary"]["status"] == "passed"
    assert any(module["path"] == "src/python_agent" for module in result["usable_modules"])
    assert Path(result["artifacts"]["audit_json"]).exists()
    assert Path(result["artifacts"]["audit_md"]).exists()
    assert Path(result["artifacts"]["trace_jsonl"]).exists()
    assert not Path(result["workspace"]["workspace_root"]).exists()
    assert result["cleanup"]["performed"] is True


def test_audit_node_repo_reports_modules(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)

    result = audit_repository(
        str(_fixture_dir("node_agent")),
        expected_capabilities=["agent", "cli", "search"],
        allow_light_run=True,
        keep_workspace=False,
    )

    assert "JavaScript" in result["static_analysis"]["primary_languages"]
    assert any("src/modules" in module["path"] or module["path"] == "index.js" for module in result["usable_modules"])
    assert result["run_summary"]["status"] in {"passed", "skipped"}
    if shutil.which("node"):
        assert result["run_summary"]["status"] == "passed"


def test_keep_workspace_preserves_downloaded_repo(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)

    result = audit_repository(
        str(_fixture_dir("static_docs")),
        expected_capabilities=["workflow", "agent"],
        allow_light_run=False,
        keep_workspace=True,
    )

    assert result["cleanup"]["performed"] is False
    assert Path(result["workspace"]["workspace_root"]).exists()
    assert Path(result["artifacts"]["audit_json"]).exists()


def test_smart_recommend_projects_can_attach_audit(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)

    fixture_repo = str(_fixture_dir("python_agent"))

    def fake_recommend_projects(skill_gaps, top_n=3, profile=None):
        return [
            {
                "name": "fixture/python_agent",
                "url": fixture_repo,
                "stars": "1",
                "reason": "fixture",
                "difficulty": "低",
                "time_estimate": "10分钟",
            }
        ]

    monkeypatch.setattr(
        "job_assistant.modules.github_recommender.recommend_projects",
        fake_recommend_projects,
    )

    result = smart_recommend_projects(
        ["agent"],
        profile={},
        analysis={},
        top_n=1,
        user_choice="use_local",
        audit_top_repo=True,
        audit_expected_capabilities=["agent", "cli"],
        audit_allow_light_run=True,
        audit_keep_workspace=False,
    )

    assert result["status"] == "success"
    assert "audit_summary" in result["repos"][0]
    assert result["repos"][0]["audit_summary"]["verdict"] in {"strong_match", "partial_match"}


def test_recommend_projects_can_use_llm_scoring(monkeypatch):
    captured = {}

    monkeypatch.setattr("job_assistant.modules.github_recommender.has_llm_configured", lambda: True)
    monkeypatch.setattr("job_assistant.modules.github_recommender._search_github", lambda query: [])

    def fake_rerank(candidates, skill_gaps, profile, top_n):
        captured["candidate_count"] = len(candidates)
        return [
            {
                "name": "microsoft/autogen",
                "url": "https://github.com/microsoft/autogen",
                "stars": "45000",
                "fit_score": 93,
                "reason": "更符合当前用户背景",
                "difficulty": "中高",
                "time_estimate": "5-7天",
            }
        ]

    monkeypatch.setattr(
        "job_assistant.modules.github_recommender._llm_rerank",
        fake_rerank,
    )

    repos = recommend_projects(
        ["agent", "python"],
        top_n=1,
        profile={"skills": {"Python": {"level": 3, "years": 2}}, "experience_level": "中级"},
    )

    assert repos[0]["name"] == "microsoft/autogen"
    assert repos[0]["fit_score"] == 93
    assert captured["candidate_count"] == 5


def test_recommend_projects_raises_when_llm_scoring_returns_empty(monkeypatch):
    monkeypatch.setattr("job_assistant.modules.github_recommender.has_llm_configured", lambda: True)
    monkeypatch.setattr("job_assistant.modules.github_recommender._search_github", lambda query: [])
    monkeypatch.setattr("job_assistant.modules.github_recommender._llm_rerank", lambda *args, **kwargs: [])

    with pytest.raises(RuntimeError, match="LLM 项目评分失败"):
        recommend_projects(
            ["agent", "python"],
            top_n=1,
            profile={"skills": {"Python": {"level": 3, "years": 2}}, "experience_level": "中级"},
        )


def test_recommend_projects_reranks_github_api_results_when_llm_available(monkeypatch):
    captured = {}
    monkeypatch.setattr("job_assistant.modules.github_recommender.has_llm_configured", lambda: True)
    monkeypatch.setattr(
        "job_assistant.modules.github_recommender._search_github",
        lambda query: [
            {
                "full_name": "openai/openai-agents-python",
                "html_url": "https://github.com/openai/openai-agents-python",
                "stargazers_count": 12345,
                "description": "Agents SDK",
            }
        ],
    )

    def fake_rerank(candidates, skill_gaps, profile, top_n):
        captured["candidates"] = candidates
        return [
            {
                "name": "openai/openai-agents-python",
                "url": "https://github.com/openai/openai-agents-python",
                "stars": "12345",
                "fit_score": 96,
                "reason": "直接匹配 Agent 能力栈",
                "difficulty": "中",
                "time_estimate": "3-5天",
            }
        ]

    monkeypatch.setattr("job_assistant.modules.github_recommender._llm_rerank", fake_rerank)

    repos = recommend_projects(
        ["agent", "python"],
        top_n=1,
        profile={"skills": {"Python": {"level": 3, "years": 2}}, "experience_level": "中级"},
    )

    assert captured["candidates"][0]["name"] == "openai/openai-agents-python"
    assert repos[0]["fit_score"] == 96
