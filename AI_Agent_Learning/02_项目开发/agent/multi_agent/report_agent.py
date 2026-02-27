import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

import report_generator
from .state import MultiAgentState


def make_report_node(output_dir: Path) -> Callable:
    def report_node(state: MultiAgentState) -> dict:
        print("\n[ReportAgent] 生成报告...", flush=True)
        profile = state["user_profile"]
        analyzed_jobs = state["analyzed_jobs"]
        learning_resources = state["learning_resources"]

        resource_map = {r["job_id"]: r for r in learning_resources}
        ranked_jobs = []
        for job in analyzed_jobs:
            res = resource_map.get(job["job_id"], {})
            ranked_jobs.append({
                **job,
                "repos": res.get("repos", []),
                "suggestions": res.get("suggestions", ""),
            })

        ranked_jobs.sort(key=lambda x: x.get("match", {}).get("score", 0), reverse=True)
        report_md = report_generator.generate_markdown(profile, ranked_jobs)

        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"report_multi_agent_{ts}.md"
        path.write_text(report_md, encoding="utf-8")

        print(f"[ReportAgent] 报告已生成：{path}", flush=True)
        return {"report_path": str(path)}

    return report_node
