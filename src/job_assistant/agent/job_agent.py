from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_framework.gateway.hooks import HooksRegistry
from agent_framework.harness.trace import JsonlTraceWriter
from agent_framework.llm.types import OnToken
from agent_framework.runtime.react_engine import ReactEngine
from agent_framework.runtime.tool_dispatcher import ToolDispatcher
from agent_framework.tools.registry import ToolRegistry

from job_assistant import config
from job_assistant.agent.conversation_memory import ConversationMemory
from job_assistant.agent.state import JobAssistantState
from job_assistant.agent.tools import (
    AnalyzeJobTool,
    AuditGitHubRepoTool,
    CompareJobsTool,
    CreateLearningPlanTool,
    DiscoverJobsTool,
    GenerateReportTool,
    MatchJobTool,
    RecommendLearningTool,
    SearchGitHubTool,
    SearchJobsTool,
)
from job_assistant.llm_runtime import create_chat_model
from job_assistant.persistence.sqlite_store import SQLiteJobStore, SQLiteJobStoreConfig

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
你是一个专业的 AI 求职助手 Agent。你的目标是帮助用户自主找岗位、分析职位 JD、计算匹配度，并给出个性化的技能提升建议。

## 用户画像
{user_profile_json}

## 当前会话上下文
{conversation_context}

## 可用工具
你可以使用以下工具：
1. discover_jobs - 基于画像自主搜索公开岗位并返回已打分 shortlist
2. search_jobs - 使用本地/回退模式搜索职位
3. analyze_job - 分析职位要求
4. match_job - 计算匹配度
5. recommend_learning - 推荐学习项目
6. create_learning_plan - 制定学习计划
7. compare_jobs - 对比多个职位
8. audit_github_repo - 下载并验证某个 GitHub 仓库是否符合预期
9. search_github - 独立的 GitHub 项目搜索（不依赖职位分析）
10. generate_report - 生成最终报告

