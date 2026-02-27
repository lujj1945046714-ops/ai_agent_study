import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

import config
from modules import fetch_jobs
from .state import MultiAgentState


def search_node(state: MultiAgentState) -> dict:
    print("\n[SearchAgent] 搜索职位...", flush=True)
    profile = state["user_profile"]

    jobs = fetch_jobs(profile, max_results=config.MAX_FETCH_JOBS)
    print(f"[SearchAgent] 找到 {len(jobs)} 个职位", flush=True)
    for j in jobs:
        print(f"  - {j['title']} @ {j['company']} ({j['city']})", flush=True)

    return {"raw_jobs": jobs}
