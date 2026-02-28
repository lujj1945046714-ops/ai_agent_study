"""
测试增强版匹配器的完整集成
"""
import json
from pathlib import Path
import config
from agent.react_agent import JobSearchAgent

# 测试用例 1: 新格式用户画像（中等熟练度）
enhanced_profile = {
    "name": "增强版测试用户",
    "experience_level": "1-3年",
    "skills": {
        "Python": {"level": 3, "years": 2, "projects": ["Web应用", "数据分析"]},
        "LangChain": {"level": 2, "years": 0.5, "projects": ["学习项目"]},
        "FastAPI": {"level": 3, "years": 1.5, "projects": ["API服务"]},
        "Git": {"level": 3, "years": 2},
        "LLM API调用": {"level": 3, "years": 1, "projects": ["聊天机器人"]}
    },
    "target_roles": ["AI Agent 工程师"],
    "preferences": {
        "cities": ["上海"],
        "salary_min_k": 20,
        "salary_max_k": 35
    }
}

# 测试 JD
test_jobs = [
    {
        "job_id": "enhanced-001",
        "title": "AI Agent 工程师",
        "company": "增强版测试公司",
        "city": "上海",
        "salary": "25-35k",
        "jd_text": """
岗位职责：
- 负责基于 LLM 的 Agent 工作流设计与开发
- 设计并实现多 Agent 协作与任务编排能力
- 优化 Agent 推理效率和响应速度

任职要求：
- 熟练掌握 Python，有 FastAPI 或 Flask 开发经验
- 熟悉 LangChain、AutoGen 等 Agent 框架
- 了解 RAG、Function Calling 等技术
- 有 LLM API 集成经验（OpenAI、DeepSeek 等）
- 熟悉 Git 版本控制和团队协作
"""
    }
]

def test_enhanced_integration():
    """测试增强版匹配器的完整集成"""
    print("\n=== 测试增强版匹配器集成 ===\n")

    base_dir = Path(__file__).resolve().parent
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    agent = JobSearchAgent(
        user_profile=enhanced_profile,
        name="增强版测试用户",
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        model=config.DEEPSEEK_MODEL,
        output_dir=output_dir,
    )

    # 预加载测试 JD
    agent.preload_jobs(test_jobs)

    # 运行 Agent
    try:
        summary = agent.run("帮我分析这个职位并推荐学习项目")
        print("\n=== Agent 总结 ===")
        print(summary)

        # 检查匹配结果
        print("\n=== 匹配结果详情 ===")
        for job_id, data in agent._results.items():
            match_result = data.get("match", {})
            print(f"\n职位: {job_id}")
            print(f"匹配分数: {match_result.get('score', 0)}/100")

            # 检查是否有详细信息（增强版特有）
            if "matched_skills_detailed" in match_result:
                print("\n✅ 增强版匹配器已启用")
                print("\n已匹配技能（详细）:")
                for m in match_result.get("matched_skills_detailed", [])[:3]:
                    print(f"  • {m['skill']} ({m['category']})")
                    print(f"    用户水平: level {m['user_level']}")
                    print(f"    匹配质量: {m['match_quality']}")

                print("\n技能缺口（详细）:")
                for g in match_result.get("skill_gaps_detailed", [])[:3]:
                    print(f"  • {g['skill']} ({g['category']})")
                    print(f"    要求: level {g['required_level']}")
                    print(f"    当前: level {g['user_level']}")
                    print(f"    差距: {g['gap_desc']}")
            else:
                print("\n⚠️ 使用的是旧版匹配器")

        print("\n测试通过 ✓")
        return True
    except Exception as e:
        print(f"\n测试失败 ✗: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_enhanced_integration()
    exit(0 if success else 1)