## 工作原则
{job_source_instruction}
2. 当用户说“帮我找岗位/刷新岗位/看看有没有适合我的职位”时，优先调用 discover_jobs；它已经会完成搜索、JD 抽取、去重和匹配打分。
3. 如果 discover_jobs 返回 fallback_required，再退回 search_jobs 或引导用户粘贴 JD。
4. 对单个具体职位做深挖时，再调用 analyze_job → match_job → recommend_learning（匹配分过低可跳过推荐）。
5. 每次工具调用后，先观察结果再决定下一步；不要重复分析同一个 job_id（如果已分析，直接复用已有结果）。
6. 如果用户要求验证具体项目，调用 audit_github_repo，并基于审计结果说明输入/输出、模块和工程特点。
7. 所有职位处理完毕后，调用 generate_report 生成最终报告。
"""

_JOB_SOURCE_SEARCH = "1. 优先用 discover_jobs 按用户画像自主搜索公开岗位；仅在失败时再用 search_jobs 回退。"
_JOB_SOURCE_PRELOAD = """\
1. 职位已预加载，直接从以下列表开始分析（无需再次搜索）：
{jobs_summary}"""


class JobAssistantAgent:
    def __init__(
        self,
        *,
        user_profile: Dict[str, Any],
        output_dir: Optional[Path] = None,
        session_id: str = "default",
        max_steps: int = 30,
        enable_phase2: bool = True,
    ):
        config.ensure_dirs()

        self.session_id = session_id
        self.max_steps = max_steps
        self.enable_phase2 = enable_phase2

        self.output_dir = output_dir or config.OUTPUT_DIR
        self.state = JobAssistantState(profile=user_profile, output_dir=self.output_dir)
        self.last_run_result: Any | None = None

        self.conversation_memory: Optional[ConversationMemory] = None
        if enable_phase2:
            self.conversation_memory = ConversationMemory(max_history=20)
            session_file = self.output_dir / f"session_{session_id}.json"
            if session_file.exists():
                try:
                    self.conversation_memory.load(str(session_file))
                    logger.info("已加载会话: %s", session_file)
                except Exception as exc:
                    logger.warning("加载会话失败: %s", exc)

        llm = create_chat_model()

        self._trace_writer: JsonlTraceWriter | None = None
        self._db = SQLiteJobStore(SQLiteJobStoreConfig(db_path=config.DB_PATH))

        hooks = HooksRegistry()
        hooks.register("before_tool", self._on_before_tool)
        hooks.register("after_tool", self._on_after_tool)
        registry = ToolRegistry()
        dispatcher = ToolDispatcher(registry, hooks)

        registry.register(DiscoverJobsTool(self.state, self._db, memory=self.conversation_memory))
        registry.register(SearchJobsTool(self.state))
        registry.register(AnalyzeJobTool(self.state, memory=self.conversation_memory))
        registry.register(MatchJobTool(self.state, memory=self.conversation_memory))
        registry.register(RecommendLearningTool(self.state, memory=self.conversation_memory))
        registry.register(CreateLearningPlanTool(self.state))
        registry.register(CompareJobsTool(self.state))
        registry.register(AuditGitHubRepoTool(self.state))
        registry.register(SearchGitHubTool(self.state, memory=self.conversation_memory))
        registry.register(GenerateReportTool(self.state))

        self._engine = ReactEngine(llm=llm, tool_registry=registry, tool_dispatcher=dispatcher)

    def preload_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        for job in jobs:
            self.state.job_store[job["job_id"]] = job

    def run(self, task: str, *, stream: bool = False, on_token: Optional[OnToken] = None) -> str:
        trace_path = self.output_dir / "traces" / f"{self.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._trace_writer = JsonlTraceWriter(trace_path)

        self._trace_writer.write(
            "run.start",
            {"session_id": self.session_id, "task": task},
        )

        if self.enable_phase2 and self.conversation_memory is not None:
            conversation_context = self.conversation_memory.get_context_summary() or "这是新会话的开始"
        else:
            conversation_context = "这是新会话的开始"

        if self.state.job_store:
            jobs_summary = "\n".join(
                f"  - {j['job_id']}: {j.get('title')} @ {j.get('company')} ({j.get('city')}, {j.get('salary')})"
                for j in self.state.job_store.values()
            )
            job_source_instruction = _JOB_SOURCE_PRELOAD.format(jobs_summary=jobs_summary)
        else:
            job_source_instruction = _JOB_SOURCE_SEARCH

        system_prompt = _SYSTEM_PROMPT.format(
            user_profile_json=json.dumps(self.state.profile, ensure_ascii=False, indent=2),
            conversation_context=conversation_context,
            job_source_instruction=job_source_instruction,
        )

        result = self._engine.run(
            system_prompt=system_prompt,
            task=task,
            max_steps=self.max_steps,
            stream=stream,
            on_token=on_token,
        )
        self.last_run_result = result

        self._trace_writer.write(
            "run.end",
            {"steps": result.steps, "output_text": result.output_text},
        )
        self._trace_writer.write("run.messages", {"messages": result.messages})

        if self.enable_phase2 and self.conversation_memory is not None:
            self.conversation_memory.add_conversation_turn(task, result.output_text)
            self._save_session()

        return result.output_text or "分析完成"

    def _save_session(self) -> None:
        if not self.conversation_memory:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        session_file = self.output_dir / f"session_{self.session_id}.json"
        try:
            self.conversation_memory.save(str(session_file))
        except Exception as exc:
            logger.warning("保存会话失败: %s", exc)

    def _on_before_tool(self, ctx: Dict[str, Any]) -> None:
        if self._trace_writer is None:
            return
        self._trace_writer.write(
            "tool.before",
            {"tool_name": ctx.get("tool_name", ""), "arguments": ctx.get("arguments", {})},
        )

    def _on_after_tool(self, ctx: Dict[str, Any]) -> None:
        tool_name = ctx.get("tool_name", "")
        arguments = ctx.get("arguments", {}) or {}
        result = ctx.get("result")

        if self._trace_writer is not None:
            payload: Dict[str, Any] = {"tool_name": tool_name, "arguments": arguments}
            if result is not None:
                payload["success"] = bool(getattr(result, "success", False))
                payload["error"] = getattr(result, "error", None)
                payload["output"] = getattr(result, "output", None)
            self._trace_writer.write("tool.after", payload)

        try:
            if tool_name == "discover_jobs":
                return

            if tool_name == "search_jobs":
                self._db.save_raw_jobs(list(self.state.job_store.values()))
                return

            if tool_name in {"analyze_job", "match_job", "recommend_learning"}:
                job_id = arguments.get("job_id")
                if not job_id:
                    return
                job = self.state.job_store.get(job_id)
                if not job:
                    return
                data = self.state.results.get(job_id, {})
                self._db.save_snapshot(
                    job_id=job_id,
                    job=job,
                    analysis=data.get("analysis"),
                    match=data.get("match"),
                    repos=data.get("repos"),
                    suggestions=data.get("suggestions"),
                )
                return

            if tool_name == "generate_report":
                for job_id in list(self.state.results.keys()):
                    job = self.state.job_store.get(job_id)
                    if not job:
                        continue
                    data = self.state.results.get(job_id, {})
                    self._db.save_snapshot(
                        job_id=job_id,
                        job=job,
                        analysis=data.get("analysis"),
                        match=data.get("match"),
                        repos=data.get("repos"),
                        suggestions=data.get("suggestions"),
                    )
        except Exception:  # pragma: no cover - best-effort persistence
            logger.warning("SQLite 持久化失败", exc_info=True)
