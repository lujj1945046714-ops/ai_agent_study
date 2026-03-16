"""
Enhanced skill matching with proficiency levels.

新增功能：
1. 技能熟练度等级（0-5）
2. 动态语义匹配阈值
3. 向后兼容旧格式用户画像
4. 语义匹配不可用时的模糊匹配降级
5. 输出可解释的分项评分
"""
from typing import Any, Dict, List, Tuple
from functools import lru_cache
import difflib
import json
import re

from job_assistant.llm_runtime import complete_json_flexible, has_llm_configured

# 技能熟练度定义
SKILL_PROFICIENCY = {
    0: "未接触",
    1: "了解概念",      # 看过文档，知道是什么
    2: "基础使用",      # 跑过 demo，写过简单代码
    3: "熟练掌握",      # 独立完成项目，理解原理
    4: "深度实践",      # 解决过复杂问题，有最佳实践
    5: "专家级别"       # 贡献开源，深入源码，能讲课
}

# 岗位技能要求等级
JOB_REQUIREMENT_LEVEL = {
    "required_skills": {
        "min_level": 3,      # 必备技能至少要熟练掌握
        "weight": 0.6,
        "threshold": 0.80    # 语义匹配阈值（严格）
    },
    "tech_stack": {
        "min_level": 2,      # 技术栈至少要基础使用
        "weight": 0.3,
        "threshold": 0.75    # 语义匹配阈值（中等）
    },
    "nice_to_have": {
        "min_level": 1,      # 加分项了解即可
        "weight": 0.1,
        "threshold": 0.70    # 语义匹配阈值（宽松）
    }
}

FUZZY_THRESHOLD = {
    "required_skills": 0.88,
    "tech_stack": 0.84,
    "nice_to_have": 0.80,
}

_st_model = None

_LLM_MATCH_PROMPT = """你是资深 AI 求职顾问。请基于用户画像与岗位分析，给出灵活但可解释的匹配评估。

要求：
1. 综合考虑技能覆盖、熟练度、项目经历、岗位级别、经验年限
2. score 为 0-100 的整数
3. matched_skills 写用户已覆盖且对岗位有帮助的关键技能
4. skill_gaps 写最关键的 1-6 个缺口
5. 所有字段必须存在；没有内容时返回空数组或空字符串
6. 只返回 JSON，不要 markdown，不要解释

JSON 结构：
{
  "score": 0,
  "skill_gaps": ["缺口1"],
  "skill_gaps_detailed": [
    {
      "skill": "技能名",
      "required_level": 3,
      "user_level": 1,
      "gap_desc": "差距描述",
      "category": "required_skills"
    }
  ],
  "matched_skills": ["技能1"],
  "matched_skills_detailed": [
    {
      "skill": "岗位技能",
      "user_skill": "用户技能",
      "user_level": 3,
      "match_quality": "完全匹配",
      "category": "必备技能"
    }
  ],
  "match_reasons": ["原因1", "原因2", "原因3"],
  "score_breakdown": {
    "required_skills": {"coverage": 0.0, "avg_skill_score": 0.0, "weight": 0.0, "matched_count": 0, "total_count": 0},
    "tech_stack": {"coverage": 0.0, "avg_skill_score": 0.0, "weight": 0.0, "matched_count": 0, "total_count": 0},
    "nice_to_have": {"coverage": 0.0, "avg_skill_score": 0.0, "weight": 0.0, "matched_count": 0, "total_count": 0},
    "base": 0.0,
    "gate": 0.0,
    "raw_score": 0.0,
    "exp_adjust": 0
  }
}
"""


def _get_st_model():
    global _st_model
    if _st_model is not None:
        return _st_model
    try:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        return _st_model
    except Exception:
        return None


@lru_cache(maxsize=256)
def _encode(text: str):
    model = _get_st_model()
    if model is None:
        return None
    return model.encode(text, convert_to_tensor=True)


