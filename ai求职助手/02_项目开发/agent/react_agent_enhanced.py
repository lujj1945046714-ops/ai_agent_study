"""
ReAct Agent 核心循环（Phase 2 增强版）

新增功能：
1. 对话记忆系统 - 记住所有分析和推荐
2. 主动建议引擎 - 根据匹配度主动建议
3. 上下文理解 - 理解简短追问
4. 学习规划 - 自动制定学习计划

架构：
  用户任务
    └─ system prompt（用户画像 + 工具说明 + 上下文记忆）
         └─ ReAct 循环
              ├─ Think：LLM 决定下一步
              ├─ Act：调用工具
              ├─ Observe：获取结果，追加到 messages
              ├─ Update Memory：更新对话记忆
              ├─ Generate Suggestion：生成主动建议
              └─ 重复，直到 LLM 不再调用工具
"""
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保父目录在 sys.path 中
_BASE = Path(__file__).resolve().parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

import memory as mem
from agent.tools import (
    TOOL_SCHEMAS,
    tool_analyze_job,
    tool_generate_report,
    tool_match_job,
    tool_recommend_learning,
)

# Phase 2 新增模块
from agent.conversation_memory import ConversationMemory
from agent.suggestion_engine import ProactiveSuggestionEngine
from agent.context_understanding import ContextualUnderstanding
from agent.learning_planner import LearningPlanner

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是一个专业的 AI 求职助手 Agent。你的目标是帮助用户找到最合适的 AI Agent 工程师职位，\
并给出个性化的技能提升建议。

## 用户画像
{user_profile_json}

## 历史记忆
{memory_context}

## 当前会话上下文
{conversation_context}

## 可用工具
你可以使用以下工具：
1. search_jobs - 搜索职位
2. analyze_job - 分析职位要求
3. match_job - 计算匹配度
4. recommend_learning - 推荐学习项目
5. create_learning_plan - 制定学习计划（新增）
6. compare_jobs - 对比多个职位（新增）
7. generate_report - 生成最终报告

## 工作原则
{job_source_instruction}
2. 对每个职位依次调用 analyze_job → match_job → recommend_learning。
3. 每次操作后，观察结果并根据主动建议决定下一步。
4. 如果用户说"再推荐几个"、"这个职位怎么样"等简短追问，从上下文中理解指代。
5. 分析完职位后，主动询问用户是否需要：
   - 推荐学习项目
   - 制定学习计划
   - 继续分析其他职位
6. 所有职位处理完毕后，调用 generate_report 生成最终报告。

