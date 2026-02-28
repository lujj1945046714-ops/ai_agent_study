"""
测试增强版技能匹配算法
"""
import json
from modules.matcher_enhanced import (
    match_job_enhanced,
    normalize_user_skills,
    SKILL_PROFICIENCY
)

# 测试用例 1: 旧格式用户画像（向后兼容）
old_format_profile = {
    "name": "旧格式用户",
    "experience_level": "应届",
    "skills": {
        "core": ["Python", "LLM API调用"],
        "tools": ["Git"]
    }
}

# 测试用例 2: 新格式用户画像（低熟练度）
low_proficiency_profile = {
    "name": "初学者",
    "experience_level": "应届",
    "skills": {
        "Python": {"level": 2, "years": 0.5},
        "LangChain": {"level": 1, "years": 0},
        "Git": {"level": 2, "years": 0.5}
    }
}

# 测试用例 3: 新格式用户画像（高熟练度）
high_proficiency_profile = {
    "name": "资深工程师",
    "experience_level": "3-5年",
    "skills": {
        "Python": {"level": 4, "years": 4, "projects": ["项目A", "项目B"]},
        "LangChain": {"level": 3, "years": 1.5, "projects": ["Agent系统"]},
        "FastAPI": {"level": 4, "years": 3},
        "Git": {"level": 4, "years": 4},
        "Docker": {"level": 3, "years": 2},
        "RAG": {"level": 3, "years": 1}
    }
}

# 测试用例 4: 新格式用户画像（中等熟练度）
medium_proficiency_profile = {
    "name": "中级工程师",
    "experience_level": "1-3年",
    "skills": {
        "Python": {"level": 3, "years": 2},
        "LangChain": {"level": 2, "years": 0.5},
        "FastAPI": {"level": 3, "years": 1.5},
        "Git": {"level": 3, "years": 2},
        "LLM API调用": {"level": 3, "years": 1}
    }
}

# 测试 JD
test_analysis = {
    "required_skills": ["Python", "LangChain", "LLM API调用"],
    "tech_stack": ["FastAPI", "Git", "Docker"],
    "nice_to_have": ["RAG", "向量数据库"],
    "job_level": "中级",
    "summary": "负责基于 LLM 的 Agent 系统设计与开发"
}


def print_match_result(profile, analysis, title):
    """打印匹配结果"""
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")

    # 显示用户技能
    print(f"\n用户: {profile['name']} ({profile['experience_level']})")
    print(f"技能:")
    skills = normalize_user_skills(profile)
    for skill_name, skill_data in skills.items():
        level = skill_data['level']
        years = skill_data['years']
        print(f"  - {skill_name}: {SKILL_PROFICIENCY[level]} (level {level}, {years}年)")

    # 执行匹配
    result = match_job_enhanced(profile, analysis)

    # 显示匹配结果
    print(f"\n匹配分数: {result['score']}/100")

    print(f"\n已匹配技能:")
    if result.get('matched_skills_detailed'):
        for m in result['matched_skills_detailed']:
            print(f"  ✓ {m['skill']} ({m['category']})")
            print(f"    用户水平: {SKILL_PROFICIENCY[m['user_level']]} (level {m['user_level']})")
            print(f"    匹配质量: {m['match_quality']}")
    else:
        print("  无")

    print(f"\n技能缺口:")
    if result.get('skill_gaps_detailed'):
        for g in result['skill_gaps_detailed']:
            print(f"  ✗ {g['skill']} ({g['category']})")
            print(f"    要求水平: {SKILL_PROFICIENCY[g['required_level']]} (level {g['required_level']})")
            print(f"    当前水平: {SKILL_PROFICIENCY[g['user_level']]} (level {g['user_level']})")
            print(f"    差距描述: {g['gap_desc']}")
    else:
        print("  无")

    print(f"\n匹配理由:")
    for reason in result['match_reasons']:
        print(f"  • {reason}")

    return result


def test_all():
    """运行所有测试"""
    print("\n" + "="*60)
    print("增强版技能匹配算法测试")
    print("="*60)

    # 测试 1: 旧格式（向后兼容）
    r1 = print_match_result(
        old_format_profile,
        test_analysis,
        "测试 1: 旧格式用户画像（向后兼容）"
    )

    # 测试 2: 低熟练度
    r2 = print_match_result(
        low_proficiency_profile,
        test_analysis,
        "测试 2: 低熟练度用户（初学者）"
    )

    # 测试 3: 中等熟练度
    r3 = print_match_result(
        medium_proficiency_profile,
        test_analysis,
        "测试 3: 中等熟练度用户（1-3年）"
    )

    # 测试 4: 高熟练度
    r4 = print_match_result(
        high_proficiency_profile,
        test_analysis,
        "测试 4: 高熟练度用户（3-5年）"
    )

    # 对比分析
    print(f"\n{'='*60}")
    print("对比分析")
    print(f"{'='*60}")
    print(f"\n旧格式用户（默认 level 2）: {r1['score']} 分")
    print(f"低熟练度用户（level 1-2）:  {r2['score']} 分")
    print(f"中等熟练度用户（level 2-3）: {r3['score']} 分")
    print(f"高熟练度用户（level 3-4）:  {r4['score']} 分")

    print(f"\n✅ 验证: 熟练度越高，匹配分数越高")
    assert r2['score'] < r3['score'] < r4['score'], "熟练度排序错误"

    print(f"✅ 验证: 旧格式兼容性正常")
    assert r1['score'] > 0, "旧格式匹配失败"

    print(f"\n{'='*60}")
    print("所有测试通过！✓")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    test_all()
