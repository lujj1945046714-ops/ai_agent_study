from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_framework.tools.base import BaseTool

from job_assistant import report_generator
from job_assistant.agent.conversation_memory import ConversationMemory
from job_assistant.agent.learning_planner import LearningPlanner
from job_assistant.agent.state import JobAssistantState
from job_assistant.agent.suggestion_engine import ProactiveSuggestionEngine
from job_assistant.job_discovery import JobDiscoveryService
from job_assistant.modules import analyze_jd, generate_suggestions, match_job, smart_recommend_projects
from job_assistant.modules.scraper import fetch_jobs
from job_assistant.repo_audit import audit_repository


def _jd_preview(text: str, limit: int = 120) -> str:
    preview = " ".join((text or "").split())
    if len(preview) <= limit:
        return preview
    return preview[:limit].strip() + "..."


class SearchJobsTool(BaseTool):
    def __init__(self, state: JobAssistantState):
        self._state = state

    @property
    def name(self) -> str:
        return "search_jobs"

    @property
    def description(self) -> str:
        return "搜索符合条件的职位列表，返回职位基本信息（标题、公司、城市、薪资）"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cities": {"type": "array", "items": {"type": "string"}, "description": "目标城市列表"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "职位关键词列表"},
                "max_results": {"type": "integer", "description": "最多返回职位数，默认 10"},
            },
            "required": ["cities", "keywords"],
        }

    def execute(self, *, cities: List[str], keywords: List[str], max_results: int = 10) -> Dict[str, Any]:
        patched = dict(self._state.profile)
        patched["preferences"] = dict(self._state.profile.get("preferences", {}))
        patched["preferences"]["cities"] = cities
        patched["target_roles"] = keywords

        full_jobs = fetch_jobs(patched, max_results=max_results)
        for job in full_jobs:
            self._state.job_store[job["job_id"]] = job

        summary = [
            {
                "job_id": j["job_id"],
                "title": j["title"],
                "company": j["company"],
                "city": j["city"],
                "salary": j["salary"],
                "jd_preview": _jd_preview(j.get("jd_text", "")),
            }
            for j in full_jobs
        ]
        return {"count": len(summary), "jobs": summary}


class DiscoverJobsTool(BaseTool):
    def __init__(self, state: JobAssistantState, store: Any, memory: Optional[ConversationMemory] = None):
        self._state = state
        self._store = store
        self._memory = memory
        self._service = JobDiscoveryService(store=store)

    @property
    def name(self) -> str:
        return "discover_jobs"

    @property
    def description(self) -> str:
        return "基于用户画像自主搜索公开岗位页面，抽取 JD、去重、打分并返回 shortlist"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cities": {"type": "array", "items": {"type": "string"}, "description": "目标城市列表，可选，默认从画像读取"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "岗位关键词列表，可选，默认从画像扩展"},
                "salary_min_k": {"type": "integer", "description": "最低薪资，单位 k，可选"},
                "salary_max_k": {"type": "integer", "description": "最高薪资，单位 k，可选"},
                "max_results": {"type": "integer", "description": "最多返回 shortlist 数量，默认 10，上限 10"},
                "refresh": {"type": "boolean", "description": "是否强制刷新公开岗位搜索，默认 false"},
            },
            "required": [],
        }

    def execute(
        self,
        *,
        cities: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        salary_min_k: Optional[int] = None,
        salary_max_k: Optional[int] = None,
        max_results: int = 10,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        result = self._service.discover(
            self._state.profile,
            cities=cities,
            keywords=keywords,
            salary_min_k=salary_min_k,
            salary_max_k=salary_max_k,
            max_results=max_results,
            refresh=refresh,
        )

        shortlist = result.get("shortlist", [])
        self._state.discovery_runs[result.get("run_id") or "latest"] = result

        for job in shortlist:
            job_id = job.get("job_id", "")
            if not job_id:
                continue
            self._state.job_store[job_id] = {
                "job_id": job_id,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "city": job.get("city", ""),
                "salary": job.get("salary", ""),
                "jd_text": job.get("jd_text", ""),
                "source": job.get("source", ""),
                "source_url": job.get("source_url", ""),
                "post_time": job.get("post_time", ""),
            }
            self._state.discovered_jobs[job_id] = job
            self._state.results.setdefault(job_id, {})["analysis"] = {"job_id": job_id, **job.get("analysis", {})}
            self._state.results.setdefault(job_id, {})["match"] = {"job_id": job_id, **job.get("match", {})}

        if self._memory is not None:
            if cities:
                self._memory.update_user_preference("preferred_cities", cities)
            if keywords:
                self._memory.update_user_preference("preferred_keywords", keywords)

        return result


class AnalyzeJobTool(BaseTool):
    def __init__(self, state: JobAssistantState, memory: Optional[ConversationMemory] = None):
        self._state = state
        self._memory = memory

    @property
    def name(self) -> str:
        return "analyze_job"

    @property
    def description(self) -> str:
        return "深度分析某个职位的 JD，提取必备技能、技术栈、岗位级别和核心职责"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "职位唯一 ID"},
                "jd_text": {"type": "string", "description": "职位描述原文（可选，默认从已加载职位读取）"},
            },
            "required": ["job_id"],
        }

    def execute(self, *, job_id: str, jd_text: str = "") -> Dict[str, Any]:
        existing = self._state.results.get(job_id, {}).get("analysis")
        if existing:
            return existing

        stored = self._state.job_store.get(job_id, {})
        jd_text = jd_text or stored.get("jd_text", "")
        result = {"job_id": job_id, **analyze_jd(jd_text)}

        self._state.results.setdefault(job_id, {})["analysis"] = result

        if self._memory is not None:
            self._memory.add_job_analysis(
                job_id,
                {
                    "title": stored.get("title"),
                    "company": stored.get("company"),
                    "city": stored.get("city"),
                    "salary": stored.get("salary"),
                },
                result,
            )

        return result


