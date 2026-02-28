"""
Phase 2 单元测试：测试各个模块
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from agent.conversation_memory import ConversationMemory
from agent.suggestion_engine import ProactiveSuggestionEngine
from agent.learning_planner import LearningPlanner
from agent.context_understanding import ContextualUnderstanding


def test_conversation_memory():
    """测试对话记忆系统"""
    print("\n" + "=" * 60)
    print("测试 1: 对话记忆系统")
    print("=" * 60)

    memory = ConversationMemory(max_history=10)

    # 添加职位分析
    job_info = {
        "title": "AI Agent 工程师",
        "company": "测试公司",
        "city": "上海",
        "salary": "25-35k"
    }
    analysis = {
        "required_skills": ["Python", "LangChain", "FastAPI"],
        "tech_stack": ["Docker", "Git"],
        "nice_to_have": ["RAG", "Prompt Engineering"]
    }
    memory.add_job_analysis("job-001", job_info, analysis)

    # 添加匹配结果
    match_result = {
        "score": 71,
        "skill_gaps": ["LangChain", "Docker"],
        "matched_skills": ["Python", "FastAPI"]
    }
    memory.add_match_result("job-001", match_result)

    # 添加推荐项目
    projects = [
        {"repo": "langchain/langchain", "stars": 50000},
        {"repo": "chatchat-space/Langchain-Chatchat", "stars": 20000}
    ]
    memory.add_recommended_projects("job-001", projects)

    # 添加对话
    memory.add_conversation_turn(
        "帮我分析这个职位",
        "已完成分析，匹配度71分"
    )

    # 测试查询
    print("\n✓ 添加数据成功")
    print(f"  已分析职位数: {len(memory.analyzed_jobs)}")
    print(f"  已推荐项目数: {len(memory.get_recommended_projects('job-001'))}")
    print(f"  对话轮数: {len(memory.conversation_history)}")

    # 测试上下文摘要
    print("\n上下文摘要:")
    print(memory.get_context_summary())

    # 测试持久化
    temp_file = project_root / "test_memory.json"
    memory.save(str(temp_file))
    print(f"\n✓ 保存到文件: {temp_file}")

    # 测试加载
    memory2 = ConversationMemory()
    memory2.load(str(temp_file))
    print(f"✓ 从文件加载成功")
    print(f"  已分析职位数: {len(memory2.analyzed_jobs)}")

    # 清理
    temp_file.unlink()

    print("\n✅ 对话记忆系统测试通过")
    return True


def test_suggestion_engine():
    """测试主动建议引擎"""
    print("\n" + "=" * 60)
    print("测试 2: 主动建议引擎")
    print("=" * 60)

    engine = ProactiveSuggestionEngine()

    # 测试不同匹配度的建议
    test_cases = [
        (45, ["LangChain", "Docker", "FastAPI"], "低匹配度"),
        (65, ["LangChain", "Docker"], "中等匹配度"),
        (75, ["Docker"], "良好匹配度"),
        (90, [], "高匹配度")
    ]

    for score, gaps, desc in test_cases:
        print(f"\n--- {desc} ({score}分) ---")
        suggestion = engine.suggest_after_analysis(
            "job-001",
            "AI Agent 工程师",
            score,
            gaps,
            ["Python", "FastAPI"]
        )
        print(f"建议级别: {suggestion['level']}")
        print(f"消息: {suggestion['message'][:50]}...")
        print(f"建议数: {len(suggestion['suggestions'])}")

    # 测试推荐后建议
    print("\n--- 推荐后建议 ---")
    suggestion = engine.suggest_after_recommendation("AI Agent 工程师", 3, 2)
    print(f"消息: {suggestion['message']}")
    print(f"建议数: {len(suggestion['suggestions'])}")

    # 测试格式化
    print("\n--- 格式化输出 ---")
    formatted = engine.format_suggestion(suggestion)
    print(formatted[:200] + "...")

    print("\n✅ 主动建议引擎测试通过")
    return True


def test_learning_planner():
    """测试学习规划器"""
    print("\n" + "=" * 60)
    print("测试 3: 学习规划器")
    print("=" * 60)

    planner = LearningPlanner()

    # 测试技能缺口
    skill_gaps = [
        {
            "skill": "LangChain",
            "required_level": 3,
            "user_level": 2,
            "category": "required_skills"
        },
        {
            "skill": "Docker",
            "required_level": 2,
            "user_level": 0,
            "category": "tech_stack"
        },
        {
            "skill": "RAG",
            "required_level": 2,
            "user_level": 0,
            "category": "nice_to_have"
        }
    ]

    # 测试3个月计划
    print("\n--- 3个月学习计划 ---")
    plan = planner.create_plan(skill_gaps, "3months")
    print(f"时间框架: {plan['timeframe']}")
    print(f"总周数: {plan['total_weeks']}")
    print(f"预计周数: {plan['estimated_weeks']}")
    print(f"可行性: {plan['feasible']}")
    print(f"阶段数: {len(plan['phases'])}")

    # 测试格式化
    print("\n--- 格式化计划 ---")
    formatted = planner.format_plan(plan)
    print(formatted[:300] + "...")

    # 测试快速计划
    print("\n--- 快速学习建议 ---")
    quick_plan = planner.create_quick_plan(skill_gaps)
    print(quick_plan)

    print("\n✅ 学习规划器测试通过")
    return True


def test_context_understanding():
    """测试上下文理解"""
    print("\n" + "=" * 60)
    print("测试 4: 上下文理解")
    print("=" * 60)

    # 创建记忆
    memory = ConversationMemory()
    memory.add_job_analysis(
        "job-001",
        {"title": "AI Agent 工程师", "company": "测试公司"},
        {"required_skills": ["Python", "LangChain"]}
    )
    memory.add_match_result("job-001", {"score": 71})

    # 创建理解器
    understanding = ContextualUnderstanding(memory)

    # 测试不同输入
    test_inputs = [
        "再推荐几个项目",
        "这个职位怎么样",
        "对比一下",
        "制定学习计划",
        "帮我分析这个职位"
    ]

    for user_input in test_inputs:
        print(f"\n--- 输入: {user_input} ---")
        result = understanding.understand(user_input)
        enhanced = understanding.enhance_with_context(result)

        print(f"意图: {enhanced['intent']}")
        print(f"需要上下文: {enhanced['needs_context']}")

        if enhanced['references']:
            print(f"指代: {enhanced['references']}")

        # 测试补全
        completed = understanding.complete_user_input(user_input)
        if completed != user_input:
            print(f"补全后: {completed}")

    print("\n✅ 上下文理解测试通过")
    return True


def test_integration():
    """测试模块集成"""
    print("\n" + "=" * 60)
    print("测试 5: 模块集成")
    print("=" * 60)

    # 创建所有模块
    memory = ConversationMemory()
    engine = ProactiveSuggestionEngine()
    planner = LearningPlanner()
    understanding = ContextualUnderstanding(memory)

    # 模拟完整流程
    print("\n--- 模拟用户会话 ---")

    # 1. 分析职位
    print("\n[用户] 帮我分析这个 AI Agent 工程师职位")
    job_info = {
        "title": "AI Agent 工程师",
        "company": "测试公司",
        "city": "上海",
        "salary": "25-35k"
    }
    analysis = {
        "required_skills": ["Python", "LangChain", "FastAPI"],
        "tech_stack": ["Docker", "Git"]
    }
    memory.add_job_analysis("job-001", job_info, analysis)

    match_result = {
        "score": 71,
        "skill_gaps": ["LangChain", "Docker"],
        "matched_skills": ["Python", "FastAPI"]
    }
    memory.add_match_result("job-001", match_result)

    # 生成建议
    suggestion = engine.suggest_after_analysis(
        "job-001",
        "AI Agent 工程师",
        71,
        ["LangChain", "Docker"],
        ["Python", "FastAPI"]
    )
    print(f"[Agent] {suggestion['message'][:100]}...")
    print(f"[Agent] 建议: {len(suggestion['suggestions'])} 个选项")

    # 2. 用户追问
    print("\n[用户] 推荐学习项目")
    projects = [
        {"repo": "langchain/langchain", "stars": 50000},
        {"repo": "chatchat-space/Langchain-Chatchat", "stars": 20000}
    ]
    memory.add_recommended_projects("job-001", projects)

    suggestion2 = engine.suggest_after_recommendation("AI Agent 工程师", 2, 2)
    print(f"[Agent] {suggestion2['message']}")

    # 3. 用户再次追问（简短）
    print("\n[用户] 再推荐几个")
    result = understanding.understand("再推荐几个")
    enhanced = understanding.enhance_with_context(result)
    print(f"[理解] 意图: {enhanced['intent']}")
    print(f"[理解] 职位: {enhanced['references'].get('job_title')}")
    print(f"[理解] 已推荐: {enhanced['context'].get('already_recommended_count')} 个")

    # 4. 制定学习计划
    print("\n[用户] 制定学习计划")
    skill_gaps = [
        {"skill": "LangChain", "required_level": 3, "user_level": 2, "category": "required_skills"},
        {"skill": "Docker", "required_level": 2, "user_level": 0, "category": "tech_stack"}
    ]
    plan = planner.create_plan(skill_gaps, "3months")
    print(f"[Agent] 已创建 {plan['timeframe']} 学习计划")
    print(f"[Agent] 共 {len(plan['phases'])} 个阶段")

    # 统计
    print("\n--- 会话统计 ---")
    stats = memory.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n✅ 模块集成测试通过")
    return True


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("Phase 2 单元测试")
    print("=" * 60)

    tests = [
        ("对话记忆系统", test_conversation_memory),
        ("主动建议引擎", test_suggestion_engine),
        ("学习规划器", test_learning_planner),
        ("上下文理解", test_context_understanding),
        ("模块集成", test_integration)
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n❌ {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
        return True
    else:
        print(f"\n⚠️ {total - passed} 个测试失败")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
