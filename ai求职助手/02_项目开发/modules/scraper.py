from typing import Any, Dict, List


_MOCK_JOBS = [
    {
        "job_id": "boss-ai-agent-001",
        "title": "AI Agent 工程师",
        "company": "星河科技",
        "city": "上海",
        "salary": "25-40k",
        "jd_text": """
岗位职责：
- 负责基于 LLM 的 Agent 工作流设计与开发
- 设计并实现多 Agent 协作与任务编排能力
- 优化工具调用链路并持续监控效果
任职要求：
- 熟练掌握 Python，具备工程化开发经验
- 熟悉 LangChain 或 LlamaIndex
- 有 Prompt Engineering 实战经验
- 有 RAG 或 ReAct 实践经验优先
""",
    },
    {
        "job_id": "boss-llm-app-002",
        "title": "LLM 应用开发工程师",
        "company": "蓝海智能",
        "city": "北京",
        "salary": "22-35k",
        "jd_text": """
岗位职责：
- 开发企业内部 AI 助手，落地知识检索与问答系统
- 优化大模型调用成本和响应延迟
任职要求：
- 精通 Python / FastAPI
- 熟悉 RAG、向量数据库
- 熟悉 SQL 与数据建模
- 有开源项目经验加分
""",
    },
    {
        "job_id": "boss-agent-platform-003",
        "title": "Agent 平台工程师",
        "company": "未来引擎",
        "city": "深圳",
        "salary": "28-45k",
        "jd_text": """
岗位职责：
- 搭建 Agent 平台，支持任务规划、执行、回溯
- 维护模型服务和任务调度系统
任职要求：
- Python 基础扎实
- 熟悉 AutoGen / LangGraph / ReAct
- 熟悉 Docker、Redis、SQL
- 3年以上相关经验
""",
    },
    {
        "job_id": "boss-junior-agent-004",
        "title": "初级 AI 工程师（Agent方向）",
        "company": "起跑线科技",
        "city": "上海",
        "salary": "15-22k",
        "jd_text": """
岗位职责：
- 参与 AI Agent 系统开发与测试
- 根据业务需求开发工具调用插件
任职要求：
- 熟悉 Python，了解 LLM API 调用
- 了解 Prompt 编写
- 有 GitHub 项目经验优先，应届可投
""",
    },
    {
        "job_id": "boss-data-ai-005",
        "title": "数据智能工程师（LLM）",
        "company": "云图数据",
        "city": "杭州",
        "salary": "20-30k",
        "jd_text": """
岗位职责：
- 建设行业数据问答系统
- 负责模型效果评估与迭代
任职要求：
- Python、SQL、FastAPI
- RAG 项目经验
- 了解向量数据库
""",
    },
]


def _salary_overlap(salary_text: str, min_k: int, max_k: int) -> bool:
    salary_text = salary_text.lower().replace("k", "")
    if "-" not in salary_text:
        return True
    low, high = salary_text.split("-", 1)
    try:
        low_v = int(low.strip())
        high_v = int(high.strip())
    except ValueError:
        return True
    return not (high_v < min_k or low_v > max_k)


def fetch_jobs_from_input() -> List[Dict[str, Any]]:
    """交互式让用户手动粘贴 JD 文本，返回 job list。"""
    jobs = []
    print("\n=== 手动输入职位信息模式 ===")
    print("请逐个输入职位信息，输入完成后选择结束。\n")

    while True:
        idx = len(jobs) + 1
        print(f"--- 职位 {idx} ---")
        title = input("职位名称: ").strip()
        company = input("公司名称: ").strip()
        city = input("城市: ").strip()
        salary = input("薪资范围（如 25-35k）: ").strip()
        print("JD 文本（多行，输入 --- 单独一行结束）:")
        jd_lines = []
        while True:
            line = input()
            if line.strip() == "---":
                break
            jd_lines.append(line)
        jd_text = "\n".join(jd_lines)

        jobs.append({
            "job_id": f"manual-{idx:03d}",
            "title": title,
            "company": company,
            "city": city,
            "salary": salary,
            "jd_text": jd_text,
        })
        print(f"[已添加] {title} @ {company}\n")

        cont = input("继续添加下一个职位？(y/n): ").strip().lower()
        if cont != "y":
            break

    print(f"\n共输入 {len(jobs)} 个职位，开始分析...\n")
    return jobs


def fetch_jobs(profile: Dict[str, Any], max_results: int = 30, use_boss: bool = False) -> List[Dict[str, Any]]:
    """
    获取职位列表。
    use_boss=True 时进入手动输入模式。
    use_boss=False（默认）使用 Mock 数据。
    """
    if use_boss:
        return fetch_jobs_from_input()

    # Mock 数据过滤逻辑
    prefs = profile.get("preferences", {})
    cities = set(prefs.get("cities", []))
    salary_min = int(prefs.get("salary_min_k", 0))
    salary_max = int(prefs.get("salary_max_k", 999))
    keywords = [k.lower() for k in profile.get("target_roles", [])]

    selected: List[Dict[str, Any]] = []
    for job in _MOCK_JOBS:
        if cities and job["city"] not in cities:
            continue
        if not _salary_overlap(job["salary"], salary_min, salary_max):
            continue
        haystack = f"{job['title']} {job['jd_text']}".lower()
        if keywords and not any(keyword in haystack for keyword in keywords):
            continue
        selected.append(job)
        if len(selected) >= max_results:
            break

    if not selected:
        return _MOCK_JOBS[: min(len(_MOCK_JOBS), max_results)]
    return selected