class MatchJobTool(BaseTool):
    def __init__(self, state: JobAssistantState, memory: Optional[ConversationMemory] = None):
        self._state = state
        self._memory = memory
        self._suggestion_engine = ProactiveSuggestionEngine()

    @property
    def name(self) -> str:
        return "match_job"

    @property
    def description(self) -> str:
        return "计算用户与职位的匹配分数（0-100），找出技能缺口和匹配理由"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "职位唯一 ID"},
                "analysis": {"type": "object", "description": "analyze_job 返回的分析结果（可选）"},
            },
            "required": ["job_id"],
        }

    def execute(self, *, job_id: str, analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        analysis = analysis or self._state.results.get(job_id, {}).get("analysis", {})
        result = {"job_id": job_id, **match_job(self._state.profile, analysis)}

        self._state.results.setdefault(job_id, {})["match"] = result

        if result.get("score", 0) < 25:
            self._state.results[job_id]["repos"] = []
            result["recommend_learning_skipped"] = True
            result["skip_reason"] = "匹配分低于25，已自动跳过学习推荐"

        if self._memory is not None:
            self._memory.add_match_result(job_id, result)

        job = self._state.job_store.get(job_id, {})
        suggestion = self._suggestion_engine.suggest_after_analysis(
            job_id,
            job.get("title", ""),
            int(result.get("score", 0) or 0),
            list(result.get("skill_gaps", []) or []),
            list(result.get("matched_skills", []) or []),
        )
        result["proactive_suggestion"] = self._suggestion_engine.format_suggestion(suggestion)

        return result


class RecommendLearningTool(BaseTool):
    def __init__(self, state: JobAssistantState, memory: Optional[ConversationMemory] = None):
        self._state = state
        self._memory = memory
        self._suggestion_engine = ProactiveSuggestionEngine()

    @property
    def name(self) -> str:
        return "recommend_learning"

    @property
    def description(self) -> str:
        return "根据技能缺口推荐 GitHub 开源项目，帮助用户针对性补齐短板。支持交互式重规划。"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "职位唯一 ID，用于关联推荐结果"},
                "skill_gaps": {"type": "array", "items": {"type": "string"}, "description": "需要补充的技能列表"},
                "top_n": {"type": "integer", "description": "推荐项目数量，默认 3"},
                "user_choice": {
                    "type": "string",
                    "description": "用户对重规划的选择（replan/lower_stars/use_local），仅在 need_replan 后使用",
                },
                "retry_context": {"type": "object", "description": "重试上下文，从上次 need_replan 响应中获取"},
                "audit_top_repo": {"type": "boolean", "description": "是否对推荐结果中的第一个仓库做下载-运行-清理审计"},
                "audit_expected_capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "审计时重点核对的能力标签，例如 agent/cli/api/rag",
                },
                "audit_allow_light_run": {"type": "boolean", "description": "审计时是否允许轻量运行验证"},
                "audit_keep_workspace": {"type": "boolean", "description": "审计后是否保留下载和依赖工作区"},
            },
            "required": ["job_id", "skill_gaps"],
        }

    def execute(
        self,
        *,
        job_id: str,
        skill_gaps: List[str],
        top_n: int = 3,
        user_choice: Optional[str] = None,
        retry_context: Optional[Dict[str, Any]] = None,
        audit_top_repo: bool = False,
        audit_expected_capabilities: Optional[List[str]] = None,
        audit_allow_light_run: bool = True,
        audit_keep_workspace: bool = False,
    ) -> Dict[str, Any]:
        analysis = self._state.results.get(job_id, {}).get("analysis", {})

        result = smart_recommend_projects(
            skill_gaps,
            profile=self._state.profile,
            analysis=analysis,
            top_n=top_n,
            user_choice=user_choice,
            retry_context=retry_context,
            audit_top_repo=audit_top_repo,
            audit_expected_capabilities=audit_expected_capabilities,
            audit_allow_light_run=audit_allow_light_run,
            audit_keep_workspace=audit_keep_workspace,
        )

        if isinstance(result, dict) and "status" in result:
            return {"job_id": job_id, "skill_gaps": skill_gaps, **result}

        repos = result
        self._state.results.setdefault(job_id, {})["repos"] = repos

        if self._memory is not None:
            self._memory.add_recommended_projects(job_id, repos)

        job = self._state.job_store.get(job_id, {})
        suggestion = self._suggestion_engine.suggest_after_recommendation(
            job_id,
            job.get("title", ""),
            repos,
        )

        return {
            "job_id": job_id,
            "skill_gaps": skill_gaps,
            "repos": repos,
            "proactive_suggestion": self._suggestion_engine.format_suggestion(suggestion),
        }


