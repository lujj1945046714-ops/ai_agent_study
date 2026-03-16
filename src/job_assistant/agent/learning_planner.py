"""
学习规划器

功能：
1. 创建3/6/12个月学习计划
2. 按优先级排序技能
3. 设置学习里程碑
4. 推荐学习资源
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta


class LearningPlanner:
    """学习规划器"""

    # 技能学习时间估算（周）
    SKILL_LEARNING_TIME = {
        0: {"to_1": 1, "to_2": 2, "to_3": 4},   # 从 level 0 到各级别
        1: {"to_2": 1, "to_3": 3},              # 从 level 1 到各级别
        2: {"to_3": 2},                         # 从 level 2 到 level 3
    }

    def __init__(self):
        """初始化学习规划器"""
        pass

    # ==================== 创建学习计划 ====================

    def create_plan(
        self,
        skill_gaps: List[Dict[str, Any]],
        timeframe: str = "3months",
        user_level: str = "1-3年"
    ) -> Dict[str, Any]:
        """
        创建学习计划

        Args:
            skill_gaps: 技能缺口列表，格式：
                [
                    {
                        "skill": "LangChain",
                        "required_level": 3,
                        "user_level": 2,
                        "category": "required_skills"
                    }
                ]
            timeframe: 时间框架（"3months", "6months", "12months"）
            user_level: 用户经验水平

        Returns:
            学习计划字典
        """
        # 1. 按优先级排序技能缺口
        sorted_gaps = self._sort_by_priority(skill_gaps)

        # 2. 计算总学习时间
        total_weeks = self._calculate_total_weeks(sorted_gaps)

        # 3. 根据时间框架调整
        available_weeks = self._get_available_weeks(timeframe)

        # 4. 分配学习时间
        phases = self._create_phases(sorted_gaps, available_weeks, timeframe)

        # 5. 生成计划
        return {
            "timeframe": timeframe,
            "total_weeks": available_weeks,
            "estimated_weeks": total_weeks,
            "feasible": total_weeks <= available_weeks,
            "phases": phases,
            "summary": self._create_summary(phases, timeframe),
            "created_at": datetime.now().isoformat()
        }

    def _sort_by_priority(self, skill_gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按优先级排序技能缺口

        优先级规则：
        1. 必备技能 > 技术栈 > 加分项
        2. 差距大的优先（level 0 > level 1 > level 2）
        3. 基础技能优先（Python > 框架）
        """
        # 类别权重
        category_weight = {
            "required_skills": 3,
            "tech_stack": 2,
            "nice_to_have": 1
        }

        # 基础技能列表
        foundation_skills = {"Python", "JavaScript", "Java", "Go", "Git"}

        def priority_score(gap):
            category = gap.get("category", "tech_stack")
            user_level = gap.get("user_level", 0)
            skill = gap.get("skill", "")

            # 类别分数
            cat_score = category_weight.get(category, 1) * 100

            # 差距分数（差距越大，优先级越高）
            gap_score = (3 - user_level) * 10

            # 基础技能加分
            foundation_bonus = 5 if skill in foundation_skills else 0

            return cat_score + gap_score + foundation_bonus

        return sorted(skill_gaps, key=priority_score, reverse=True)

    def _calculate_total_weeks(self, skill_gaps: List[Dict[str, Any]]) -> int:
        """计算总学习时间（周）"""
        total_weeks = 0

        for gap in skill_gaps:
            user_level = gap.get("user_level", 0)
            required_level = gap.get("required_level", 3)

            # 查找学习时间
            if user_level in self.SKILL_LEARNING_TIME:
                time_key = f"to_{required_level}"
                weeks = self.SKILL_LEARNING_TIME[user_level].get(time_key, 4)
                total_weeks += weeks

        return total_weeks

    def _get_available_weeks(self, timeframe: str) -> int:
        """获取可用周数"""
        timeframe_weeks = {
            "3months": 12,
            "6months": 24,
            "12months": 48
        }
        return timeframe_weeks.get(timeframe, 12)

    def _create_phases(
        self,
        skill_gaps: List[Dict[str, Any]],
        available_weeks: int,
        timeframe: str
    ) -> List[Dict[str, Any]]:
        """
        创建学习阶段

        将技能分配到不同阶段
        """
        phases = []

        if timeframe == "3months":
            # 3个月：2个阶段
            phase_count = 2
            phase_names = ["第1-2个月：基础技能", "第3个月：综合实践"]
        elif timeframe == "6months":
            # 6个月：3个阶段
            phase_count = 3
            phase_names = ["第1-2个月：基础技能", "第3-4个月：进阶实践", "第5-6个月：项目实战"]
        else:
            # 12个月：4个阶段
            phase_count = 4
            phase_names = [
                "第1-3个月：基础技能",
                "第4-6个月：进阶实践",
                "第7-9个月：项目实战",
                "第10-12个月：优化提升"
            ]

        # 分配技能到各阶段
        skills_per_phase = len(skill_gaps) // phase_count + 1

        for i in range(phase_count):
            start_idx = i * skills_per_phase
            end_idx = min((i + 1) * skills_per_phase, len(skill_gaps))
            phase_skills = skill_gaps[start_idx:end_idx]

            if not phase_skills:
                continue

            phase = {
                "name": phase_names[i] if i < len(phase_names) else f"阶段 {i+1}",
                "skills": self._create_skill_items(phase_skills),
                "duration_weeks": available_weeks // phase_count,
                "goals": self._create_phase_goals(phase_skills)
            }

            phases.append(phase)

        return phases

    def _create_skill_items(self, skill_gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """创建技能学习项"""
        items = []

        for gap in skill_gaps:
            skill = gap.get("skill", "")
            user_level = gap.get("user_level", 0)
            required_level = gap.get("required_level", 3)

            # 学习时间
            if user_level in self.SKILL_LEARNING_TIME:
                time_key = f"to_{required_level}"
                weeks = self.SKILL_LEARNING_TIME[user_level].get(time_key, 4)
            else:
                weeks = 4

            # 学习目标
            level_names = {
                0: "未接触",
                1: "了解概念",
                2: "基础使用",
                3: "熟练掌握",
                4: "深度实践",
                5: "专家级别"
            }

            item = {
                "skill": skill,
                "current_level": user_level,
                "target_level": required_level,
                "current_level_name": level_names.get(user_level, "未知"),
                "target_level_name": level_names.get(required_level, "未知"),
                "estimated_weeks": weeks,
                "learning_path": self._create_learning_path(skill, user_level, required_level),
                "milestones": self._create_milestones(skill, user_level, required_level)
            }

            items.append(item)

        return items

    def _create_learning_path(self, skill: str, current: int, target: int) -> List[str]:
        """创建学习路径"""
        paths = []

        if current == 0:
            paths.append(f"📖 学习 {skill} 基础概念和核心原理")
            paths.append(f"💻 跑通官方示例和教程")

        if current <= 1 and target >= 2:
            paths.append(f"🔨 完成 2-3 个简单项目")
            paths.append(f"📚 阅读官方文档和最佳实践")

        if current <= 2 and target >= 3:
            paths.append(f"🚀 独立完成 1-2 个完整项目")
            paths.append(f"🐛 解决实际问题，积累经验")
            paths.append(f"📝 总结项目经验，形成知识体系")

        return paths

    def _create_milestones(self, skill: str, current: int, target: int) -> List[str]:
        """创建里程碑"""
        milestones = []

        if current == 0:
            milestones.append(f"✓ 理解 {skill} 的核心概念")
            milestones.append(f"✓ 能够运行基础示例")

        if current <= 1 and target >= 2:
            milestones.append(f"✓ 能够独立编写简单代码")
            milestones.append(f"✓ 完成 2 个练习项目")

        if current <= 2 and target >= 3:
            milestones.append(f"✓ 独立完成 1 个完整项目")
            milestones.append(f"✓ 能够解决常见问题")
            milestones.append(f"✓ 可以在简历中展示")

        return milestones

    def _create_phase_goals(self, skill_gaps: List[Dict[str, Any]]) -> List[str]:
        """创建阶段目标"""
        skills = [gap.get("skill", "") for gap in skill_gaps]
        return [
            f"掌握 {', '.join(skills[:3])}{'等技能' if len(skills) > 3 else ''}",
            f"完成 {len(skills)} 个技能的学习目标",
            "积累项目经验，可在简历中展示"
        ]

    def _create_summary(self, phases: List[Dict[str, Any]], timeframe: str) -> str:
        """创建计划摘要"""
        total_skills = sum(len(phase["skills"]) for phase in phases)

        summary = f"📅 {timeframe.replace('months', '个月')}学习计划\n\n"
        summary += f"共 {len(phases)} 个阶段，涵盖 {total_skills} 个技能。\n\n"

        for i, phase in enumerate(phases, 1):
            summary += f"阶段 {i}: {phase['name']}\n"
            skills = [s["skill"] for s in phase["skills"]]
            summary += f"  技能: {', '.join(skills)}\n"
            summary += f"  时长: {phase['duration_weeks']} 周\n\n"

        return summary

    # ==================== 格式化输出 ====================

    def format_plan(self, plan: Dict[str, Any]) -> str:
        """
        格式化学习计划为文本

        Args:
            plan: 学习计划字典

        Returns:
            格式化的文本
        """
        lines = []

        # 标题
        timeframe_text = plan["timeframe"].replace("months", "个月")
        lines.append(f"📅 {timeframe_text}学习计划")
        lines.append("=" * 50)
        lines.append("")

        # 可行性
        if not plan["feasible"]:
            lines.append(f"⚠️ 注意：预计需要 {plan['estimated_weeks']} 周，但只有 {plan['total_weeks']} 周可用。")
            lines.append("建议：适当延长时间或聚焦核心技能。")
            lines.append("")

        # 各阶段
        for i, phase in enumerate(plan["phases"], 1):
            lines.append(f"## {phase['name']}")
            lines.append(f"⏱️ 时长：{phase['duration_weeks']} 周")
            lines.append("")

            # 阶段目标
            lines.append("🎯 阶段目标：")
            for goal in phase["goals"]:
                lines.append(f"  • {goal}")
            lines.append("")

            # 技能学习
            for skill_item in phase["skills"]:
                lines.append(f"### {skill_item['skill']}")
                lines.append(f"📊 当前：{skill_item['current_level_name']} (level {skill_item['current_level']})")
                lines.append(f"🎯 目标：{skill_item['target_level_name']} (level {skill_item['target_level']})")
                lines.append(f"⏱️ 预计：{skill_item['estimated_weeks']} 周")
                lines.append("")

                # 学习路径
                lines.append("📚 学习路径：")
                for path in skill_item["learning_path"]:
                    lines.append(f"  {path}")
                lines.append("")

                # 里程碑
                lines.append("✅ 里程碑：")
                for milestone in skill_item["milestones"]:
                    lines.append(f"  {milestone}")
                lines.append("")

            lines.append("-" * 50)
            lines.append("")

        # 总结
        lines.append("## 💡 学习建议")
        lines.append("")
        lines.append("1. **保持节奏**：每周投入 10-15 小时学习")
        lines.append("2. **动手实践**：理论结合实践，多写代码")
        lines.append("3. **记录总结**：写学习笔记，整理项目经验")
        lines.append("4. **寻求反馈**：加入社区，参与开源项目")
        lines.append("5. **定期回顾**：每月回顾进度，调整计划")
        lines.append("")

        return "\n".join(lines)

    # ==================== 快速计划 ====================

    def create_quick_plan(self, skill_gaps: List[Dict[str, Any]]) -> str:
        """
        创建快速学习计划（简化版）

        Args:
            skill_gaps: 技能缺口列表

        Returns:
            简化的学习计划文本
        """
        sorted_gaps = self._sort_by_priority(skill_gaps)

        lines = ["📚 快速学习建议", "=" * 50, ""]

        for i, gap in enumerate(sorted_gaps[:5], 1):  # 只显示前5个
            skill = gap.get("skill", "")
            user_level = gap.get("user_level", 0)
            required_level = gap.get("required_level", 3)
            category = gap.get("category", "")

            # 优先级标签
            priority = "🔴 高优先级" if category == "required_skills" else "🟡 中优先级"

            lines.append(f"{i}. {skill} {priority}")
            lines.append(f"   当前 level {user_level} → 目标 level {required_level}")

            # 学习建议
            if user_level == 0:
                lines.append(f"   💡 从零开始，建议先学习基础概念和官方教程")
            elif user_level == 1:
                lines.append(f"   💡 已了解概念，建议多做练习项目")
            elif user_level == 2:
                lines.append(f"   💡 已有基础，建议完成1-2个完整项目")

            lines.append("")

        return "\n".join(lines)
