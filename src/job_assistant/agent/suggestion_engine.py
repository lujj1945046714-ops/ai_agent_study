"""
主动建议引擎

功能：
1. 分析后建议（根据匹配度）
2. 推荐后建议
3. 多职位对比建议
4. 智能提问
"""

from typing import Dict, List, Any, Optional


class ProactiveSuggestionEngine:
    """主动建议引擎"""

    def __init__(self):
        """初始化建议引擎"""
        pass

    # ==================== 分析后建议 ====================

    def suggest_after_analysis(
        self,
        job_id: str,
        job_title: str,
        match_score: int,
        skill_gaps: List[str],
        matched_skills: List[str]
    ) -> Dict[str, Any]:
        """
        职位分析后的建议

        Args:
            job_id: 职位ID
            job_title: 职位标题
            match_score: 匹配分数
            skill_gaps: 技能缺口列表
            matched_skills: 已匹配技能列表

        Returns:
            建议字典
        """
        if match_score < 50:
            return self._suggest_low_match(job_title, match_score, skill_gaps)
        elif match_score < 70:
            return self._suggest_medium_match(job_title, match_score, skill_gaps)
        elif match_score < 85:
            return self._suggest_good_match(job_title, match_score, skill_gaps)
        else:
            return self._suggest_high_match(job_title, match_score)

    def _suggest_low_match(self, job_title: str, score: int, gaps: List[str]) -> Dict[str, Any]:
        """低匹配度建议（< 50分）"""
        gap_text = "、".join(gaps[:3])
        if len(gaps) > 3:
            gap_text += f" 等{len(gaps)}个技能"

        return {
            "level": "low",
            "message": f"📊 匹配度较低（{score}分）\n\n主要技能缺口：{gap_text}\n\n这个职位可能需要较长时间准备。",
            "suggestions": [
                {
                    "action": "recommend_learning",
                    "label": "📚 推荐学习项目（长期准备）",
                    "description": "为你推荐 GitHub 项目来系统学习缺失技能"
                },
                {
                    "action": "create_long_plan",
                    "label": "📅 制定6-12个月学习计划",
                    "description": "制定长期学习路线图"
                },
                {
                    "action": "search_more",
                    "label": "🔍 搜索更匹配的职位",
                    "description": "寻找更适合当前技能水平的职位"
                }
            ]
        }

    def _suggest_medium_match(self, job_title: str, score: int, gaps: List[str]) -> Dict[str, Any]:
        """中等匹配度建议（50-70分）"""
        gap_text = "、".join(gaps[:3])

        return {
            "level": "medium",
            "message": f"📊 匹配度中等（{score}分）\n\n主要技能缺口：{gap_text}\n\n通过针对性学习，有机会达到要求。",
            "suggestions": [
                {
                    "action": "recommend_learning",
                    "label": "📚 推荐学习项目",
                    "description": "为你推荐针对性的学习项目"
                },
                {
                    "action": "create_plan",
                    "label": "📅 制定3个月学习计划",
                    "description": "制定短期冲刺计划"
                },
                {
                    "action": "continue_search",
                    "label": "🔍 继续分析其他职位",
                    "description": "对比更多职位，找到最佳选择"
                }
            ]
        }

    def _suggest_good_match(self, job_title: str, score: int, gaps: List[str]) -> Dict[str, Any]:
        """良好匹配度建议（70-85分）"""
        gap_text = "、".join(gaps) if gaps else "无明显缺口"

        return {
            "level": "good",
            "message": f"✅ 匹配度良好（{score}分）\n\n小幅提升空间：{gap_text}\n\n你已经具备大部分要求，稍作准备即可投递！",
            "suggestions": [
                {
                    "action": "recommend_learning",
                    "label": "📚 推荐学习项目（查漏补缺）",
                    "description": "针对小缺口进行快速提升"
                },
                {
                    "action": "prepare_interview",
                    "label": "🎯 准备面试",
                    "description": "整理项目经验，准备技术问题"
                },
                {
                    "action": "optimize_resume",
                    "label": "📝 优化简历",
                    "description": "针对这个职位优化简历"
                }
            ]
        }

    def _suggest_high_match(self, job_title: str, score: int) -> Dict[str, Any]:
        """高匹配度建议（>= 85分）"""
        return {
            "level": "high",
            "message": f"🎉 匹配度很高（{score}分）\n\n你的技能非常符合要求，建议尽快投递！",
            "suggestions": [
                {
                    "action": "prepare_interview",
                    "label": "🎯 准备面试",
                    "description": "整理项目经验，准备常见面试问题"
                },
                {
                    "action": "optimize_resume",
                    "label": "📝 优化简历",
                    "description": "突出匹配的技能和项目经验"
                },
                {
                    "action": "research_company",
                    "label": "🏢 了解公司背景",
                    "description": "研究公司文化、产品和团队"
                }
            ]
        }

    # ==================== 推荐后建议 ====================

    def suggest_after_recommendation(
        self,
        job_title: str,
        recommended_count: int,
        total_gaps: int
    ) -> Dict[str, Any]:
        """
        项目推荐后的建议

        Args:
            job_title: 职位标题
            recommended_count: 已推荐项目数
            total_gaps: 总技能缺口数

        Returns:
            建议字典
        """
        return {
            "message": f"已为你推荐 {recommended_count} 个学习项目。",
            "suggestions": [
                {
                    "action": "recommend_more",
                    "label": "🔄 再推荐几个项目",
                    "description": "获取更多学习资源"
                },
                {
                    "action": "create_plan",
                    "label": "📅 制定学习计划",
                    "description": "基于这些项目制定详细的学习路线"
                },
                {
                    "action": "continue_search",
                    "label": "🔍 继续分析其他职位",
                    "description": "看看其他职位的要求"
                }
            ]
        }

    # ==================== 多职位对比建议 ====================

    def suggest_job_comparison(self, job_count: int) -> Dict[str, Any]:
        """
        多职位对比建议

        Args:
            job_count: 已分析职位数

        Returns:
            建议字典
        """
        if job_count < 2:
            return {
                "message": "目前只分析了1个职位。",
                "suggestions": [
                    {
                        "action": "search_more",
                        "label": "🔍 搜索更多职位",
                        "description": "分析更多职位以便对比"
                    }
                ]
            }

        return {
            "message": f"已分析 {job_count} 个职位。",
            "suggestions": [
                {
                    "action": "compare_jobs",
                    "label": "📊 对比所有职位",
                    "description": "生成对比表格，找出最佳选择"
                },
                {
                    "action": "recommend_best",
                    "label": "⭐ 推荐最佳职位",
                    "description": "基于匹配度和发展前景推荐"
                }
            ]
        }

    # ==================== 智能提问 ====================

    def ask_clarification(self, context: str) -> Dict[str, Any]:
        """
        智能提问（当意图不明确时）

        Args:
            context: 当前上下文

        Returns:
            问题字典
        """
        return {
            "message": "我可以帮你：",
            "options": [
                {
                    "action": "analyze_job",
                    "label": "🔍 分析职位",
                    "description": "分析职位要求和技能匹配度"
                },
                {
                    "action": "recommend_learning",
                    "label": "📚 推荐学习项目",
                    "description": "推荐 GitHub 项目来提升技能"
                },
                {
                    "action": "create_plan",
                    "label": "📅 制定学习计划",
                    "description": "制定系统的学习路线图"
                },
                {
                    "action": "compare_jobs",
                    "label": "📊 对比职位",
                    "description": "对比已分析的职位"
                }
            ]
        }

    # ==================== 格式化输出 ====================

    def format_suggestion(self, suggestion: Dict[str, Any]) -> str:
        """
        格式化建议为文本

        Args:
            suggestion: 建议字典

        Returns:
            格式化的文本
        """
        lines = [suggestion["message"], ""]

        if "suggestions" in suggestion:
            lines.append("💡 建议：")
            for i, sug in enumerate(suggestion["suggestions"], 1):
                lines.append(f"{i}. {sug['label']}")
                lines.append(f"   {sug['description']}")
                lines.append("")

        if "options" in suggestion:
            lines.append("请选择：")
            for i, opt in enumerate(suggestion["options"], 1):
                lines.append(f"{i}. {opt['label']}")
                lines.append(f"   {opt['description']}")
                lines.append("")

        return "\n".join(lines)

    # ==================== 上下文感知建议 ====================

    def suggest_next_action(
        self,
        last_action: Optional[str],
        analyzed_jobs_count: int,
        has_recommendations: bool
    ) -> Dict[str, Any]:
        """
        基于上下文建议下一步操作

        Args:
            last_action: 最近的操作
            analyzed_jobs_count: 已分析职位数
            has_recommendations: 是否已有推荐

        Returns:
            建议字典
        """
        if last_action == "analyze_job":
            return {
                "message": "职位分析完成。接下来你可以：",
                "suggestions": [
                    {
                        "action": "recommend_learning",
                        "label": "📚 推荐学习项目",
                        "description": "获取针对性的学习资源"
                    },
                    {
                        "action": "search_more",
                        "label": "🔍 分析更多职位",
                        "description": "对比不同职位的要求"
                    }
                ]
            }

        if last_action == "match_job" and not has_recommendations:
            return {
                "message": "匹配分析完成。要不要：",
                "suggestions": [
                    {
                        "action": "recommend_learning",
                        "label": "📚 推荐学习项目",
                        "description": "针对技能缺口推荐项目"
                    }
                ]
            }

        if last_action == "recommend_projects":
            return {
                "message": "项目推荐完成。你可以：",
                "suggestions": [
                    {
                        "action": "recommend_more",
                        "label": "🔄 再推荐几个",
                        "description": "获取更多学习资源"
                    },
                    {
                        "action": "create_plan",
                        "label": "📅 制定学习计划",
                        "description": "规划学习路线"
                    }
                ]
            }

        # 默认建议
        return self.ask_clarification("")