def _semantic_match(user_skill: str, required_skill: str, threshold: float = 0.75) -> bool:
    """语义匹配，支持动态阈值"""
    from sentence_transformers import util
    u = _encode(user_skill)
    r = _encode(required_skill)
    if u is None or r is None:
        return False
    return float(util.cos_sim(u, r)) >= threshold


# 技能同义词映射（保持向后兼容）
_SYNONYM = {
    "llm api调用": "llm",
    "llm api": "llm",
    "llm": "llm",
    "大模型": "llm",
    "prompt engineering": "prompt",
    "提示词工程": "prompt",
    "prompt工程": "prompt",
    "prompt": "prompt",
    "检索增强生成": "rag",
    "retrieval augmented generation": "rag",
    "rag": "rag",
    "rag项目深度分析": "rag",
    "向量数据库": "vector-db",
    "向量库": "vector-db",
    "vector db": "vector-db",
    "vectordb": "vector-db",
    "vector database": "vector-db",
    "langchain": "langchain",
    "lang chain": "langchain",
    "llamaindex": "llamaindex",
    "autogen": "autogen",
    "python": "python",
    "fastapi": "fastapi",
    "sql": "sql",
    "git": "git",
    "agent": "agent",
    "re-act": "react",
    "re act": "react",
    "react": "react",
}


def _norm(skill: str) -> str:
    """标准化技能名称"""
    key = skill.strip().lower()
    return _SYNONYM.get(key, key)


def _raw_compare_key(skill: str) -> str:
    """用于“近似精确匹配”的比较 key：忽略大小写与常见分隔符。"""
    s = skill.strip().lower()
    s = re.sub(r"[\s\-_./]+", "", s)
    return s


def _compare_key(skill: str) -> str:
    """用于模糊匹配的比较 key：先做同义词归一化，再移除分隔符。"""
    s = _norm(skill)
    s = re.sub(r"[\s\-_./]+", "", s)
    s = re.sub(r"[()（）\[\]{}]+", "", s)
    return s.strip().lower()


def _fuzzy_similarity(a: str, b: str) -> float:
    """模糊相似度（0-1），在语义模型不可用时作为降级方案。"""
    a_key = _compare_key(a)
    b_key = _compare_key(b)
    if not a_key or not b_key:
        return 0.0
    return difflib.SequenceMatcher(None, a_key, b_key).ratio()