class AuditGitHubRepoTool(BaseTool):
    def __init__(self, state: JobAssistantState):
        self._state = state

    @property
    def name(self) -> str:
        return "audit_github_repo"

    @property
    def description(self) -> str:
        return "下载 GitHub 仓库到沙箱工作区，做静态分析、轻量运行验证，并输出清理后的审计报告"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo_url": {"type": "string", "description": "GitHub 仓库 URL，或本地仓库路径"},
                "expected_capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "希望仓库具备的能力标签，例如 agent/cli/api/rag",
                },
                "allow_light_run": {"type": "boolean", "description": "是否做轻量运行验证，默认 true"},
                "keep_workspace": {"type": "boolean", "description": "是否保留下载后的工作区和依赖，默认 false"},
            },
            "required": ["repo_url"],
        }

    def execute(
        self,
        *,
        repo_url: str,
        expected_capabilities: Optional[List[str]] = None,
        allow_light_run: bool = True,
        keep_workspace: bool = False,
    ) -> Dict[str, Any]:
        result = audit_repository(
            repo_url,
            expected_capabilities=expected_capabilities,
            allow_light_run=allow_light_run,
            keep_workspace=keep_workspace,
        )
        self._state.repo_audits[repo_url] = result
        return result


class CreateLearningPlanTool(BaseTool):
    def __init__(self, state: JobAssistantState):
        self._state = state
        self._planner = LearningPlanner()

    @property
    def name(self) -> str:
        return "create_learning_plan"

    @property
    def description(self) -> str:
        return "为用户制定3/6/12个月学习计划"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "职位 ID"},
                "timeframe": {"type": "string", "enum": ["3months", "6months", "12months"], "description": "时间框架"},
            },
            "required": ["job_id"],
        }

    def execute(self, *, job_id: str, timeframe: str = "3months") -> Dict[str, Any]:
        match = self._state.results.get(job_id, {}).get("match", {})
        gaps = match.get("skill_gaps_detailed") or []

        normalized = []
        for gap in gaps:
            normalized.append(
                {
                    "skill": gap.get("skill", ""),
                    "required_level": gap.get("required_level", 3),
                    "user_level": gap.get("user_level", 0),
                    "category": gap.get("category", "required_skills"),
                }
            )

        plan = self._planner.create_plan(normalized, timeframe=timeframe)
        formatted = self._planner.format_plan(plan)
        return {"success": True, "plan": plan, "formatted_plan": formatted}


