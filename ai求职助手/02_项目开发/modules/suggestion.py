import logging
import sys
import os
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

_SUGGESTION_PROMPT = """你是一个 AI 求职顾问。根据以下信息，给出 3 条具体可执行的学习建议。

## 目标岗位分析
- 核心职责：{core_work}
- 必备技能：{required_skills}
- 技能缺口（用户还不具备）：{skill_gaps}

## 推荐项目：{repo_name}
{readme_content}

## 要求
严格按以下 JSON 格式输出，不要有任何额外内容：
[
  {{
    "direction": "具体学习方向（一句话）",
    "technical_depth": "怎么做（结合项目的具体操作）",
    "why_relevant": "为什么对求职有帮助"
  }}
]

建议要结合项目的实际内容，不要泛泛而谈。"""


def _llm_suggestions(analysis: Dict, repo: Dict, skill_gaps: List[str]) -> List[Dict[str, str]]:
    try:
        import config
        from openai import OpenAI
        if not config.DEEPSEEK_API_KEY:
            return []
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

        from modules.github_recommender import fetch_readme
        readme = fetch_readme(repo["name"])
        if not readme:
            return []

        prompt = _SUGGESTION_PROMPT.format(
            core_work="、".join(analysis.get("core_work", [])[:3]),
            required_skills="、".join(analysis.get("required_skills", [])[:5]),
            skill_gaps="、".join(skill_gaps[:5]) or "无明显缺口",
            repo_name=repo["name"],
            readme_content=readme,
        )

        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        import json
        raw = resp.choices[0].message.content
        result = json.loads(raw)
        # 兼容返回列表或包裹在 key 里的情况
        if isinstance(result, list):
            return result[:3]
        for v in result.values():
            if isinstance(v, list):
                return v[:3]
    except Exception as e:
        logger.warning("LLM 建议生成失败，降级到模板: %s", e)
    return []


def generate_suggestions(
    analysis: Dict,
    repos: List[Dict],
    skill_gaps: List[str],
) -> List[Dict[str, str]]:
    # 优先用 LLM + README 生成建议
    if repos:
        llm_result = _llm_suggestions(analysis, repos[0], skill_gaps)
        if llm_result:
            return llm_result

    # 降级：模板生成
    suggestions: List[Dict[str, str]] = []
    core_work = analysis.get("core_work", [])

    for gap in skill_gaps[:2]:
        suggestions.append({
            "direction": f"围绕 {gap} 设计可验证的子模块",
            "technical_depth": "加入可观测指标（成功率、延迟、错误率）并做对比实验",
            "why_relevant": f"直接对应岗位技能缺口 {gap}，可在简历中形成闭环证据",
        })

    if core_work:
        suggestions.append({
            "direction": f"把职责「{core_work[0]}」拆成可复用流程编排",
            "technical_depth": "实现分层架构：输入解析、任务规划、执行器、结果评估",
            "why_relevant": "体现你对 Agent 系统设计而非单点调用的理解",
        })

    if repos:
        suggestions.append({
            "direction": f"二次开发 {repos[0]['name']} 的核心链路",
            "technical_depth": "增加失败重试、缓存和日志追踪，展示工程化能力",
            "why_relevant": "与推荐仓库直接关联，便于快速落地和演示",
        })

    return suggestions[:3]