## 注意
- 每次工具调用后，仔细观察返回结果再决定下一步。
- 不要重复分析同一个 job_id。
- 利用上下文记忆，理解用户的简短追问。
- 主动提出建议，引导用户完成求职流程。
"""

_JOB_SOURCE_SEARCH = "1. 先用 search_jobs 搜索职位，cities 和 keywords 从用户画像中提取。"
_JOB_SOURCE_PRELOAD = """\
1. 职位已预加载，直接从以下列表开始分析（无需调用 search_jobs）：
{jobs_summary}"""


class JobSearchAgent:
    def __init__(
        self,
        user_profile: Dict[str, Any],
        api_key: str,
        base_url: str,
        model: str,
        output_dir: Path,
        name: str = "default",
        max_steps: int = 30,
        enable_phase2: bool = True,  # 是否启用 Phase 2 功能
    ):
        self.profile = user_profile
        self.model = model
        self.output_dir = output_dir
        self.max_steps = max_steps
        self._name = name
        self.messages: List[Dict] = []
        self._job_store: Dict[str, Dict] = {}
        self._results: Dict[str, Dict] = {}
        self._memory = mem.load(name)

        # Phase 2 新增
        self.enable_phase2 = enable_phase2
        if enable_phase2:
            self.conversation_memory = ConversationMemory(max_history=20)
            self.suggestion_engine = ProactiveSuggestionEngine()
            self.learning_planner = LearningPlanner()

            # 尝试加载会话
            session_file = output_dir / f"session_{name}.json"
            if session_file.exists():
                try:
                    self.conversation_memory.load(str(session_file))
                    logger.info("已加载会话: %s", session_file)
                except Exception as e:
                    logger.warning("加载会话失败: %s", e)

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:
            raise RuntimeError("需要安装 openai 包：pip install openai")

        # ContextualUnderstanding 在 client 初始化后创建，传入 LLM 客户端
        if enable_phase2:
            self.context_understanding = ContextualUnderstanding(
                self.conversation_memory,
                llm_client=self.client,
                model=model,
            )

    # ── 公开入口 ────────────────────────────────────────────────────────────

    def preload_jobs(self, jobs: List[Dict]) -> None:
        """将外部传入的 job 列表写入 _job_store，供 agent 直接分析。"""
        for j in jobs:
            self._job_store[j["job_id"]] = j

    def run(self, task: str = "帮我分析当前市场上适合我的 AI Agent 工程师职位") -> str:
        # 构建记忆上下文
        memory_context = mem.build_memory_prompt(self._memory) or "暂无历史记录"

        # Phase 2: 构建会话上下文
        conversation_context = ""
        if self.enable_phase2:
            conversation_context = self.conversation_memory.get_context_summary()
            if not conversation_context:
                conversation_context = "这是新会话的开始"

        if self._job_store:
            jobs_summary = "\n".join(
                f"  - {j['job_id']}: {j['title']} @ {j['company']} ({j['city']}, {j['salary']})"
                for j in self._job_store.values()
            )
            job_source_instruction = _JOB_SOURCE_PRELOAD.format(jobs_summary=jobs_summary)
        else:
            job_source_instruction = _JOB_SOURCE_SEARCH

        system = _SYSTEM_PROMPT.format(
            user_profile_json=json.dumps(self.profile, ensure_ascii=False, indent=2),
            memory_context=memory_context,
            conversation_context=conversation_context,
            job_source_instruction=job_source_instruction,
        )
        self.messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

        logger.info("Agent 启动，任务：%s", task)

        for step in range(1, self.max_steps + 1):
            logger.info("── Step %d ──", step)

            tool_calls_buffer: Dict[int, Dict] = {}
            full_content = ""

            print(f"\n[Step {step}] ", end="", flush=True)

            try:
                with self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=self._get_tool_schemas(),
                    tool_choice="auto",
                    stream=True,
                ) as stream:
                    for chunk in stream:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            print(delta.content, end="", flush=True)
                            full_content += delta.content
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                buf = tool_calls_buffer.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                if tc.id:
                                    buf["id"] = tc.id
                                if tc.function and tc.function.name:
                                    buf["name"] = tc.function.name
                                if tc.function and tc.function.arguments:
                                    buf["arguments"] += tc.function.arguments
            except Exception as stream_err:
                logger.warning("流式响应中断，尝试重试: %s", stream_err)
                if not full_content and not tool_calls_buffer:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=self.messages,
                        tools=self._get_tool_schemas(),
                        tool_choice="auto",
                    )
                    msg = resp.choices[0].message
                    full_content = msg.content or ""
                    if msg.tool_calls:
                        for i, tc in enumerate(msg.tool_calls):
                            tool_calls_buffer[i] = {
                                "id": tc.id,
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }

            if full_content:
                print()

            msg_dict: Dict[str, Any] = {"role": "assistant", "content": full_content}
            if tool_calls_buffer:
                msg_dict["tool_calls"] = [
                    {
                        "id": buf["id"],
                        "type": "function",
                        "function": {"name": buf["name"], "arguments": buf["arguments"]},
                    }
                    for buf in tool_calls_buffer.values()
                ]
            self.messages.append(msg_dict)

            if not tool_calls_buffer:
                logger.info("Agent 完成，共 %d 步", step)

                # Phase 2: 记录对话
                if self.enable_phase2:
                    self.conversation_memory.add_conversation_turn(task, full_content)
                    self._save_session()

                self._save_memory(full_content)
                return full_content or "分析完成"

            # 执行工具调用
            for buf in tool_calls_buffer.values():
                name = buf["name"]
                try:
                    args = json.loads(buf["arguments"])
                except json.JSONDecodeError:
                    args = {}

                logger.info("调用工具: %s  参数: %s", name, args)
                print(f"\n[工具调用] {name}", flush=True)
                result = self._dispatch(name, args)
                logger.info("工具结果: %s", json.dumps(result, ensure_ascii=False)[:200])

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": buf["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })

        # Phase 2: 保存会话
        if self.enable_phase2:
            self._save_session()

        self._save_memory("")
        return "已达到最大步骤数，分析终止"

    def _get_tool_schemas(self) -> List[Dict]:
        """获取工具 schema（Phase 2 新增工具）"""
        schemas = list(TOOL_SCHEMAS)

        if self.enable_phase2:
            # 添加新工具
            schemas.extend([
                {
                    "type": "function",
                    "function": {
                        "name": "create_learning_plan",
                        "description": "为用户制定3/6/12个月学习计划",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "job_id": {
                                    "type": "string",
                                    "description": "职位ID"
                                },
                                "timeframe": {
                                    "type": "string",
                                    "enum": ["3months", "6months", "12months"],
                                    "description": "时间框架"
                                }
                            },
                            "required": ["job_id"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "compare_jobs",
                        "description": "对比已分析的多个职位",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "job_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "要对比的职位ID列表（可选，默认对比所有已分析职位）"
                                }
                            }
                        }
                    }
                }
            ])

        return schemas

    # ── 工具分发 ────────────────────────────────────────────────────────────

    def _dispatch(self, name: str, args: Dict) -> Any:
        try:
            if name == "search_jobs":
                return self._handle_search_jobs(args)
            elif name == "analyze_job":
                return self._handle_analyze_job(args)
            elif name == "match_job":
                return self._handle_match_job(args)
            elif name == "recommend_learning":
                return self._handle_recommend_learning(args)
            elif name == "create_learning_plan":
                return self._handle_create_learning_plan(args)
            elif name == "compare_jobs":
                return self._handle_compare_jobs(args)
            elif name == "generate_report":
                return self._handle_generate_report(args)
            else:
                return {"error": f"未知工具: {name}"}
        except Exception as exc:
            logger.exception("工具 %s 执行失败", name)
            return {"error": str(exc)}

    # ── 工具处理器 ────────────────────────────────────────────────────────────

    def _handle_search_jobs(self, args: Dict) -> Any:
        """搜索职位"""
        from modules.scraper import fetch_jobs

        patched = dict(self.profile)
        patched["preferences"] = dict(self.profile.get("preferences", {}))
        patched["preferences"]["cities"] = args.get("cities", [])
        patched["target_roles"] = args.get("keywords", [])

        full_jobs = fetch_jobs(patched, max_results=args.get("max_results", 10))
        for j in full_jobs:
            self._job_store[j["job_id"]] = j

        summary = [
            {
                "job_id": j["job_id"],
                "title": j["title"],
                "company": j["company"],
                "city": j["city"],
                "salary": j["salary"],
                "jd_preview": j["jd_text"][:120].strip() + "...",
            }
            for j in full_jobs
        ]
        return {"count": len(summary), "jobs": summary}

    def _handle_analyze_job(self, args: Dict) -> Any:
        """分析职位要求"""
        job_id = args["job_id"]
        jd_text = args.get("jd_text") or self._job_store.get(job_id, {}).get("jd_text", "")
        result = tool_analyze_job(job_id, jd_text)

        # Phase 2: 记录到对话记忆
        if self.enable_phase2:
            job = self._job_store.get(job_id, {})
            self.conversation_memory.add_job_analysis(
                job_id,
                {
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "city": job.get("city"),
                    "salary": job.get("salary"),
                },
                result
            )

        self._results.setdefault(job_id, {})["analysis"] = result
        return result

    def _handle_match_job(self, args: Dict) -> Any:
        """计算匹配度"""
        job_id = args["job_id"]
        analysis = args.get("analysis") or self._results.get(job_id, {}).get("analysis", {})
        result = tool_match_job(self.profile, job_id, analysis)

        self._results.setdefault(job_id, {})["match"] = result

        if result["score"] < 25:
            self._results[job_id]["repos"] = []
            result["recommend_learning_skipped"] = True
            result["skip_reason"] = "匹配分低于25，已自动跳过学习推荐"

        # Phase 2: 记录匹配结果 + 生成主动建议
        if self.enable_phase2:
            self.conversation_memory.add_match_result(job_id, result)

            job = self._job_store.get(job_id, {})
            suggestion = self.suggestion_engine.suggest_after_analysis(
                job_id,
                job.get("title", ""),
                result.get("score", 0),
                result.get("skill_gaps", []),
                result.get("matched_skills", [])
            )
            result["proactive_suggestion"] = self.suggestion_engine.format_suggestion(suggestion)

        return result

    def _handle_recommend_learning(self, args: Dict) -> Any:
        """推荐学习项目"""
        job_id = args.get("job_id", "")
        skill_gaps = args.get("skill_gaps", [])
        user_choice = args.get("user_choice")
        retry_context = args.get("retry_context")
        analysis = self._results.get(job_id, {}).get("analysis", {}) if job_id else {}

        result = tool_recommend_learning(
            skill_gaps=skill_gaps,
            top_n=args.get("top_n", 3),
            profile=self.profile,
            analysis=analysis,
            user_choice=user_choice,
            retry_context=retry_context,
        )

        if result.get("status") == "need_replan":
            if job_id:
                self._results.setdefault(job_id, {})["replan_pending"] = {
                    "skill_gaps": skill_gaps,
                    "retry_context": result.get("retry_context"),
                    "failure_reason": result.get("failure_reason"),
                }
            return result

        # Phase 2: 记录推荐项目 + 生成主动建议
        if job_id and result.get("repos"):
            self._results.setdefault(job_id, {})["repos"] = result["repos"]
            if "replan_pending" in self._results.get(job_id, {}):
                del self._results[job_id]["replan_pending"]

            if self.enable_phase2:
                self.conversation_memory.add_recommended_projects(job_id, result["repos"])

                job = self._job_store.get(job_id, {})
                already_count = len(self.conversation_memory.get_recommended_projects(job_id))
                suggestion = self.suggestion_engine.suggest_after_recommendation(
                    job.get("title", ""),
                    len(result["repos"]),
                    already_count
                )
                result["proactive_suggestion"] = self.suggestion_engine.format_suggestion(suggestion)

        return result

    def _handle_create_learning_plan(self, args: Dict) -> Any:
        """制定学习计划（Phase 2 新增）"""
        if not self.enable_phase2:
            return {"error": "Phase 2 功能未启用"}

        job_id = args.get("job_id")
        timeframe = args.get("timeframe", "3months")

        if not job_id:
            return {"error": "缺少 job_id"}

        # 获取匹配结果
        match_result = self._results.get(job_id, {}).get("match")
        if not match_result:
            return {"error": f"请先计算匹配度: {job_id}"}

        # 构建技能缺口列表
        skill_gaps = []
        analysis = self._results.get(job_id, {}).get("analysis", {})

        # 从详细技能缺口中提取
        for gap in match_result.get("skill_gaps_detailed", []):
            skill_gaps.append({
                "skill": gap["skill"],
                "required_level": gap["required_level"],
                "user_level": gap["user_level"],
                "category": gap["category"]
            })

        # 创建学习计划
        plan = self.learning_planner.create_plan(skill_gaps, timeframe)

        # 格式化输出
        formatted_plan = self.learning_planner.format_plan(plan)

        return {
            "success": True,
            "plan": plan,
            "formatted_plan": formatted_plan
        }

    def _handle_compare_jobs(self, args: Dict) -> Any:
        """对比多个职位（Phase 2 新增）"""
        if not self.enable_phase2:
            return {"error": "Phase 2 功能未启用"}

        job_ids = args.get("job_ids", [])

        # 如果未指定，对比所有已分析的职位
        if not job_ids:
            job_ids = list(self._results.keys())

        if len(job_ids) < 2:
            return {"error": "至少需要2个职位进行对比"}

        # 收集对比数据
        comparison = []
        for job_id in job_ids:
            job = self._job_store.get(job_id)
            match_result = self._results.get(job_id, {}).get("match")

            if job and match_result:
                comparison.append({
                    "job_id": job_id,
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "city": job.get("city"),
                    "salary": job.get("salary"),
                    "score": match_result.get("score", 0),
                    "matched_skills_count": len(match_result.get("matched_skills", [])),
                    "skill_gaps_count": len(match_result.get("skill_gaps", []))
                })

        # 按匹配度排序
        comparison.sort(key=lambda x: x["score"], reverse=True)

        # 生成对比建议
        suggestion = self.suggestion_engine.suggest_job_comparison(len(comparison))

        return {
            "success": True,
            "comparison": comparison,
            "recommendation": suggestion
        }

    def _handle_generate_report(self, args: Dict) -> Any:
        """生成最终报告"""
        try:
            # 构建 ranked_jobs 列表（合并 job_store 和 results）
            ranked_jobs = []
            for job_id, result in self._results.items():
                job = self._job_store.get(job_id, {})
                ranked_jobs.append({
                    **job,
                    "analysis": result.get("analysis", {}),
                    "match": result.get("match", {}),
                    "repos": result.get("repos", []),
                })

            result = tool_generate_report(
                self.profile,
                ranked_jobs,
                self.output_dir
            )

            # Phase 2: 记录报告生成
            if self.enable_phase2:
                self.conversation_memory.add_conversation_turn(
                    "生成报告",
                    f"已生成报告: {result.get('report_path')}"
                )

            return result
        except Exception as e:
            logger.exception("生成报告失败")
            return {"error": str(e)}

    # ── 辅助方法 ────────────────────────────────────────────────────────────

    def _save_session(self) -> None:
        """保存会话（Phase 2）"""
        if not self.enable_phase2:
            return

        session_file = self.output_dir / f"session_{self._name}.json"
        try:
            self.conversation_memory.save(str(session_file))
            logger.info("会话已保存: %s", session_file)
        except Exception as e:
            logger.warning("保存会话失败: %s", e)

    def _save_memory(self, final_content: str) -> None:
        """保存长期记忆"""
        if not self._results:
            return

        best = max(
            self._results.items(),
            key=lambda kv: kv[1].get("match", {}).get("score", 0)
        )
        job_id, data = best
        job_info = self._job_store.get(job_id, {})
        top_job = job_info.get("title", job_id)
        top_score = data.get("match", {}).get("score", 0)
        main_gaps = data.get("match", {}).get("skill_gaps", [])

        mem.append_search(self._memory, top_job, top_score, main_gaps)
        mem.save(self._memory, self._name)
        logger.info("长期记忆已保存：top_job=%s score=%d", top_job, top_score)
