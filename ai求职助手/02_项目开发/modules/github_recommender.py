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


_PLAN_SEARCH_PROMPT = """你是一个 AI 学习规划专家。根据用户背景和技能缺口，制定 GitHub 项目搜索计划。

## 用户背景
- 经验阶段：{experience_level}
- 已掌握技能：{user_skills}
- 技能缺口：{skill_gaps}

## 目标岗位
- 核心职责：{core_work}
- 必备技能：{required_skills}

## 任务
1. 分析技能缺口的优先级（哪些是核心必备，哪些是加分项）
2. 制定学习路径（先学什么，再学什么，循序渐进）
3. 为每个学习阶段设计搜索策略（项目类型、关键词、优先级）

严格按以下 JSON 格式输出，不要有任何额外内容：
{{
  "learning_path": [
    "第一步：学习内容描述",
    "第二步：学习内容描述",
    "第三步：学习内容描述"
  ],
  "search_targets": [
    {{
      "stage": "第一步",
      "type": "tutorial/project/framework",
      "keywords": "英文搜索词（2-4个词）",
      "priority": 1,
      "reason": "为什么搜索这个"
    }},
    {{
      "stage": "第二步",
      "type": "tutorial/project/framework",
      "keywords": "英文搜索词（2-4个词）",
      "priority": 2,
      "reason": "为什么搜索这个"
    }}
  ],
  "estimated_api_calls": 6,
  "skip_search": false,
  "skip_reason": ""
}}

注意：
- search_targets 最多 3 个，避免浪费 API
- 如果用户技能已经很匹配（缺口很少），设置 skip_search=true 并说明原因
- priority 从 1 开始，数字越小优先级越高
"""


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


_REPLAN_PROMPT = """你是一个 GitHub 搜索专家。上一次搜索结果不理想，需要调整搜索策略。

## 上次搜索情况
- 搜索词：{previous_queries}
- 问题：{failure_reason}

## 用户背景
- 经验阶段：{experience_level}
- 已掌握技能：{user_skills}
- 技能缺口：{skill_gaps}

## 任务
分析失败原因，生成新的搜索策略（换角度、换关键词、调整难度）。

严格按以下 JSON 格式输出，不要有任何额外内容：
{{
  "new_queries": [
    {{"query": "新的英文搜索词（2-4个词）", "reason": "为什么换这个角度"}},
    {{"query": "新的英文搜索词（2-4个词）", "reason": "为什么换这个角度"}}
  ],
  "should_stop": false,
  "stop_reason": ""
}}

注意：
- new_queries 最多 2 个，避免浪费 API
- 如果判断无法找到合适项目（技能太冷门、要求太高等），设置 should_stop=true
"""


