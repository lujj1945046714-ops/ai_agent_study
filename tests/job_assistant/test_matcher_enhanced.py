from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _import_matcher():
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    import job_assistant.modules.matcher_enhanced as matcher_enhanced
    return matcher_enhanced


def test_score_is_clamped_to_100(monkeypatch):
    me = _import_matcher()
    monkeypatch.setattr(me, "has_llm_configured", lambda: False)
    monkeypatch.setattr(me, "_get_st_model", lambda: None)

    profile = {
        "skills": {
            "Python": {"level": 5, "years": 10},
            "LangChain": {"level": 5, "years": 5},
            "RAG": {"level": 5, "years": 3},
            "FastAPI": {"level": 5, "years": 3},
            "Docker": {"level": 5, "years": 3},
        },
        "experience_years": 10,
    }
    analysis = {
        "required_skills": ["Python", "LangChain", "RAG"],
        "tech_stack": ["FastAPI", "Docker"],
        "nice_to_have": ["Redis"],
        "job_level": "中级",
    }

    result = me.match_job_enhanced(profile, analysis)

    assert 0 <= result["score"] <= 100
    assert "score_breakdown" in result


def test_soft_gate_penalizes_missing_required_but_not_zero(monkeypatch):
    me = _import_matcher()
    monkeypatch.setattr(me, "has_llm_configured", lambda: False)
    monkeypatch.setattr(me, "_get_st_model", lambda: None)

    analysis = {
        "required_skills": ["Python", "RAG"],
        "tech_stack": [],
        "nice_to_have": [],
        "job_level": "中级",
    }
    profile_full = {
        "skills": {
            "Python": {"level": 3, "years": 2},
            "RAG": {"level": 3, "years": 1},
        },
        "experience_years": 3,
    }
    profile_missing = {
        "skills": {
            "Python": {"level": 3, "years": 2},
        },
        "experience_years": 3,
    }

    full = me.match_job_enhanced(profile_full, analysis)
    missing = me.match_job_enhanced(profile_missing, analysis)

    assert full["score"] > missing["score"]
    assert missing["score"] > 0


def test_fuzzy_matching_used_when_semantic_unavailable(monkeypatch):
    me = _import_matcher()
    monkeypatch.setattr(me, "has_llm_configured", lambda: False)
    monkeypatch.setattr(me, "_get_st_model", lambda: None)

    profile = {
        "skills": {
            "Postgres": {"level": 2, "years": 1},
        },
        "experience_years": 2,
    }
    analysis = {
        "required_skills": [],
        "tech_stack": ["PostgreSQL"],
        "nice_to_have": [],
        "job_level": "中级",
    }

    result = me.match_job_enhanced(profile, analysis)

    assert "PostgreSQL" in result["matched_skills"]
    detail = next(d for d in result["matched_skills_detailed"] if d["skill"] == "PostgreSQL")
    assert detail["match_type"] == "fuzzy"
    assert detail["similarity"] >= me.FUZZY_THRESHOLD["tech_stack"]


def test_breakdown_and_gap_fields_present(monkeypatch):
    me = _import_matcher()
    monkeypatch.setattr(me, "has_llm_configured", lambda: False)
    monkeypatch.setattr(me, "_get_st_model", lambda: None)

    profile = {
        "skills": {
            "Python": {"level": 2, "years": 1},
        },
        "experience_years": 1,
    }
    analysis = {
        "required_skills": ["Python"],
        "tech_stack": [],
        "nice_to_have": [],
        "job_level": "中级",
    }

    result = me.match_job_enhanced(profile, analysis)

    breakdown = result["score_breakdown"]
    assert "required_skills" in breakdown
    assert "base" in breakdown and "gate" in breakdown and "raw_score" in breakdown

    assert result["skill_gaps_detailed"]
    gap = result["skill_gaps_detailed"][0]
    assert {"skill", "required_level", "user_level", "gap_desc", "category"} <= set(gap.keys())


def test_llm_match_path_used_when_llm_available(monkeypatch):
    me = _import_matcher()
    monkeypatch.setattr(me, "has_llm_configured", lambda: True)
    monkeypatch.setattr(
        me,
        "complete_json_flexible",
        lambda *args, **kwargs: {
            "score": 91,
            "skill_gaps": ["Docker"],
            "skill_gaps_detailed": [{"skill":"Docker","required_level":2,"user_level":0,"gap_desc":"缺少工程化容器经验","category":"tech_stack"}],
            "matched_skills": ["Python","LangChain"],
            "matched_skills_detailed": [{"skill":"Python","user_skill":"Python","user_level":4,"match_quality":"完全匹配","category":"必备技能"}],
            "match_reasons": ["核心技能覆盖较好","具备相关项目经验","岗位级别匹配"],
            "score_breakdown": {
                "required_skills": {"coverage": 1.0, "avg_skill_score": 0.9, "weight": 0.6, "matched_count": 2, "total_count": 2},
                "tech_stack": {"coverage": 0.5, "avg_skill_score": 0.4, "weight": 0.3, "matched_count": 1, "total_count": 2},
                "nice_to_have": {"coverage": 0.0, "avg_skill_score": 0.0, "weight": 0.1, "matched_count": 0, "total_count": 0},
                "base": 0.82,
                "gate": 1.0,
                "raw_score": 91,
                "exp_adjust": 0,
            },
        },
    )

    profile = {
        "skills": {
            "Python": {"level": 4, "years": 3},
            "LangChain": {"level": 3, "years": 2},
        },
        "experience_years": 3,
    }
    analysis = {
        "required_skills": ["Python", "LangChain"],
        "tech_stack": ["Docker"],
        "nice_to_have": [],
        "job_level": "中级",
    }

    result = me.match_job_enhanced(profile, analysis)

    assert result["score"] == 91
    assert result["skill_gaps"] == ["Docker"]
    assert result["matched_skills"][:2] == ["Python", "LangChain"]


def test_llm_match_does_not_silently_fall_back_to_rules(monkeypatch):
    me = _import_matcher()
    monkeypatch.setattr(me, "has_llm_configured", lambda: True)
    monkeypatch.setattr(
        me,
        "complete_json_flexible",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("llm failed")),
    )

    with pytest.raises(RuntimeError, match="llm failed"):
        me.match_job_enhanced({"skills": {}}, {"required_skills": [], "tech_stack": [], "nice_to_have": []})
