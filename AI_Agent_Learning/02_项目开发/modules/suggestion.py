from typing import Dict, List


def generate_suggestions(
    analysis: Dict,
    repos: List[Dict],
    skill_gaps: List[str],
) -> List[Dict[str, str]]:
    suggestions: List[Dict[str, str]] = []
    core_work = analysis.get("core_work", [])

    if skill_gaps:
        for gap in skill_gaps[:2]:
            suggestions.append(
                {
                    "direction": f"围绕 {gap} 设计可验证的子模块",
                    "technical_depth": "加入可观测指标（成功率、延迟、错误率）并做对比实验",
                    "why_relevant": f"直接对应岗位技能缺口 {gap}，可在简历中形成闭环证据",
                }
            )

    if core_work:
        suggestions.append(
            {
                "direction": f"把职责“{core_work[0]}”拆成可复用流程编排",
                "technical_depth": "实现分层架构：输入解析、任务规划、执行器、结果评估",
                "why_relevant": "体现你对 Agent 系统设计而非单点调用的理解",
            }
        )

    if repos:
        top_repo = repos[0]
        suggestions.append(
            {
                "direction": f"二次开发 {top_repo['name']} 的核心链路",
                "technical_depth": "增加失败重试、缓存和日志追踪，展示工程化能力",
                "why_relevant": "与推荐仓库直接关联，便于快速落地和演示",
            }
        )

    return suggestions[:3]
