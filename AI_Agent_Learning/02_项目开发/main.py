import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import config
import database
import report_generator
from modules import analyze_jd, fetch_jobs, generate_suggestions, match_job, recommend_projects

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def load_user_profile(profile_path: str) -> Dict[str, Any]:
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _rank_jobs(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(records, key=lambda item: item.get("match", {}).get("score", 0), reverse=True)


def run() -> str:
    base_dir = Path(__file__).resolve().parent
    profile_path = base_dir / "user_profile.json"
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    profile = load_user_profile(str(profile_path))
    db_path = str(base_dir / config.DB_PATH)
    database.init_db(db_path)

    raw_jobs = fetch_jobs(profile, max_results=config.MAX_FETCH_JOBS)
    database.save_raw_jobs(db_path, raw_jobs)

    coarse_jobs = database.list_unanalyzed_jobs(db_path, limit=config.MAX_COARSE_FILTER)
    deep_jobs = coarse_jobs[: config.MAX_DEEP_ANALYSIS]

    for job in deep_jobs:
        analysis = analyze_jd(job["jd_text"])
        match = match_job(profile, analysis)
        repos = recommend_projects(match.get("skill_gaps", []), top_n=config.GITHUB_TOP_N)
        suggestions = generate_suggestions(analysis, repos, match.get("skill_gaps", []))
        database.save_enrichment(db_path, job["job_id"], analysis, match, repos, suggestions)

    ranked = _rank_jobs(database.list_enriched_jobs(db_path, limit=config.MAX_COARSE_FILTER))
    report = report_generator.generate_markdown(profile, ranked)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"report_{ts}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    return str(report_path)


def run_agent(task: str = "帮我分析当前市场上适合我的 AI Agent 工程师职位") -> str:
    """
    Agent 模式入口：使用 ReAct 循环，LLM 自主决定工具调用顺序。
    与 run() 的区别：
      - run()       线性 Pipeline，顺序固定
      - run_agent() LLM 驱动，可动态跳过低分职位、自主决定何时生成报告
    """
    from agent.react_agent import JobSearchAgent

    base_dir = Path(__file__).resolve().parent
    profile = load_user_profile(str(base_dir / "user_profile.json"))
    output_dir = base_dir / "output"

    agent = JobSearchAgent(
        user_profile=profile,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        model=config.DEEPSEEK_MODEL,
        output_dir=output_dir,
    )

    summary = agent.run(task)
    print("\n── Agent 总结 ──")
    print(summary)
    return summary


if __name__ == "__main__":
    import sys
    if "--agent" in sys.argv:
        run_agent()
    else:
        path = run()
        print(f"分析完成，报告已生成：{path}")
