import json
import logging
import os
import sys
import time
from typing import Dict, List, Set

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)

# 24h 本地缓存文件
_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".github_cache.json")
_CACHE_TTL = 86400  # seconds


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


def _load_cache() -> dict:
    try:
        if os.path.exists(_CACHE_FILE):
            data = json.loads(open(_CACHE_FILE, encoding="utf-8").read())
            if time.time() - data.get("_ts", 0) < _CACHE_TTL:
                return data
    except Exception:
        pass
    return {}


def _save_cache(data: dict) -> None:
    try:
        data["_ts"] = time.time()
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("GitHub 缓存写入失败: %s", e)


def _get_proxies() -> dict:
    """读取系统代理或 config 中配置的代理。"""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or getattr(config, "HTTP_PROXY", "")
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def fetch_readme(repo_name: str) -> str:
    """拉取指定仓库的 README 内容，失败返回空字符串。"""
    cache = _load_cache()
    cache_key = f"readme:{repo_name}"
    if cache_key in cache:
        return cache[cache_key]

    url = f"https://api.github.com/repos/{repo_name}/readme"
    headers = {"Authorization": f"token {config.GITHUB_TOKEN}"} if config.GITHUB_TOKEN else {}
    headers["Accept"] = "application/vnd.github.raw"
    try:
        resp = requests.get(url, headers=headers, timeout=10, proxies=_get_proxies())
        resp.raise_for_status()
        content = resp.text[:3000]  # 截取前3000字符，避免超出 LLM context
        cache[cache_key] = content
        _save_cache(cache)
        return content
    except Exception as e:
        logger.warning("README 拉取失败 %s: %s", repo_name, e)
        return ""


def _search_github(query: str, min_stars: int = 1000) -> list:
    cache = _load_cache()
    cache_key = f"{query}:{min_stars}"
    if cache_key in cache:
        return cache[cache_key]

    url = "https://api.github.com/search/repositories"
    params = {"q": f"{query} topic:llm stars:>{min_stars}", "sort": "stars", "per_page": 5}
    headers = {"Authorization": f"token {config.GITHUB_TOKEN}"} if config.GITHUB_TOKEN else {}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5, proxies=_get_proxies())
        resp.raise_for_status()
        items = resp.json().get("items", [])
        cache[cache_key] = items
        _save_cache(cache)
        return items
    except Exception as e:
        logger.warning("GitHub API 请求失败，降级到本地目录: %s", e)
        return []


_QUERY_GEN_PROMPT = """你是一个 GitHub 项目搜索专家。根据以下求职信息，生成 3 个不同角度的 GitHub 搜索关键词。

## 用户背景
- 经验阶段：{experience_level}
- 已掌握技能：{user_skills}

## 目标岗位
- 核心职责：{core_work}
- 必备技能：{required_skills}
- 技能缺口：{skill_gaps}

## 要求
生成 3 个搜索策略，角度分别是：
1. 直接补齐技能缺口
2. 与岗位核心职责匹配
3. 适合用户当前水平快速上手

严格按以下 JSON 格式输出，不要有任何额外内容：
{{
  "queries": [
    {{"query": "英文搜索词（2-4个词）", "angle": "角度说明"}},
    {{"query": "英文搜索词（2-4个词）", "angle": "角度说明"}},
    {{"query": "英文搜索词（2-4个词）", "angle": "角度说明"}}
  ]
}}"""


_RERANK_PROMPT = """你是一个 AI 求职顾问。从候选 GitHub 项目中选出最适合该用户的 {top_n} 个，给出个性化推荐理由。

## 用户背景
- 经验阶段：{experience_level}
- 已掌握技能：{user_skills}
- 技能缺口：{skill_gaps}

## 候选项目列表
{candidates}

选出最适合的 {top_n} 个，综合考虑：技能缺口匹配度、项目难度与用户水平、简历含金量。

严格按以下 JSON 格式输出，不要有任何额外内容：
{{
  "selected": [
    {{
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "stars": "star数",
      "reason": "个性化推荐理由（结合用户背景，一句话）",
      "difficulty": "低/低中/中/中高/高",
      "time_estimate": "预计上手时间"
    }}
  ]
}}"""


