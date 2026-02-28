"""
Phase 2 Step 6: 完整集成测试

测试场景（不需要真实 API，使用 mock）：
1. 单职位深度分析流程
2. 多职位对比流程
3. 追问与上下文理解
4. 学习计划制定
5. 会话持久化与恢复
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from agent.conversation_memory import ConversationMemory
from agent.suggestion_engine import ProactiveSuggestionEngine
from agent.learning_planner import LearningPlanner
from agent.context_understanding import ContextualUnderstanding

# ── 测试数据 ────────────────────────────────────────────────────────────────

MOCK_PROFILE = {
    "name": "测试用户",
    "target_cities": ["上海", "北京"],
    "target_keywords": ["AI Agent", "LLM"],
    "skills": {
        "Python": {"level": 3},
        "FastAPI": {"level": 3},
        "LangChain": {"level": 2},
        "Docker": {"level": 0},
        "Git": {"level": 3},
    }
}

MOCK_JOBS = [
    {
        "job_id": "job-001",
        "title": "AI Agent 工程师",
        "company": "公司A",
        "city": "上海",
        "salary": "25-35k",
        "jd_text": "要求：Python、LangChain、FastAPI、Docker",
    },
    {
        "job_id": "job-002",
        "title": "LLM 应用工程师",
        "company": "公司B",
        "city": "北京",
        "salary": "30-40k",
        "jd_text": "要求：Python、LangChain、Docker、K8s",
    },
    {
        "job_id": "job-003",
        "title": "大模型工程师",
        "company": "公司C",
        "city": "上海",
        "salary": "35-50k",
        "jd_text": "要求：Python、PyTorch、LangChain、CUDA",
    },
]

MOCK_ANALYSIS = {
    "required_skills": [
        {"skill": "Python", "level": 3},
        {"skill": "LangChain", "level": 3},
        {"skill": "FastAPI", "level": 2},
    ],
    "tech_stack": [
        {"skill": "Docker", "level": 2},
        {"skill": "Git", "level": 2},
    ],
    "nice_to_have": [
        {"skill": "RAG", "level": 1},
    ],
}

MOCK_MATCH = {
    "score": 71,
    "matched_skills": ["Python", "FastAPI", "Git"],
    "skill_gaps": ["LangChain", "Docker"],
    "skill_gaps_detailed": [
        {"skill": "LangChain", "required_level": 3, "user_level": 2, "category": "required_skills"},
        {"skill": "Docker", "required_level": 2, "user_level": 0, "category": "tech_stack"},
    ],
}

MOCK_REPOS = [
    {"repo": "langchain-ai/langchain", "stars": 90000, "description": "LangChain 官方仓库"},
    {"repo": "chatchat-space/Langchain-Chatchat", "stars": 30000, "description": "中文 RAG 应用"},
    {"repo": "langgenius/dify", "stars": 40000, "description": "LLM 应用开发平台"},
]

OUTPUT_DIR = project_root / "test_output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── 场景 1: 单职位深度分析 ────────────────────────────────────────────────

def test_scenario_single_job():
    """场景1：单职位深度分析 + 主动建议"""
    print("\n" + "=" * 60)
    print("场景 1: 单职位深度分析")
    print("=" * 60)

    memory = ConversationMemory()
    engine = ProactiveSuggestionEngine()
    planner = LearningPlanner()
    context = ContextualUnderstanding(memory)

    job = MOCK_JOBS[0]
    job_id = job["job_id"]

    # Step 1: 分析职位
    print(f"\n[用户] 帮我分析「{job['title']}」这个职位")
    memory.add_job_analysis(job_id, job, MOCK_ANALYSIS)
    print(f"[Agent] 已分析职位: {job['title']} @ {job['company']}")

    # Step 2: 匹配度
    memory.add_match_result(job_id, MOCK_MATCH)
    suggestion = engine.suggest_after_analysis(
        job_id, job["title"],
        MOCK_MATCH["score"],
        MOCK_MATCH["skill_gaps"],
        MOCK_MATCH["matched_skills"]
    )
    print(f"[Agent] 匹配度: {MOCK_MATCH['score']}分")
    print(f"[Agent] 建议级别: {suggestion['level']}")
    print(f"[Agent] {suggestion['message'][:60]}...")
    assert suggestion["level"] == "good", f"期望 good，实际 {suggestion['level']}"

    # Step 3: 推荐学习项目
    print("\n[用户] 推荐学习项目")
    memory.add_recommended_projects(job_id, MOCK_REPOS)
    rec_suggestion = engine.suggest_after_recommendation(job["title"], 3, 3)
    print(f"[Agent] 已推荐 {len(MOCK_REPOS)} 个项目")
    print(f"[Agent] {rec_suggestion['message']}")
    assert len(rec_suggestion["suggestions"]) > 0

    # Step 4: 追问「再推荐几个」
    print("\n[用户] 再推荐几个")
    result = context.understand("再推荐几个")
    enhanced = context.enhance_with_context(result)
    assert enhanced["intent"] == "recommend_more"
    assert enhanced["references"].get("job_id") == job_id
    assert enhanced["context"].get("already_recommended_count") == 3
    print(f"[理解] 意图: {enhanced['intent']}")
    print(f"[理解] 指代职位: {enhanced['references'].get('job_title')}")
    print(f"[理解] 已推荐: {enhanced['context'].get('already_recommended_count')} 个")

    # Step 5: 制定学习计划
    print("\n[用户] 制定3个月学习计划")
    plan = planner.create_plan(MOCK_MATCH["skill_gaps_detailed"], "3months")
    assert plan["feasible"] is True
    assert plan["timeframe"] == "3months"
    print(f"[Agent] 已创建 {plan['timeframe']} 学习计划")
    print(f"[Agent] 共 {len(plan['phases'])} 个阶段，预计 {plan['estimated_weeks']} 周")

    print("\n✅ 场景 1 通过")
    return True


# ── 场景 2: 多职位对比 ────────────────────────────────────────────────────

def test_scenario_multi_job():
    """场景2：多职位对比"""
    print("\n" + "=" * 60)
    print("场景 2: 多职位对比")
    print("=" * 60)

    memory = ConversationMemory()
    engine = ProactiveSuggestionEngine()
    context = ContextualUnderstanding(memory)

    scores = [71, 58, 45]

    # 分析3个职位
    for i, job in enumerate(MOCK_JOBS):
        job_id = job["job_id"]
        memory.add_job_analysis(job_id, job, MOCK_ANALYSIS)
        match = {**MOCK_MATCH, "score": scores[i]}
        memory.add_match_result(job_id, match)
        print(f"[Agent] 已分析: {job['title']} — {scores[i]}分")

    # 用户追问「对比一下」
    print("\n[用户] 对比一下这几个职位")
    result = context.understand("对比一下这几个职位")
    enhanced = context.enhance_with_context(result)
    assert enhanced["intent"] == "compare_jobs"
    assert len(enhanced["references"].get("job_ids", [])) == 3
    print(f"[理解] 意图: {enhanced['intent']}")
    print(f"[理解] 对比职位数: {len(enhanced['references']['job_ids'])}")

    # 对比建议
    suggestion = engine.suggest_job_comparison(3)
    assert len(suggestion["suggestions"]) > 0
    print(f"[Agent] {suggestion['message'][:60]}...")

    # 验证上下文中的职位数据
    jobs_data = enhanced["context"].get("jobs_data", [])
    assert len(jobs_data) == 3
    # 验证分数正确
    for jd in jobs_data:
        assert jd["score"] in scores
    summary_list = [f"{j['title']}({j['score']}分)" for j in jobs_data]
    print(f"[Agent] 对比数据: {summary_list}")

    print("\n✅ 场景 2 通过")
    return True


# ── 场景 3: 上下文追问 ────────────────────────────────────────────────────

def test_scenario_context_followup():
    """场景3：多种追问与上下文理解"""
    print("\n" + "=" * 60)
    print("场景 3: 追问与上下文理解")
    print("=" * 60)

    memory = ConversationMemory()
    context = ContextualUnderstanding(memory)

    job = MOCK_JOBS[0]
    memory.add_job_analysis(job["job_id"], job, MOCK_ANALYSIS)
    memory.add_match_result(job["job_id"], MOCK_MATCH)

    test_cases = [
        ("再推荐几个项目",   "recommend_more",  True),
        ("这个职位怎么样",   "query_job",       True),
        ("对比一下",         "compare_jobs",    True),
        ("制定学习计划",     "create_plan",     True),
        ("帮我搜索新职位",   "search_jobs",     False),
        # "分析这个职位" 含 "这个职位" → 匹配 query_job（模式优先级高于 analyze_job）
        ("分析这个职位",     "query_job",       True),
    ]

    all_pass = True
    for user_input, expected_intent, needs_ctx in test_cases:
        result = context.understand(user_input)
        enhanced = context.enhance_with_context(result)
        ok = enhanced["intent"] == expected_intent
        ctx_ok = enhanced["needs_context"] == needs_ctx
        status = "✓" if (ok and ctx_ok) else "✗"
        print(f"  {status} '{user_input}' → {enhanced['intent']} (需要上下文: {enhanced['needs_context']})")
        if not (ok and ctx_ok):
            all_pass = False

    # 测试输入补全
    print("\n  输入补全测试:")
    completions = [
        ("再推荐几个", f"为「{job['title']}」再推荐几个学习项目"),
        ("这个职位怎么样", f"「{job['title']}」的匹配度怎么样？有哪些技能缺口？"),
        ("对比一下", "对比所有已分析的职位，帮我选择最合适的"),
    ]
    for user_input, expected in completions:
        completed = context.complete_user_input(user_input)
        ok = completed == expected
        status = "✓" if ok else "✗"
        print(f"  {status} '{user_input}' → '{completed}'")
        if not ok:
            all_pass = False

    assert all_pass, "部分追问测试失败"
    print("\n✅ 场景 3 通过")
    return True


# ── 场景 4: 会话持久化与恢复 ─────────────────────────────────────────────

def test_scenario_session_persistence():
    """场景4：会话持久化与恢复"""
    print("\n" + "=" * 60)
    print("场景 4: 会话持久化与恢复")
    print("=" * 60)

    session_file = OUTPUT_DIR / "test_session_step6.json"

    # 创建会话并填充数据
    memory1 = ConversationMemory()
    for job in MOCK_JOBS[:2]:
        memory1.add_job_analysis(job["job_id"], job, MOCK_ANALYSIS)
        memory1.add_match_result(job["job_id"], MOCK_MATCH)
    memory1.add_recommended_projects("job-001", MOCK_REPOS)
    memory1.add_conversation_turn("帮我分析职位", "已完成分析")
    memory1.add_conversation_turn("推荐学习项目", "已推荐3个项目")

    # 保存
    memory1.save(str(session_file))
    print(f"[保存] 会话已保存: {session_file}")
    print(f"  已分析职位: {len(memory1.analyzed_jobs)}")
    print(f"  对话轮数: {len(memory1.conversation_history)}")

    # 恢复
    memory2 = ConversationMemory()
    memory2.load(str(session_file))
    print(f"\n[恢复] 会话已加载")
    print(f"  已分析职位: {len(memory2.analyzed_jobs)}")
    print(f"  对话轮数: {len(memory2.conversation_history)}")

    # 验证数据完整性
    assert len(memory2.analyzed_jobs) == 2, "职位数不匹配"
    assert len(memory2.conversation_history) == 2, "对话轮数不匹配"
    assert memory2.get_last_analyzed_job()["job_id"] == "job-002", "最近职位不匹配"
    assert len(memory2.get_recommended_projects("job-001")) == 3, "推荐项目数不匹配"

    # 验证上下文摘要
    summary = memory2.get_context_summary()
    assert summary, "上下文摘要为空"
    print(f"\n[上下文摘要]\n{summary[:200]}...")

    # 清理
    session_file.unlink()

    print("\n✅ 场景 4 通过")
    return True


# ── 场景 5: 增强版 Agent 工具分发（mock LLM）────────────────────────────

def test_scenario_agent_dispatch():
    """场景5：增强版 Agent 工具分发（不调用真实 LLM）"""
    print("\n" + "=" * 60)
    print("场景 5: Agent 工具分发（mock）")
    print("=" * 60)

    from agent.react_agent_enhanced import JobSearchAgent

    agent = JobSearchAgent(
        user_profile=MOCK_PROFILE,
        api_key="mock-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        output_dir=OUTPUT_DIR,
        name="step6_test",
        enable_phase2=True,
    )
    agent.preload_jobs(MOCK_JOBS)

    # mock tool_analyze_job
    with patch("agent.react_agent_enhanced.tool_analyze_job", return_value=MOCK_ANALYSIS), \
         patch("agent.react_agent_enhanced.tool_match_job", return_value=MOCK_MATCH), \
         patch("agent.react_agent_enhanced.tool_recommend_learning", return_value={"repos": MOCK_REPOS}):

        # 测试 analyze_job
        result = agent._dispatch("analyze_job", {"job_id": "job-001"})
        assert "required_skills" in result, "analyze_job 返回格式错误"
        assert agent._results["job-001"]["analysis"] == MOCK_ANALYSIS
        assert agent.conversation_memory.get_last_analyzed_job()["job_id"] == "job-001"
        print("  ✓ analyze_job → 记忆已更新")

        # 测试 match_job
        result = agent._dispatch("match_job", {"job_id": "job-001"})
        assert result["score"] == 71
        assert "proactive_suggestion" in result
        assert agent.conversation_memory.get_match_result("job-001") is not None
        print("  ✓ match_job → 主动建议已生成")

        # 测试 recommend_learning
        result = agent._dispatch("recommend_learning", {"job_id": "job-001", "skill_gaps": ["LangChain"]})
        assert "repos" in result
        assert "proactive_suggestion" in result
        print("  ✓ recommend_learning → 推荐建议已生成")

        # 测试 create_learning_plan
        result = agent._dispatch("create_learning_plan", {"job_id": "job-001", "timeframe": "3months"})
        assert result.get("success") is True
        assert "plan" in result
        print("  ✓ create_learning_plan → 学习计划已生成")

        # 测试 compare_jobs（需要2个职位的结果）
        agent._results["job-002"] = {"analysis": MOCK_ANALYSIS, "match": {**MOCK_MATCH, "score": 58}}
        result = agent._dispatch("compare_jobs", {})
        assert result.get("success") is True
        assert len(result["comparison"]) == 2
        # 验证按分数降序排列
        assert result["comparison"][0]["score"] >= result["comparison"][1]["score"]
        print("  ✓ compare_jobs → 对比结果已排序")

    print("\n✅ 场景 5 通过")
    return True


# ── 主测试入口 ────────────────────────────────────────────────────────────

def run_all():
    print("\n" + "=" * 60)
    print("Phase 2 Step 6: 完整集成测试")
    print("=" * 60)

    scenarios = [
        ("单职位深度分析",     test_scenario_single_job),
        ("多职位对比",         test_scenario_multi_job),
        ("追问与上下文理解",   test_scenario_context_followup),
        ("会话持久化与恢复",   test_scenario_session_persistence),
        ("Agent 工具分发",     test_scenario_agent_dispatch),
    ]

    results = []
    for name, fn in scenarios:
        try:
            ok = fn()
            results.append((name, ok))
        except Exception as e:
            import traceback
            print(f"\n❌ {name} 失败: {e}")
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n总计: {passed}/{len(results)} 通过")

    if passed == len(results):
        print("\n🎉 Step 6 全部通过！Phase 2 完成！")
    else:
        print(f"\n⚠️ {len(results) - passed} 个场景失败")

    return passed == len(results)


if __name__ == "__main__":
    success = run_all()
    exit(0 if success else 1)
