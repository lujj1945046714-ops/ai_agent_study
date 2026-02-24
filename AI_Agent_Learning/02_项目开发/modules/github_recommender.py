from typing import Dict, List, Set


_REPO_CATALOG = [
    {
        "name": "langchain-ai/langchain",
        "url": "https://github.com/langchain-ai/langchain",
        "stars": 110000,
        "tags": {"python", "langchain", "agent", "rag"},
        "difficulty": "中",
        "time_estimate": "4-6天",
    },
    {
        "name": "run-llama/llama_index",
        "url": "https://github.com/run-llama/llama_index",
        "stars": 40000,
        "tags": {"python", "llamaindex", "rag", "vector-db"},
        "difficulty": "中",
        "time_estimate": "4-6天",
    },
    {
        "name": "microsoft/autogen",
        "url": "https://github.com/microsoft/autogen",
        "stars": 45000,
        "tags": {"python", "agent", "autogen", "react"},
        "difficulty": "中高",
        "time_estimate": "5-7天",
    },
    {
        "name": "langgenius/dify",
        "url": "https://github.com/langgenius/dify",
        "stars": 90000,
        "tags": {"agent", "workflow", "rag", "docker"},
        "difficulty": "高",
        "time_estimate": "7-10天",
    },
    {
        "name": "fastapi/fastapi",
        "url": "https://github.com/fastapi/fastapi",
        "stars": 85000,
        "tags": {"python", "fastapi", "api"},
        "difficulty": "低中",
        "time_estimate": "2-4天",
    },
]


def _norm(values: List[str]) -> Set[str]:
    return {v.strip().lower() for v in values if v and v.strip()}


def recommend_projects(skill_gaps: List[str], top_n: int = 3) -> List[Dict[str, str]]:
    gap_set = _norm(skill_gaps)
    ranked = []

    for repo in _REPO_CATALOG:
        overlap = len(gap_set.intersection(repo["tags"]))
        star_factor = min(repo["stars"] / 100000, 1.0)
        score = overlap * 0.75 + star_factor * 0.25
        ranked.append((score, overlap, repo))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]["stars"]), reverse=True)

    recommendations: List[Dict[str, str]] = []
    for _, overlap, repo in ranked[:top_n]:
        if overlap > 0:
            reason = f"可补齐技能缺口：{', '.join(sorted(gap_set.intersection(repo['tags'])))}"
        elif gap_set:
            reason = "与目标岗位相关，适合作为能力延展项目"
        else:
            reason = "与 Agent/LLM 求职方向匹配，适合作为简历项目"
        recommendations.append(
            {
                "name": repo["name"],
                "url": repo["url"],
                "stars": str(repo["stars"]),
                "reason": reason,
                "difficulty": repo["difficulty"],
                "time_estimate": repo["time_estimate"],
            }
        )
    return recommendations