class CompareJobsTool(BaseTool):
    def __init__(self, state: JobAssistantState):
        self._state = state
        self._suggestion_engine = ProactiveSuggestionEngine()

    @property
    def name(self) -> str:
        return "compare_jobs"

    @property
    def description(self) -> str:
        return "对比已分析的多个职位"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要对比的职位ID列表（可选，默认对比所有已分析职位）",
                }
            },
        }

    def execute(self, *, job_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        if not job_ids:
            job_ids = list(self._state.results.keys())
        if len(job_ids) < 2:
            return {"error": "至少需要2个职位进行对比"}

        comparison = []
        for job_id in job_ids:
            job = self._state.job_store.get(job_id)
            match = self._state.results.get(job_id, {}).get("match")
            if not job or not match:
                continue
            comparison.append(
                {
                    "job_id": job_id,
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "city": job.get("city"),
                    "salary": job.get("salary"),
                    "score": match.get("score", 0),
                    "matched_skills_count": len(match.get("matched_skills", [])),
                    "skill_gaps_count": len(match.get("skill_gaps", [])),
                }
            )

        comparison.sort(key=lambda x: x["score"], reverse=True)
        suggestion = self._suggestion_engine.suggest_job_comparison(len(comparison))
        return {"success": True, "comparison": comparison, "recommendation": suggestion}


class GenerateReportTool(BaseTool):
    def __init__(self, state: JobAssistantState):
        self._state = state

    @property
    def name(self) -> str:
        return "generate_report"

    @property
    def description(self) -> str:
        return "生成最终的 Markdown 求职分析报告并保存到文件"

    @property
    def schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> Dict[str, Any]:
        ranked_jobs = []
        for job_id, result in self._state.results.items():
            job = self._state.job_store.get(job_id, {})
            ranked_jobs.append(
                {
                    **job,
                    "analysis": result.get("analysis", {}),
                    "match": result.get("match", {}),
                    "repos": result.get("repos", []),
                    "suggestions": result.get("suggestions", []),
                }
            )

        for job in ranked_jobs:
            suggestions = job.get("suggestions")
            if not suggestions or not isinstance(suggestions, list):
                job["suggestions"] = generate_suggestions(
                    job.get("analysis", {}),
                    job.get("repos", []),
                    job.get("match", {}).get("skill_gaps", []),
                )

        ranked_sorted = sorted(ranked_jobs, key=lambda x: x.get("match", {}).get("score", 0), reverse=True)
        report_md = report_generator.generate_markdown(self._state.profile, ranked_sorted)

        self._state.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._state.output_dir / f"report_agent_{ts}.md"
        path.write_text(report_md, encoding="utf-8")

        return {
            "status": "success",
            "report_path": str(path),
            "jobs_analyzed": len(ranked_sorted),
            "top_job": ranked_sorted[0]["title"] if ranked_sorted else "无",
        }


class SearchGitHubTool(BaseTool):
    """独立的 GitHub 项目搜索工具（不依赖职位分析）"""

    def __init__(self, state: JobAssistantState, memory: Optional[ConversationMemory] = None):
        self._state = state
        self._memory = memory

    @property
    def name(self) -> str:
        return "search_github"

    @property
    def description(self) -> str:
        return "根据用户需求搜索 GitHub 项目，支持自然语言描述"

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_query": {
                    "type": "string",
                    "description": "用户的搜索需求（自然语言）"
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "提取的关键词列表（可选，LLM 自动提取）"
                },
                "min_stars": {
                    "type": "integer",
                    "description": "最低 star 数，默认 1000"
                },
                "top_n": {
                    "type": "integer",
                    "description": "返回项目数量，默认 5"
                },
                "user_choice": {
                    "type": "string",
                    "enum": ["replan", "lower_stars", "use_local"],
                    "description": "重规划选项（可选）"
                }
            },
            "required": ["user_query"]
        }

    def execute(
        self,
        *,
        user_query: str,
        keywords: Optional[List[str]] = None,
        min_stars: int = 1000,
        top_n: int = 5,
        user_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行流程：
        1. LLM 理解用户需求，提取关键词和技术栈
        2. 调用 smart_recommend_projects()（复用现有逻辑）
        3. 返回推荐项目列表
        """
        # 构建临时画像用于搜索
        temp_profile = {
            "name": "GitHub Search User",
            "target_roles": keywords or [user_query],
            "skills": [],
            "preferences": {}
        }

        # 构建临时职位用于触发推荐
        temp_job = {
            "job_id": f"github_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "title": user_query,
            "required_skills": keywords or [],
            "preferred_skills": []
        }

        # 调用现有的 smart_recommend_projects
        result = smart_recommend_projects(
            profile=temp_profile,
            job=temp_job,
            top_n=top_n,
            min_stars=min_stars,
            user_choice=user_choice
        )

        # 记录到会话记忆
        if self._memory:
            self._memory.add_message(
                "system",
                f"GitHub 搜索: {user_query} (找到 {len(result.get('repos', []))} 个项目)"
            )

        return result
