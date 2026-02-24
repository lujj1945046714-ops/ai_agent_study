"""
工具定义：将现有模块包装为 Agent 可调用的工具。
每个工具包含：schema（告诉 LLM 怎么调用）+ 实现函数。
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# 确保父目录在 sys.path 中
_BASE = Path(__file__).resolve().parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

import config
import database
import report_generator
from modules import analyze_jd, fetch_jobs, generate_suggestions, match_job, recommend_projects

# ── Tool Schemas（传给 LLM 的函数描述）──────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "搜索符合条件的职位列表，返回职位基本信息（标题、公司、城市、薪资）",
            "parameters": {
                "type": "object",
                "properties": {
                    "cities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "目标城市列表，如 ['上海', '北京']",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "职位关键词，如 ['AI Agent', 'LLM']",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回职位数，默认 10",
                    },
                },
                "required": ["cities", "keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_job",
            "description": "深度分析某个职位的 JD，提取必备技能、技术栈、岗位级别和核心职责",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "职位唯一 ID"},
                    "jd_text": {"type": "string", "description": "职位描述原文"},
                },
                "required": ["job_id", "jd_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_job",
            "description": "计算用户与职位的匹配分数（0-100），找出技能缺口和匹配理由",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "职位唯一 ID"},
                    "analysis": {
                        "type": "object",
                        "description": "analyze_job 返回的分析结果",
                    },
                },
                "required": ["job_id", "analysis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_learning",
            "description": "根据技能缺口推荐 GitHub 开源项目，帮助用户针对性补齐短板",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_gaps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要补充的技能列表，来自 match_job 的 skill_gaps 字段",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "推荐项目数量，默认 3",
                    },
                },
                "required": ["skill_gaps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": "生成最终的 Markdown 求职分析报告并保存到文件。当所有职位分析完成后调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "ranked_jobs": {
                        "type": "array",
                        "description": "已完成分析的职位列表，每项包含 analysis、match、repos、suggestions",
                    }
                },
                "required": ["ranked_jobs"],
            },
        },
    },
]

# ── Tool 实现函数 ────────────────────────────────────────────────────────────

def tool_search_jobs(profile: Dict, cities: List[str], keywords: List[str], max_results: int = 10) -> Dict:
    """搜索职位，返回列表摘要（不含完整 jd_text 以节省 token）"""
    # 临时覆盖 profile 中的偏好
    patched = dict(profile)
    patched["preferences"] = dict(profile.get("preferences", {}))
    patched["preferences"]["cities"] = cities
    patched["target_roles"] = keywords

    jobs = fetch_jobs(patched, max_results=max_results)
    # 只返回摘要，完整 jd_text 留给 analyze_job
    summary = [
        {
            "job_id": j["job_id"],
            "title": j["title"],
            "company": j["company"],
            "city": j["city"],
            "salary": j["salary"],
            "jd_preview": j["jd_text"][:120].strip() + "...",
        }
        for j in jobs
    ]
    return {"count": len(summary), "jobs": summary}


def tool_analyze_job(job_id: str, jd_text: str) -> Dict:
    """分析 JD，返回结构化结果"""
    result = analyze_jd(jd_text)
    return {"job_id": job_id, **result}


def tool_match_job(profile: Dict, job_id: str, analysis: Dict) -> Dict:
    """计算匹配分"""
    result = match_job(profile, analysis)
    return {"job_id": job_id, **result}


def tool_recommend_learning(skill_gaps: List[str], top_n: int = 3) -> Dict:
    """推荐学习项目"""
    repos = recommend_projects(skill_gaps, top_n=top_n)
    return {"skill_gaps": skill_gaps, "repos": repos}


def tool_generate_report(profile: Dict, ranked_jobs: List[Dict], output_dir: Path) -> Dict:
    """生成报告文件"""
    # 补全 suggestions（如果 agent 没有单独调用）
    for job in ranked_jobs:
        if "suggestions" not in job:
            job["suggestions"] = generate_suggestions(
                job.get("analysis", {}),
                job.get("repos", []),
                job.get("match", {}).get("skill_gaps", []),
            )

    ranked_sorted = sorted(ranked_jobs, key=lambda x: x.get("match", {}).get("score", 0), reverse=True)
    report_md = report_generator.generate_markdown(profile, ranked_sorted)

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"report_agent_{ts}.md"
    path.write_text(report_md, encoding="utf-8")

    return {
        "status": "success",
        "report_path": str(path),
        "jobs_analyzed": len(ranked_sorted),
        "top_job": ranked_sorted[0]["title"] if ranked_sorted else "无",
    }
