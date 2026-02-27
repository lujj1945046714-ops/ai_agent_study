import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

import config
from modules import analyze_jd, match_job
from .state import MultiAgentState


def analysis_node(state: MultiAgentState) -> dict:
    print("\n[AnalysisAgent] 分析职位...", flush=True)
    profile = state["user_profile"]
    raw_jobs = state["raw_jobs"]

    jobs_to_analyze = raw_jobs[: config.MAX_DEEP_ANALYSIS]
    analyzed = []

    for job in jobs_to_analyze:
        analysis = analyze_jd(job["jd_text"])
        match = match_job(profile, analysis)
        analyzed.append({**job, "analysis": analysis, "match": match})
        score = match.get("score", 0)
        print(f"  - {job['title']} @ {job['company']}: {score}分", flush=True)

    return {"analyzed_jobs": analyzed}