def _llm_generate_queries(skill_gaps: List[str], profile: Dict, analysis: Dict) -> List[Dict]:
    """
    让 LLM 生成多角度 GitHub 搜索策略。

    异常处理：
    - API 无法访问（网络/认证错误）→ 抛出异常
    - JSON 解析失败 → 返回空列表
    """
    from openai import OpenAI, APIConnectionError, AuthenticationError, APITimeoutError

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法生成搜索策略")

    try:
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

    except AuthenticationError as e:
        raise RuntimeError(f"API 认证失败，请检查 DEEPSEEK_API_KEY: {e}")
    except (APIConnectionError, APITimeoutError) as e:
        raise RuntimeError(f"无法连接到 DeepSeek API: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("搜索策略 JSON 解析失败，返回空列表: %s", e)
        return []
    except Exception as e:
        raise RuntimeError(f"生成搜索策略失败: {e}")


def _plan_search_strategy(skill_gaps: List[str], profile: Dict, analysis: Dict) -> Dict:
    """
    让 LLM 制定搜索计划，返回学习路径和搜索目标。

    异常处理：
    - API 无法访问（网络/认证错误）→ 抛出异常，不降级
    - JSON 解析失败 → 返回空规划，允许降级
    """
    from openai import OpenAI, APIError, APIConnectionError, AuthenticationError, APITimeoutError

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法进行搜索规划")

    try:
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

        user_skills: List[str] = []
        for skill_list in profile.get("skills", {}).values():
            user_skills.extend(skill_list)

        prompt = _PLAN_SEARCH_PROMPT.format(
            experience_level=profile.get("experience_level", "未知"),
            user_skills="、".join(user_skills[:8]) or "暂无",
            skill_gaps="、".join(skill_gaps[:5]) or "无明显缺口",
            core_work="、".join(analysis.get("core_work", [])[:3]) or "AI Agent 开发",
            required_skills="、".join(analysis.get("required_skills", [])[:5]) or "Python",
        )
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        result = json.loads(resp.choices[0].message.content)

        # 记录规划结果
        if result.get("skip_search"):
            logger.info("搜索规划：建议跳过搜索 - %s", result.get("skip_reason", "无理由"))
        else:
            logger.info("搜索规划：学习路径 %d 步，搜索目标 %d 个，预估 API 调用 %d 次",
                       len(result.get("learning_path", [])),
                       len(result.get("search_targets", [])),
                       result.get("estimated_api_calls", 0))

        return result

    except AuthenticationError as e:
        raise RuntimeError(f"API 认证失败，请检查 DEEPSEEK_API_KEY 配置: {e}")
    except (APIConnectionError, APITimeoutError) as e:
        raise RuntimeError(f"无法连接到 DeepSeek API，请检查网络或 DEEPSEEK_BASE_URL 配置: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("搜索规划 JSON 解析失败，返回空规划: %s", e)
        return {"skip_search": False, "search_targets": []}
    except Exception as e:
        # 其他未知错误也视为 API 问题，抛出异常
        raise RuntimeError(f"搜索规划失败: {e}")


def _llm_rerank(candidates: List[Dict], skill_gaps: List[str], profile: Dict, top_n: int) -> List[Dict]:
    """
    让 LLM 根据用户背景对候选项目重排序。

    异常处理：
    - API 无法访问（网络/认证错误）→ 抛出异常
    - JSON 解析失败 → 返回空列表
    """
    if not candidates:
        return []

    from openai import OpenAI, APIConnectionError, AuthenticationError, APITimeoutError

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法进行项目重排序")

    try:
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

    except AuthenticationError as e:
        raise RuntimeError(f"API 认证失败，请检查 DEEPSEEK_API_KEY: {e}")
    except (APIConnectionError, APITimeoutError) as e:
        raise RuntimeError(f"无法连接到 DeepSeek API: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("项目重排序 JSON 解析失败，返回空列表: %s", e)
        return []
    except Exception as e:
        raise RuntimeError(f"项目重排序失败: {e}")


def _check_search_quality(candidates: List[Dict], min_stars: int = 500) -> tuple[bool, str]:
    """
    检测搜索结果质量。

    返回：(is_good, failure_reason)
    - is_good: True 表示质量合格，False 表示需要重新搜索
    - failure_reason: 质量不合格的原因
    """
    if not candidates:
        return False, "搜索结果为空"

    if len(candidates) < 3:
        return False, f"搜索结果太少（只有 {len(candidates)} 个）"

    # 检查 star 数
    low_star_count = sum(1 for c in candidates if int(c.get("stars", 0)) < min_stars)
    if low_star_count > len(candidates) * 0.7:
        return False, f"大部分项目 star 数过低（{low_star_count}/{len(candidates)} 个低于 {min_stars}）"

    # 检查 description 是否为空
    no_desc_count = sum(1 for c in candidates if not c.get("description"))
    if no_desc_count > len(candidates) * 0.5:
        return False, f"大部分项目缺少描述（{no_desc_count}/{len(candidates)} 个无描述）"

    return True, ""


def _llm_replan_search(previous_queries: List[str], failure_reason: str, skill_gaps: List[str], profile: Dict) -> Dict:
    """
    让 LLM 根据失败原因重新规划搜索策略。

    返回：
    {
      "new_queries": [{"query": "...", "reason": "..."}],
      "should_stop": False,
      "stop_reason": ""
    }
    """
    from openai import OpenAI, APIConnectionError, AuthenticationError, APITimeoutError

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法重新规划搜索")

    try:
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

        user_skills: List[str] = []
        for skill_list in profile.get("skills", {}).values():
            user_skills.extend(skill_list)

        prompt = _REPLAN_PROMPT.format(
            previous_queries="、".join(previous_queries),
            failure_reason=failure_reason,
            experience_level=profile.get("experience_level", "未知"),
            user_skills="、".join(user_skills[:8]) or "暂无",
            skill_gaps="、".join(skill_gaps[:5]) or "无明显缺口",
        )
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        result = json.loads(resp.choices[0].message.content)

        if result.get("should_stop"):
            logger.info("重规划建议停止搜索：%s", result.get("stop_reason", ""))
        else:
            logger.info("重规划生成 %d 个新搜索策略", len(result.get("new_queries", [])))

        return result

    except AuthenticationError as e:
        raise RuntimeError(f"API 认证失败，请检查 DEEPSEEK_API_KEY: {e}")
    except (APIConnectionError, APITimeoutError) as e:
        raise RuntimeError(f"无法连接到 DeepSeek API: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("重规划 JSON 解析失败，返回空策略: %s", e)
        return {"new_queries": [], "should_stop": True, "stop_reason": "重规划失败"}
    except Exception as e:
        raise RuntimeError(f"重规划搜索失败: {e}")


def smart_recommend_projects(
    skill_gaps: List[str],
    profile: Dict = None,
    analysis: Dict = None,
    top_n: int = 3,
    user_choice: str = None,
    retry_context: Dict = None,
) -> Dict:
    """
    智能 GitHub 项目推荐（四步流程 + 交互式重规划）：
    0. 搜索前规划：LLM 分析用户背景，制定学习路径和搜索策略
    1. LLM 根据规划生成搜索关键词（如果规划建议跳过则直接返回本地目录）
    2. 用每个策略搜索 GitHub，合并去重
    3. 检测结果质量，不合格则询问用户是否重新规划
    4. LLM 根据用户背景重排序，返回最匹配的项目

    参数：
    - user_choice: 用户对重规划的选择（"replan" / "lower_stars" / "use_local"）
    - retry_context: 重试上下文（包含之前的搜索结果和查询历史）

    返回格式：
    {
      "status": "success" | "need_replan" | "failed",
      "repos": [...],  # status=success 时有值
      "replan_options": [  # status=need_replan 时有值
        {"value": "replan", "label": "换个角度重新搜索", "description": "..."},
        {"value": "lower_stars", "label": "降低 star 数要求", "description": "..."},
        {"value": "use_local", "label": "使用本地目录推荐", "description": "..."}
      ],
      "failure_reason": "...",
      "retry_context": {...}  # 用于下次调用
    }
    """
    profile = profile or {}
    analysis = analysis or {}

    # 恢复重试上下文
    if retry_context:
        all_candidates = retry_context.get("all_candidates", [])
        previous_queries = retry_context.get("previous_queries", [])
        attempt = retry_context.get("attempt", 0)
    else:
        all_candidates = []
        previous_queries = []
        attempt = 0

    # 处理用户选择
    if user_choice == "use_local":
        return {
            "status": "success",
            "repos": recommend_projects(skill_gaps, top_n=top_n)
        }
    elif user_choice == "lower_stars":
        # 降低 star 数要求，重新搜索
        min_stars = 100
        logger.info("用户选择降低 star 数要求到 %d", min_stars)
    else:
        min_stars = 500

    # Step 0: 搜索前规划（仅首次）
    if attempt == 0:
        plan = _plan_search_strategy(skill_gaps, profile, analysis)

        # 如果规划建议跳过搜索（用户技能已很匹配），直接返回本地目录
        if plan.get("skip_search"):
            logger.info("根据规划跳过 GitHub 搜索，使用本地目录")
            return {
                "status": "success",
                "repos": recommend_projects(skill_gaps, top_n=top_n)
            }

        # Step 1: 根据规划生成搜索词
        search_targets = plan.get("search_targets", [])
        if not search_targets:
            # 规划失败，降级到旧逻辑
            logger.info("搜索规划为空，降级到旧搜索逻辑")
            queries = _llm_generate_queries(skill_gaps, profile, analysis)
        else:
            # 使用规划的搜索目标，按优先级排序
            search_targets.sort(key=lambda x: x.get("priority", 999))
            queries = [{"query": t["keywords"], "angle": t.get("reason", "")} for t in search_targets]
            logger.info("使用规划的 %d 个搜索目标", len(queries))
    elif user_choice == "replan":
        # 用户选择重新规划
        logger.info("用户选择重新规划搜索策略")
        failure_reason = retry_context.get("failure_reason", "搜索结果不理想")
        replan = _llm_replan_search(previous_queries, failure_reason, skill_gaps, profile)

        if replan.get("should_stop"):
            logger.info("重规划建议停止搜索：%s", replan.get("stop_reason", ""))
            return {
                "status": "success",
                "repos": recommend_projects(skill_gaps, top_n=top_n)
            }

        queries = replan.get("new_queries", [])
        if not queries:
            logger.warning("重规划未生成新策略，使用本地目录")
            return {
                "status": "success",
                "repos": recommend_projects(skill_gaps, top_n=top_n)
            }
        logger.info("重规划生成 %d 个新搜索词", len(queries))
    else:
        # 不应该到这里
        queries = []

    # Step 2: 搜索 GitHub，合并去重
    seen_names: set = set(c["name"] for c in all_candidates)
    if queries:
        for q in queries:
            query_str = q.get("query", "")
            if not query_str:
                continue
            previous_queries.append(query_str)
            items = _search_github(query_str, min_stars=min_stars)
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

    # Step 3: 检测结果质量
    is_good, failure_reason = _check_search_quality(all_candidates, min_stars=min_stars)

    if not is_good:
        # 质量不合格，判断是否已重试过
        attempt += 1
        if attempt > 2:
            # 已重试 2 次，直接降级
            logger.warning("搜索重试 2 次后仍不合格，使用本地目录")
            return {
                "status": "success",
                "repos": recommend_projects(skill_gaps, top_n=top_n)
            }

        # 询问用户是否重新规划
        logger.warning("搜索结果不合格：%s，询问用户是否重新规划", failure_reason)
        return {
            "status": "need_replan",
            "replan_options": [
                {
                    "value": "replan",
                    "label": "换个角度重新搜索",
                    "description": f"当前问题：{failure_reason}。让 AI 换个搜索策略再试一次"
                },
                {
                    "value": "lower_stars",
                    "label": "降低 star 数要求（500 → 100）",
                    "description": "可能找到更多小众但实用的项目"
                },
                {
                    "value": "use_local",
                    "label": "使用本地目录推荐",
                    "description": "从预设的 5 个高质量项目中推荐"
                }
            ],
            "failure_reason": failure_reason,
            "retry_context": {
                "all_candidates": all_candidates,
                "previous_queries": previous_queries,
                "attempt": attempt
            }
        }

    # Step 4: LLM 重排序
    logger.info("搜索结果质量合格，共 %d 个候选项目", len(all_candidates))
    reranked = _llm_rerank(all_candidates, skill_gaps, profile, top_n)
    if reranked:
        logger.info("智能推荐成功，返回 %d 个项目", len(reranked))
        return {
            "status": "success",
            "repos": reranked
        }

    # 降级到本地目录
    logger.info("重排序失败，使用本地目录")
    return {
        "status": "success",
        "repos": recommend_projects(skill_gaps, top_n=top_n)
    }


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
