from typing import Any, Dict, List, Set


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


def _pick_missing(user_skills: Set[str], target_skills: List[str]) -> List[str]:
    gaps: List[str] = []
    for skill in target_skills:
        if _norm(skill) not in user_skills:
            gaps.append(skill)
    return gaps


def match_job(profile: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    user_skills = _extract_user_skills(profile)
    required = analysis.get("required_skills", [])
    tech_stack = analysis.get("tech_stack", [])
    nice_to_have = analysis.get("nice_to_have", [])

    required_match = 0 if not required else sum(_norm(s) in user_skills for s in required) / len(required)
    stack_match = 0 if not tech_stack else sum(_norm(s) in user_skills for s in tech_stack) / len(tech_stack)
    bonus_match = 0 if not nice_to_have else sum(_norm(s) in user_skills for s in nice_to_have) / len(nice_to_have)

    score = int(round((required_match * 0.55 + stack_match * 0.3 + bonus_match * 0.15) * 100))
    exp_level = str(profile.get("experience_level", ""))
    if analysis.get("job_level") == "初级" and "应届" in exp_level:
        score = min(100, score + 8)

    gaps = _pick_missing(user_skills, required + tech_stack)
    matched = [skill for skill in required + tech_stack if _norm(skill) in user_skills]
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
