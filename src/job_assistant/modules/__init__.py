from job_assistant.modules.analyzer import analyze_jd
from job_assistant.modules.github_recommender import (
    audit_repository,
    fetch_readme,
    recommend_projects,
    smart_recommend_projects,
)
from job_assistant.modules.matcher_enhanced import match_job_enhanced as match_job
from job_assistant.modules.scraper import fetch_jobs
from job_assistant.modules.suggestion import generate_suggestions

__all__ = [
    "analyze_jd",
    "audit_repository",
    "fetch_jobs",
    "fetch_readme",
    "generate_suggestions",
    "match_job",
    "recommend_projects",
    "smart_recommend_projects",
]
