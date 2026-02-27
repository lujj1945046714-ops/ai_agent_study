from typing import Any, Dict, List, Set
from functools import lru_cache

_st_model = None


def _get_st_model():
    # 语义匹配已禁用（模型需联网下载，改用关键词匹配）
    return None


@lru_cache(maxsize=256)
def _encode(text: str):
    model = _get_st_model()
    if model is None:
        return None
    return model.encode(text, convert_to_tensor=True)


def _semantic_match(user_skill: str, required_skill: str, threshold: float = 0.75) -> bool:
    from sentence_transformers import util
    u = _encode(user_skill)
    r = _encode(required_skill)
    if u is None or r is None:
        return False
    return float(util.cos_sim(u, r)) >= threshold


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
    key = skill.strip().lower()
    return _SYNONYM.get(key, key)


def _extract_user_skills(profile: Dict[str, Any]) -> Set[str]:
    result: Set[str] = set()
    for _, skill_list in profile.get("skills", {}).items():
        for skill in skill_list:
            result.add(_norm(skill))
    return result


def _skill_covered(user_skills: Set[str], required_skill: str) -> bool:
    """Check exact match first, then fall back to semantic similarity."""
    norm = _norm(required_skill)
    if norm in user_skills:
        return True
    model = _get_st_model()
    if model is None:
        return False
    return any(_semantic_match(u, required_skill) for u in user_skills)


def _pick_missing(user_skills: Set[str], target_skills: List[str]) -> List[str]:
    gaps: List[str] = []
    for skill in target_skills:
        if not _skill_covered(user_skills, skill):
            gaps.append(skill)
    return gaps


def match_job(profile: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    user_skills = _extract_user_skills(profile)
    required = analysis.get("required_skills", [])
    tech_stack = analysis.get("tech_stack", [])
    nice_to_have = analysis.get("nice_to_have", [])

    required_match = 0 if not required else sum(_skill_covered(user_skills, s) for s in required) / len(required)
    stack_match = 0 if not tech_stack else sum(_skill_covered(user_skills, s) for s in tech_stack) / len(tech_stack)
    bonus_match = 0 if not nice_to_have else sum(_skill_covered(user_skills, s) for s in nice_to_have) / len(nice_to_have)

    # 必备技能作为乘法门槛：required=0 时总分直接为0，无法被其他项救回
    score = int(round(required_match * (0.7 + stack_match * 0.2 + bonus_match * 0.1) * 100))
    exp_level = str(profile.get("experience_level", ""))
    if analysis.get("job_level") == "初级" and "应届" in exp_level:
        score = min(100, score + 8)

    gaps = _pick_missing(user_skills, required + tech_stack)
    matched = [skill for skill in required + tech_stack if _skill_covered(user_skills, skill)]
    matched_unique = list(dict.fromkeys(matched))
    gaps_unique = list(dict.fromkeys(gaps))

    reasons: List[str] = []
    if matched_unique:
        reasons.append(f"已覆盖关键技能：{', '.join(matched_unique[:4])}")
    if not gaps_unique:
        reasons.append("岗位核心技能基本匹配，可直接进入项目落地阶段")
    else:
        reasons.append(f"主要差距：{', '.join(gaps_unique[:4])}")
    reasons.append(f"岗位级别：{analysis.get('job_level', '未知')}，与你当前阶段匹配度较高")

    return {
        "score": score,
        "skill_gaps": gaps_unique[:6],
        "matched_skills": matched_unique[:6],
        "match_reasons": reasons[:3],
    }