def _llm_generate_queries(skill_gaps: List[str], profile: Dict, analysis: Dict) -> List[Dict]:
    """让 LLM 生成多角度 GitHub 搜索策略，失败返回空列表。"""
    try:
        from openai import OpenAI
        if not config.DEEPSEEK_API_KEY:
            return []
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

        user_skills: List[str] = []
        for skill_list in profile.get("skills", {}).values():
            user_skills.extend(skill_list)

        prompt = _QUERY_GEN_PROMPT.format(
            experience_level=profile.get("experience_level", "未知"),
            user_skills="、".join(user_skills[:8]) or "暂无",
            core_work="、".join(analysis.get("core_work", [])[:3]) or "AI Agent 开发",
            required_skills="、".join(analysis.get("required_skills", [])[:5]) or "Python",
            skill_gaps="、".join(skill_gaps[:5]) or "无明显缺口",
        )
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        result = json.loads(resp.choices[0].message.content)
        return result.get("queries", [])
    except Exception as e:
        logger.warning("LLM 生成搜索策略失败: %s", e)
        return []


def _llm_rerank(candidates: List[Dict], skill_gaps: List[str], profile: Dict, top_n: int) -> List[Dict]:
    """让 LLM 根据用户背景对候选项目重排序，失败返回空列表。"""
    if not candidates:
        return []
    try:
        from openai import OpenAI
        if not config.DEEPSEEK_API_KEY:
            return []
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

        user_skills: List[str] = []
        for skill_list in profile.get("skills", {}).values():
            user_skills.extend(skill_list)

        candidates_text = "\n".join(
            f"{i+1}. {c['name']} ({c.get('stars', '?')} stars) - {c.get('description', '无描述')}"
            for i, c in enumerate(candidates)
        )
        prompt = _RERANK_PROMPT.format(
            top_n=top_n,
            experience_level=profile.get("experience_level", "未知"),
            user_skills="、".join(user_skills[:8]) or "暂无",
            skill_gaps="、".join(skill_gaps[:5]) or "无明显缺口",
            candidates=candidates_text,
        )
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        result = json.loads(resp.choices[0].message.content)
        return result.get("selected", [])[:top_n]
    except Exception as e:
        logger.warning("LLM 重排序失败: %s", e)
        return []


def smart_recommend_projects(
    skill_gaps: List[str],
    profile: Dict = None,
    analysis: Dict = None,
    top_n: int = 3,
) -> List[Dict[str, str]]:
    """
    智能 GitHub 项目推荐（三步流程）：
    1. LLM 根据用户背景生成多角度搜索策略
    2. 用每个策略搜索 GitHub，合并去重
    3. LLM 根据用户背景重排序，返回最匹配的项目
    降级：GitHub API 不可用或 LLM 失败时，回退到本地目录关键词匹配。
    """
    profile = profile or {}
    analysis = analysis or {}

    # Step 1: LLM 生成搜索策略
    queries = _llm_generate_queries(skill_gaps, profile, analysis)

    # Step 2: 搜索 GitHub，合并去重
    all_candidates: List[Dict] = []
    seen_names: set = set()
    if queries:
        for q in queries:
            query_str = q.get("query", "")
            if not query_str:
                continue
            items = _search_github(query_str, min_stars=500)
            for item in items:
                name = item.get("full_name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    all_candidates.append({
                        "name": name,
                        "url": item.get("html_url", f"https://github.com/{name}"),
                        "stars": str(item.get("stargazers_count", 0)),
                        "description": item.get("description", "") or "",
                    })

    # Step 3: LLM 重排序
    if all_candidates:
        reranked = _llm_rerank(all_candidates, skill_gaps, profile, top_n)
        if reranked:
            logger.info("智能推荐成功，返回 %d 个项目", len(reranked))
            return reranked

    # 降级到本地目录
    logger.info("智能推荐降级到本地目录")
    return recommend_projects(skill_gaps, top_n=top_n)


def recommend_projects(skill_gaps: List[str], top_n: int = 3) -> List[Dict[str, str]]:
    gap_set = _norm(skill_gaps)

    # Try GitHub API first
    if gap_set:
        query = " ".join(list(gap_set)[:3])
        api_items = _search_github(query)
        if api_items:
            results = []
            for item in api_items[:top_n]:
                results.append({
                    "name": item["full_name"],
                    "url": item["html_url"],
                    "stars": str(item["stargazers_count"]),
                    "reason": f"GitHub 动态搜索：与技能缺口「{', '.join(list(gap_set)[:3])}」相关",
                    "difficulty": "中",
                    "time_estimate": "视项目规模而定",
                })
            return results

    # Fallback to local catalog
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
        recommendations.append({
            "name": repo["name"],
            "url": repo["url"],
            "stars": str(repo["stars"]),
            "reason": reason,
            "difficulty": repo["difficulty"],
            "time_estimate": repo["time_estimate"],
        })
    return recommendations
