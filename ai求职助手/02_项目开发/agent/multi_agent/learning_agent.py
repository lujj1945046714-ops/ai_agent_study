import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

import config
from modules import generate_suggestions, recommend_projects
from .state import MultiAgentState


def learning_node(state: MultiAgentState) -> dict:
    print("\n[LearningAgent] 推荐学习资源...", flush=True)
    analyzed_jobs = state["analyzed_jobs"]

    # 汇总所有技能缺口（去重保序）
    seen: set = set()
    all_gaps = []
    for job in analyzed_jobs:
        for gap in job.get("match", {}).get("skill_gaps", []):
            if gap not in seen:
                seen.add(gap)
                all_gaps.append(gap)

    repos = recommend_projects(all_gaps, top_n=config.GITHUB_TOP_N)
    print(f"[LearningAgent] 推荐 {len(repos)} 个学习项目", flush=True)

    resources = []
    for job in analyzed_jobs:
        gaps = job.get("match", {}).get("skill_gaps", [])
        suggestions = generate_suggestions(job.get("analysis", {}), repos, gaps)
        resources.append({
            "job_id": job["job_id"],
            "skill_gaps": gaps,
            "repos": repos,
            "suggestions": suggestions,
        })

    return {"learning_resources": resources}
