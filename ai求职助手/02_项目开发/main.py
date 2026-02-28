import json
import logging
from pathlib import Path
from typing import Any, Dict

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def load_user_profile(profile_path: str) -> Dict[str, Any]:
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)



def run_agent(task: str = "帮我分析当前市场上适合我的 AI Agent 工程师职位") -> str:
    """
    Agent 模式入口：使用 ReAct 循环，LLM 自主决定工具调用顺序。
    支持交互式用户画像引导 + JD 粘贴解析。
    """
    from openai import OpenAI
    from agent.react_agent import JobSearchAgent
    from onboarding import get_or_create_profile
    from modules.scraper import parse_jd_input

    base_dir = Path(__file__).resolve().parent
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    llm_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

    # 1. 获取或创建用户画像
    _name, profile = get_or_create_profile(llm_client, config.DEEPSEEK_MODEL)

    # 2. 解析用户粘贴的 JD
    jobs = parse_jd_input(llm_client, config.DEEPSEEK_MODEL)

    # 3. 构建 Agent
    agent = JobSearchAgent(
        user_profile=profile,
        name=_name,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        model=config.DEEPSEEK_MODEL,
        output_dir=output_dir,
    )

    # 4. 若有粘贴 JD，预加载；否则 agent 自行 search_jobs
    if jobs:
        agent.preload_jobs(jobs)

    summary = agent.run(task)
    print("\n── Agent 总结 ──")
    print(summary)
    return summary


if __name__ == "__main__":
    run_agent()

