from datetime import datetime
from typing import Any, Dict, List


def _line_list(items: List[str], fallback: str = "无") -> str:
    if not items:
        return fallback
    return " / ".join(items)


def generate_markdown(user_profile: Dict[str, Any], ranked_jobs: List[Dict[str, Any]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []

    lines.append("# AI 求职助手分析报告")
    lines.append("")
    lines.append(f"- 生成时间：{now}")
    lines.append(f"- 分析职位数：{len(ranked_jobs)}")
    lines.append("")

    lines.append("## 用户画像")
    lines.append("")
    lines.append(f"- 经验阶段：{user_profile.get('experience_level', '未知')}")
    lines.append(f"- 目标岗位：{_line_list(user_profile.get('target_roles', []))}")
    prefs = user_profile.get("preferences", {})
    lines.append(f"- 城市偏好：{_line_list(prefs.get('cities', []))}")
    lines.append(f"- 薪资偏好：{prefs.get('salary_min_k', 0)}k - {prefs.get('salary_max_k', 0)}k")
    lines.append("")

    lines.append("## Top 职位结果")
    lines.append("")

    if not ranked_jobs:
        lines.append("当前没有可展示结果，请先运行主流程生成分析数据。")
        lines.append("")
        return "\n".join(lines)

    for index, job in enumerate(ranked_jobs, start=1):
        analysis = job.get("analysis", {})
        match = job.get("match", {})
        repos = job.get("repos", [])
        suggestions = job.get("suggestions", [])

        lines.append(f"### {index}. {job['title']} | {job['company']} | {job['city']} | {job['salary']}")
        lines.append("")
        lines.append(f"- 匹配分：{match.get('score', 0)}")
        lines.append(f"- 岗位总结：{analysis.get('summary', '无')}")
        lines.append(f"- 必备技能：{_line_list(analysis.get('required_skills', []))}")
        lines.append(f"- 技能缺口：{_line_list(match.get('skill_gaps', []), '当前无明显缺口')}")
        lines.append(f"- 匹配理由：{_line_list(match.get('match_reasons', []))}")
        lines.append("")

        lines.append("推荐项目：")
        if repos:
            for repo in repos:
                lines.append(
                    f"- {repo['name']} ({repo['stars']} stars) | 难度: {repo['difficulty']} | 预计时间: {repo['time_estimate']}"
                )
                lines.append(f"  - {repo['url']}")
                lines.append(f"  - 推荐理由：{repo['reason']}")
        else:
            lines.append("- 无")
        lines.append("")

        lines.append("改进建议：")
        if suggestions:
            for suggestion in suggestions:
                lines.append(f"- 方向：{suggestion['direction']}")
                lines.append(f"  - 技术深度：{suggestion['technical_depth']}")
                lines.append(f"  - 相关性：{suggestion['why_relevant']}")
        else:
            lines.append("- 无")
        lines.append("")

    return "\n".join(lines)
