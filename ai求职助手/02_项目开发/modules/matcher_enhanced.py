"""
Enhanced skill matching with proficiency levels.

新增功能：
1. 技能熟练度等级（0-5）
2. 动态语义匹配阈值
3. 向后兼容旧格式用户画像
"""
from typing import Any, Dict, List, Set, Tuple
from functools import lru_cache

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

_st_model = None


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
    "prompt engineering": "prompt",
    "prompt": "prompt",
    "rag项目深度分析": "rag",
    "向量数据库": "vector-db",
    "langchain": "langchain",
    "llamaindex": "llamaindex",
    "autogen": "autogen",
    "python": "python",
    "fastapi": "fastapi",
    "sql": "sql",
    "git": "git",
    "agent": "agent",
    "react": "react",
}


def _norm(skill: str) -> str:
    """标准化技能名称"""
    key = skill.strip().lower()
    return _SYNONYM.get(key, key)


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
    计算单个技能的匹配分数（0-1.5）。

    参数:
        user_skill_data: {"level": 3, "years": 2, "projects": [...]}
        required_skill: 岗位要求的技能名称
        category: "required_skills" | "tech_stack" | "nice_to_have"

    返回:
        0: 完全不匹配
        0-1: 部分匹配（熟练度不足）
        1.0: 完全匹配
        1.0-1.5: 超出要求（额外加分）
    """
    config = JOB_REQUIREMENT_LEVEL[category]
    min_level = config["min_level"]
    user_level = user_skill_data["level"]
    user_years = user_skill_data.get("years", 0)

    # 1. 熟练度匹配
    if user_level < min_level:
        # 未达标，按比例给分
        score = (user_level / min_level) * 0.6
    elif user_level == min_level:
        # 刚好达标
        score = 1.0
    else:
        # 超出要求，额外加分（每高1级加10%）
        score = 1.0 + (user_level - min_level) * 0.1

    # 2. 经验年限加成（2年以上经验额外加10%）
    if user_years >= 2:
        score = min(1.5, score * 1.1)

    return score


def find_matching_skill(
    user_skills: Dict[str, Dict[str, Any]],
    required_skill: str,
    category: str
) -> Tuple[bool, str, float]:
    """
    在用户技能中查找匹配的技能。

    返回: (是否匹配, 匹配的用户技能名, 匹配分数)
    """
    threshold = JOB_REQUIREMENT_LEVEL[category]["threshold"]
    norm_required = _norm(required_skill)

    # 1. 精确匹配（标准化后）
    for user_skill_name, user_skill_data in user_skills.items():
        if _norm(user_skill_name) == norm_required:
            score = calculate_skill_match_score(user_skill_data, required_skill, category)
            return True, user_skill_name, score

    # 2. 语义匹配
    model = _get_st_model()
    if model is None:
        return False, "", 0.0

    for user_skill_name, user_skill_data in user_skills.items():
        if _semantic_match(user_skill_name, required_skill, threshold):
            score = calculate_skill_match_score(user_skill_data, required_skill, category)
            return True, user_skill_name, score

    return False, "", 0.0


def match_job_enhanced(profile: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
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

    matched_details = []
    gap_details = []

    # 处理必备技能
    for skill in required:
        matched, user_skill_name, score = find_matching_skill(user_skills, skill, "required_skills")
        if matched:
            required_scores.append(score)
            user_level = user_skills[user_skill_name]["level"]
            min_level = JOB_REQUIREMENT_LEVEL["required_skills"]["min_level"]

            if score >= 1.0:
                quality = "完全匹配" if score == 1.0 else "超出要求"
            else:
                quality = "部分匹配"

            matched_details.append({
                "skill": skill,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "match_quality": quality,
                "category": "必备技能"
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
            gap_details.append({
                "skill": skill,
                "required_level": JOB_REQUIREMENT_LEVEL["required_skills"]["min_level"],
                "user_level": 0,
                "gap_desc": "需要从零学习",
                "category": "required_skills"
            })

    # 处理技术栈
    for skill in tech_stack:
        matched, user_skill_name, score = find_matching_skill(user_skills, skill, "tech_stack")
        if matched:
            tech_scores.append(score)
            user_level = user_skills[user_skill_name]["level"]
            min_level = JOB_REQUIREMENT_LEVEL["tech_stack"]["min_level"]

            if score >= 1.0:
                quality = "完全匹配" if score == 1.0 else "超出要求"
            else:
                quality = "部分匹配"

            matched_details.append({
                "skill": skill,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "match_quality": quality,
                "category": "技术栈"
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
            gap_details.append({
                "skill": skill,
                "required_level": JOB_REQUIREMENT_LEVEL["tech_stack"]["min_level"],
                "user_level": 0,
                "gap_desc": "需要从零学习",
                "category": "tech_stack"
            })

    # 处理加分项
    for skill in nice_to_have:
        matched, user_skill_name, score = find_matching_skill(user_skills, skill, "nice_to_have")
        if matched:
            bonus_scores.append(score)
            user_level = user_skills[user_skill_name]["level"]
            matched_details.append({
                "skill": skill,
                "user_skill": user_skill_name,
                "user_level": user_level,
                "match_quality": "加分项",
                "category": "加分项"
            })
        else:
            bonus_scores.append(0)

    # 计算总分
    required_match = sum(required_scores) / len(required) if required else 0
    stack_match = sum(tech_scores) / len(tech_stack) if tech_stack else 0
    bonus_match = sum(bonus_scores) / len(nice_to_have) if nice_to_have else 0

    # 必备技能作为乘法门槛
    score = int(round(required_match * (0.7 + stack_match * 0.2 + bonus_match * 0.1) * 100))

    # 经验级别加成
    exp_level = str(profile.get("experience_level", ""))
    if analysis.get("job_level") == "初级" and "应届" in exp_level:
        score = min(100, score + 8)

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
    }