def normalize_user_skills(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    标准化用户技能格式，支持新旧两种格式。

    旧格式:
    {
      "skills": {
        "core": ["Python", "LangChain"],
        "tools": ["Git"]
      }
    }

    新格式:
    {
      "skills": {
        "Python": {"level": 3, "years": 2},
        "LangChain": {"level": 2, "years": 0.5}
      }
    }

    返回统一的新格式。
    """
    skills = profile.get("skills", {})

    # 检测旧格式
    if "core" in skills or "tools" in skills:
        normalized = {}
        # core 技能默认 level=2（基础使用）
        for skill in skills.get("core", []):
            normalized[skill] = {"level": 2, "years": 0}
        # tools 技能默认 level=2
        for skill in skills.get("tools", []):
            normalized[skill] = {"level": 2, "years": 0}
        return normalized

    # 已经是新格式，确保每个技能都有 level 和 years
    normalized = {}
    for skill_name, skill_data in skills.items():
        if isinstance(skill_data, dict):
            normalized[skill_name] = {
                "level": skill_data.get("level", 2),
                "years": skill_data.get("years", 0),
                "projects": skill_data.get("projects", [])
            }
        else:
            # 兼容简化格式（只有技能名）
            normalized[skill_name] = {"level": 2, "years": 0, "projects": []}

    return normalized


def calculate_skill_match_score(
    user_skill_data: Dict[str, Any],
    required_skill: str,
    category: str
) -> float:
    """
    计算单个技能的匹配分数（0-1.15）。

    参数:
        user_skill_data: {"level": 3, "years": 2, "projects": [...]}
        required_skill: 岗位要求的技能名称
        category: "required_skills" | "tech_stack" | "nice_to_have"

    返回:
        0: 完全不匹配
        0-1: 部分匹配（熟练度不足）
        1.0: 完全匹配（达到 min_level）
        1.0-1.15: 超出要求（轻微加分，避免“虚高”）
    """
    config = JOB_REQUIREMENT_LEVEL[category]
    min_level = max(int(config.get("min_level", 1) or 1), 1)
    user_level = int(user_skill_data.get("level", 0) or 0)
    user_level = max(0, min(5, user_level))
    user_years = float(user_skill_data.get("years", 0) or 0)

    if user_level <= 0:
        return 0.0

    # 1) 熟练度按比例计分（未达标也能得分，用于“软门槛”）
    level_ratio = min(user_level / min_level, 1.0)
    if user_level > min_level:
        # 超出要求：每高 1 级加 0.05，上限 +0.15
        score = 1.0 + min((user_level - min_level) * 0.05, 0.15)
    else:
        score = level_ratio

    # 2) 经验年限轻微加成（2 年以上 +5%）
    if user_years >= 2:
        score *= 1.05

    return float(min(1.15, max(0.0, score)))


def find_matching_skill(
    user_skills: Dict[str, Dict[str, Any]],
    required_skill: str,
    category: str
) -> Tuple[bool, str, float, Dict[str, Any]]:
    """
    在用户技能中查找匹配的技能。

    返回: (是否匹配, 匹配的用户技能名, 匹配分数, 匹配信息)
    """
    threshold = JOB_REQUIREMENT_LEVEL[category]["threshold"]
    norm_required = _norm(required_skill)
    raw_required = _raw_compare_key(required_skill)

    # 1. 近似精确匹配（忽略大小写与分隔符）
    for user_skill_name, user_skill_data in user_skills.items():
        if _raw_compare_key(user_skill_name) == raw_required:
            score = calculate_skill_match_score(user_skill_data, required_skill, category)
            return True, user_skill_name, score, {"match_type": "exact", "similarity": 1.0}

    # 2. 同义词匹配（标准化后相等）
    for user_skill_name, user_skill_data in user_skills.items():
        if _norm(user_skill_name) == norm_required:
            score = calculate_skill_match_score(user_skill_data, required_skill, category)
            return True, user_skill_name, score, {"match_type": "synonym", "similarity": 1.0}

    # 3. 语义匹配（sentence-transformers 可用时启用）
    model = _get_st_model()
    if model is not None:
        best_name = ""
        best_sim = 0.0
        best_data: Dict[str, Any] | None = None

        for user_skill_name, user_skill_data in user_skills.items():
            try:
                from sentence_transformers import util
                u = _encode(user_skill_name)
                r = _encode(required_skill)
                if u is None or r is None:
                    continue
                sim = float(util.cos_sim(u, r))
            except Exception:
                sim = 0.0

            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_name = user_skill_name
                best_data = user_skill_data

        if best_data is not None:
            score = calculate_skill_match_score(best_data, required_skill, category)
            return True, best_name, score, {
                "match_type": "semantic",
                "similarity": float(best_sim),
                "threshold": float(threshold),
            }

        # 语义匹配可用但未命中时，不继续走模糊匹配，避免误判
        return False, "", 0.0, {"match_type": "none"}

    # 4. 模糊匹配降级（语义模型不可用时启用）
    fuzzy_th = FUZZY_THRESHOLD.get(category, 0.85)
    best_name = ""
    best_sim = 0.0
    best_data = None
    for user_skill_name, user_skill_data in user_skills.items():
        sim = _fuzzy_similarity(user_skill_name, required_skill)
        if sim >= fuzzy_th and sim > best_sim:
            best_sim = sim
            best_name = user_skill_name
            best_data = user_skill_data

    if best_data is not None:
        score = calculate_skill_match_score(best_data, required_skill, category)
        return True, best_name, score, {
            "match_type": "fuzzy",
            "similarity": float(best_sim),
            "threshold": float(fuzzy_th),
        }

    return False, "", 0.0, {"match_type": "none"}


def _profile_for_llm(profile: Dict[str, Any]) -> Dict[str, Any]:
    normalized_skills = normalize_user_skills(profile)
    return {
        "experience_years": profile.get("experience_years", 0),
        "experience_level": profile.get("experience_level", ""),
        "target_keywords": profile.get("target_keywords", []),
        "preferences": profile.get("preferences", {}),
        "skills": normalized_skills,
    }


def _normalize_breakdown_item(item: Dict[str, Any], weight: float) -> Dict[str, Any]:
    item = item if isinstance(item, dict) else {}
    return {
        "coverage": float(item.get("coverage", 0.0) or 0.0),
        "avg_skill_score": float(item.get("avg_skill_score", 0.0) or 0.0),
        "weight": float(item.get("weight", weight) or weight),
        "matched_count": int(item.get("matched_count", 0) or 0),
        "total_count": int(item.get("total_count", 0) or 0),
    }


def _normalize_llm_match_result(result: Dict[str, Any]) -> Dict[str, Any]:
    matched_skills = [str(skill).strip() for skill in result.get("matched_skills", []) if str(skill).strip()]
    skill_gaps = [str(skill).strip() for skill in result.get("skill_gaps", []) if str(skill).strip()]

    matched_details = []
    for item in result.get("matched_skills_detailed", []) or []:
        if not isinstance(item, dict):
            continue
        matched_details.append(
            {
                "skill": str(item.get("skill", "")).strip(),
                "user_skill": str(item.get("user_skill", item.get("skill", ""))).strip(),
                "user_level": max(0, min(5, int(item.get("user_level", 0) or 0))),
                "match_quality": str(item.get("match_quality", "匹配")).strip() or "匹配",
                "category": str(item.get("category", "必备技能")).strip() or "必备技能",
            }
        )

    gap_details = []
    for item in result.get("skill_gaps_detailed", []) or []:
        if not isinstance(item, dict):
            continue
        gap_details.append(
            {
                "skill": str(item.get("skill", "")).strip(),
                "required_level": max(0, min(5, int(item.get("required_level", 3) or 3))),
                "user_level": max(0, min(5, int(item.get("user_level", 0) or 0))),
                "gap_desc": str(item.get("gap_desc", "")).strip(),
                "category": str(item.get("category", "required_skills")).strip() or "required_skills",
            }
        )

    if not matched_skills and matched_details:
        matched_skills = [item["skill"] for item in matched_details if item["skill"]]
    if not skill_gaps and gap_details:
        skill_gaps = [item["skill"] for item in gap_details if item["skill"]]

    score = int(max(0, min(100, round(float(result.get("score", 0) or 0)))))
    breakdown = result.get("score_breakdown", {}) if isinstance(result.get("score_breakdown"), dict) else {}

    return {
        "score": score,
        "skill_gaps": skill_gaps[:6],
        "skill_gaps_detailed": gap_details[:6],
        "matched_skills": matched_skills[:6],
        "matched_skills_detailed": matched_details[:6],
        "match_reasons": [str(reason).strip() for reason in (result.get("match_reasons", []) or []) if str(reason).strip()][:3],
        "score_breakdown": {
            "required_skills": _normalize_breakdown_item(breakdown.get("required_skills", {}), JOB_REQUIREMENT_LEVEL["required_skills"]["weight"]),
            "tech_stack": _normalize_breakdown_item(breakdown.get("tech_stack", {}), JOB_REQUIREMENT_LEVEL["tech_stack"]["weight"]),
            "nice_to_have": _normalize_breakdown_item(breakdown.get("nice_to_have", {}), JOB_REQUIREMENT_LEVEL["nice_to_have"]["weight"]),
            "base": float(breakdown.get("base", score / 100.0) or 0.0),
            "gate": float(breakdown.get("gate", 1.0) or 0.0),
            "raw_score": float(breakdown.get("raw_score", score) or 0.0),
            "exp_adjust": int(breakdown.get("exp_adjust", 0) or 0),
        },
        "matching_debug": result.get("matching_debug", []),
    }


def _llm_match_job(profile: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    prompt = (
        f"{_LLM_MATCH_PROMPT}\n\n"
        f"用户画像：\n{json.dumps(_profile_for_llm(profile), ensure_ascii=False, indent=2)}\n\n"
        f"岗位分析：\n{json.dumps(analysis or {}, ensure_ascii=False, indent=2)}"
    )
    try:
        result = complete_json_flexible(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
        )
    except json.JSONDecodeError as exc:
        preview = (getattr(exc, "doc", "") or "").strip().replace("\n", " ")
        if preview:
            preview = preview[:200]
            raise RuntimeError(f"岗位匹配评分失败：LLM 未返回合法 JSON。原始输出片段：{preview}") from exc
        raise RuntimeError("岗位匹配评分失败：LLM 未返回合法 JSON，且返回内容为空。") from exc
    return _normalize_llm_match_result(result)


def _rule_based_match_job_enhanced(profile: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    增强版职位匹配算法，考虑技能熟练度。

    返回格式:
    {
        "score": 85,
        "skill_gaps": [
            {"skill": "RAG", "required_level": 3, "user_level": 0, "gap_desc": "需要从零学习"},
            {"skill": "Python", "required_level": 3, "user_level": 2, "gap_desc": "需要从基础提升到熟练"}
        ],
        "matched_skills": [
            {"skill": "LangChain", "user_level": 3, "match_quality": "完全匹配"},
            {"skill": "Git", "user_level": 4, "match_quality": "超出要求"}
        ],
        "match_reasons": [...]
    }
    """
    # 标准化用户技能
    user_skills = normalize_user_skills(profile)

    required = analysis.get("required_skills", [])
    tech_stack = analysis.get("tech_stack", [])
    nice_to_have = analysis.get("nice_to_have", [])

    # 计算各类别匹配分数
    required_scores = []
    tech_scores = []
    bonus_scores = []
    required_matched_count = 0
    tech_matched_count = 0
    bonus_matched_count = 0

    matched_details = []
    gap_details = []
    debug_items = []

    # 处理必备技能
    for skill in required:
        matched, user_skill_name, score, info = find_matching_skill(user_skills, skill, "required_skills")
        if matched:
            required_matched_count += 1
            required_scores.append(score)
            user_level = int(user_skills.get(user_skill_name, {}).get("level", 0) or 0)
            user_level = max(0, min(5, user_level))
            min_level = int(JOB_REQUIREMENT_LEVEL["required_skills"]["min_level"])

            if score >= 1.0:
                quality = "完全匹配" if score == 1.0 else "超出要求"
            else:
                quality = "部分匹配"

            detail = {
                "skill": skill,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "match_quality": quality,
                "category": "必备技能",
                **info,
            }
            matched_details.append(detail)

            debug_items.append({
                "skill": skill,
                "category": "required_skills",
                "matched": True,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "required_level": min_level,
                "match_type": info.get("match_type"),
                "similarity": info.get("similarity"),
                "score": score,
            })

            # 如果熟练度不足，也算作缺口
            if user_level < min_level:
                gap_details.append({
                    "skill": skill,
                    "required_level": min_level,
                    "user_level": user_level,
                    "gap_desc": f"需要从{SKILL_PROFICIENCY[user_level]}提升到{SKILL_PROFICIENCY[min_level]}",
                    "category": "required_skills"
                })
        else:
            required_scores.append(0)
            debug_items.append({
                "skill": skill,
                "category": "required_skills",
                "matched": False,
                "user_skill": "",
                "user_level": 0,
                "required_level": JOB_REQUIREMENT_LEVEL["required_skills"]["min_level"],
                "match_type": info.get("match_type"),
                "similarity": info.get("similarity"),
                "score": 0.0,
            })
            gap_details.append({
                "skill": skill,
                "required_level": JOB_REQUIREMENT_LEVEL["required_skills"]["min_level"],
                "user_level": 0,
                "gap_desc": "需要从零学习",
                "category": "required_skills"
            })

    # 处理技术栈
    for skill in tech_stack:
        matched, user_skill_name, score, info = find_matching_skill(user_skills, skill, "tech_stack")
        if matched:
            tech_matched_count += 1
            tech_scores.append(score)
            user_level = int(user_skills.get(user_skill_name, {}).get("level", 0) or 0)
            user_level = max(0, min(5, user_level))
            min_level = int(JOB_REQUIREMENT_LEVEL["tech_stack"]["min_level"])

            if score >= 1.0:
                quality = "完全匹配" if score == 1.0 else "超出要求"
            else:
                quality = "部分匹配"

            detail = {
                "skill": skill,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "match_quality": quality,
                "category": "技术栈",
                **info,
            }
            matched_details.append(detail)

            debug_items.append({
                "skill": skill,
                "category": "tech_stack",
                "matched": True,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "required_level": min_level,
                "match_type": info.get("match_type"),
                "similarity": info.get("similarity"),
                "score": score,
            })

            if user_level < min_level:
                gap_details.append({
                    "skill": skill,
                    "required_level": min_level,
                    "user_level": user_level,
                    "gap_desc": f"需要从{SKILL_PROFICIENCY[user_level]}提升到{SKILL_PROFICIENCY[min_level]}",
                    "category": "tech_stack"
                })
        else:
            tech_scores.append(0)
            debug_items.append({
                "skill": skill,
                "category": "tech_stack",
                "matched": False,
                "user_skill": "",
                "user_level": 0,
                "required_level": JOB_REQUIREMENT_LEVEL["tech_stack"]["min_level"],
                "match_type": info.get("match_type"),
                "similarity": info.get("similarity"),
                "score": 0.0,
            })
            gap_details.append({
                "skill": skill,
                "required_level": JOB_REQUIREMENT_LEVEL["tech_stack"]["min_level"],
                "user_level": 0,
                "gap_desc": "需要从零学习",
                "category": "tech_stack"
            })

    # 处理加分项
    for skill in nice_to_have:
        matched, user_skill_name, score, info = find_matching_skill(user_skills, skill, "nice_to_have")
        if matched:
            bonus_matched_count += 1
            bonus_scores.append(score)
            user_level = int(user_skills.get(user_skill_name, {}).get("level", 0) or 0)
            user_level = max(0, min(5, user_level))
            detail = {
                "skill": skill,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "match_quality": "加分项",
                "category": "加分项",
                **info,
            }
            matched_details.append(detail)

            debug_items.append({
                "skill": skill,
                "category": "nice_to_have",
                "matched": True,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "required_level": JOB_REQUIREMENT_LEVEL["nice_to_have"]["min_level"],
                "match_type": info.get("match_type"),
                "similarity": info.get("similarity"),
                "score": score,
            })
        else:
            bonus_scores.append(0)
            debug_items.append({
                "skill": skill,
                "category": "nice_to_have",
                "matched": False,
                "user_skill": "",
                "user_level": 0,
                "required_level": JOB_REQUIREMENT_LEVEL["nice_to_have"]["min_level"],
                "match_type": info.get("match_type"),
                "similarity": info.get("similarity"),
                "score": 0.0,
            })

    # 计算分项
    required_avg = (sum(required_scores) / len(required)) if required else 0.0
    stack_avg = (sum(tech_scores) / len(tech_stack)) if tech_stack else 0.0
    bonus_avg = (sum(bonus_scores) / len(nice_to_have)) if nice_to_have else 0.0

    required_coverage = (required_matched_count / len(required)) if required else 1.0
    stack_coverage = (tech_matched_count / len(tech_stack)) if tech_stack else 0.0
    bonus_coverage = (bonus_matched_count / len(nice_to_have)) if nice_to_have else 0.0

    # 权重只对非空类别生效，避免“无该项也被扣分”
    weighted_sum = 0.0
    weight_total = 0.0
    if required:
        w = float(JOB_REQUIREMENT_LEVEL["required_skills"]["weight"])
        weighted_sum += w * required_avg
        weight_total += w
    if tech_stack:
        w = float(JOB_REQUIREMENT_LEVEL["tech_stack"]["weight"])
        weighted_sum += w * stack_avg
        weight_total += w
    if nice_to_have:
        w = float(JOB_REQUIREMENT_LEVEL["nice_to_have"]["weight"])
        weighted_sum += w * bonus_avg
        weight_total += w

    base = (weighted_sum / weight_total) if weight_total else 0.0

    # 软门槛：必备技能覆盖率越低，分数衰减越明显，但不直接归零
    gate = 0.35 + 0.65 * required_coverage

    raw_score = 100.0 * base * gate
    score = int(round(raw_score))

    # 经验级别加成
    exp_adjust = 0
    try:
        exp_years = profile.get("experience_years", None)
        exp_years_f = float(exp_years) if exp_years is not None else None
    except Exception:
        exp_years_f = None

    job_level = analysis.get("job_level")
    if exp_years_f is not None:
        if job_level == "初级" and exp_years_f <= 1:
            exp_adjust += 5
        if job_level == "高级" and exp_years_f < 3:
            exp_adjust -= 5

    score += exp_adjust
    score = int(max(0, min(100, score)))

    # 生成匹配理由
    reasons = []
    if matched_details:
        top_matched = [f"{m['skill']}({SKILL_PROFICIENCY[m['user_level']]})"
                      for m in matched_details[:4]]
        reasons.append(f"已覆盖关键技能：{', '.join(top_matched)}")

    if not gap_details:
        reasons.append("岗位核心技能基本匹配，可直接进入项目落地阶段")
    else:
        top_gaps = [g['skill'] for g in gap_details[:4]]
        reasons.append(f"主要差距：{', '.join(top_gaps)}")

    match_desc = "较高" if score >= 60 else "一般" if score >= 40 else "偏低"
    reasons.append(f"岗位级别：{analysis.get('job_level', '未知')}，与你当前阶段匹配度{match_desc}")

    # 简化的技能缺口列表（向后兼容）
    simple_gaps = [g['skill'] for g in gap_details]

    return {
        "score": score,
        "skill_gaps": simple_gaps[:6],  # 向后兼容
        "skill_gaps_detailed": gap_details[:6],  # 新增详细信息
        "matched_skills": [m['skill'] for m in matched_details[:6]],  # 向后兼容
        "matched_skills_detailed": matched_details[:6],  # 新增详细信息
        "match_reasons": reasons[:3],
        "score_breakdown": {
            "required_skills": {
                "coverage": required_coverage,
                "avg_skill_score": required_avg,
                "weight": JOB_REQUIREMENT_LEVEL["required_skills"]["weight"] if required else 0.0,
                "matched_count": required_matched_count,
                "total_count": len(required),
            },
            "tech_stack": {
                "coverage": stack_coverage,
                "avg_skill_score": stack_avg,
                "weight": JOB_REQUIREMENT_LEVEL["tech_stack"]["weight"] if tech_stack else 0.0,
                "matched_count": tech_matched_count,
                "total_count": len(tech_stack),
            },
            "nice_to_have": {
                "coverage": bonus_coverage,
                "avg_skill_score": bonus_avg,
                "weight": JOB_REQUIREMENT_LEVEL["nice_to_have"]["weight"] if nice_to_have else 0.0,
                "matched_count": bonus_matched_count,
                "total_count": len(nice_to_have),
            },
            "base": base,
            "gate": gate,
            "raw_score": raw_score,
            "exp_adjust": exp_adjust,
        },
        "matching_debug": debug_items,
    }


def match_job_enhanced(profile: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    if has_llm_configured():
        return _llm_match_job(profile, analysis)
    return _rule_based_match_job_enhanced(profile, analysis)
