"""
ReAct Agent 核心循环。

架构：
  用户任务
    └─ system prompt（用户画像 + 工具说明）
         └─ ReAct 循环
              ├─ Think：LLM 决定下一步
              ├─ Act：调用工具
              ├─ Observe：获取结果，追加到 messages
              └─ 重复，直到 LLM 不再调用工具（输出最终答案）

与旧 Pipeline 的核心区别：
  - LLM 自主决定调用哪个工具、调用顺序、何时停止
  - 支持动态分支（如发现某职位匹配极低，跳过深度分析）
  - 有完整的 Observe 反馈，LLM 可根据结果调整策略
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
    tool_search_jobs,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是一个专业的 AI 求职助手 Agent。你的目标是帮助用户找到最合适的 AI Agent 工程师职位，\
并给出个性化的技能提升建议。

## 用户画像
{user_profile_json}

## 历史记忆
{memory_context}

## 工作原则
1. 先用 search_jobs 搜索职位，cities 和 keywords 从用户画像中提取。
2. 对每个职位依次调用 analyze_job → match_job → recommend_learning。
3. 如果工具返回 recommend_learning_skipped=true，跳过该职位的 recommend_learning。
4. 所有职位处理完毕后，调用 generate_report 生成最终报告。
5. 报告生成后，用中文向用户总结关键发现（Top 职位、主要技能缺口、最重要的学习建议）。

## 注意
- 每次工具调用后，仔细观察返回结果再决定下一步。
- 不要重复分析同一个 job_id。
- analyze_job 需要完整的 jd_text，从 search_jobs 返回的 job_id 对应的原始数据中获取。
"""

# search_jobs 返回的是摘要，agent 需要完整 jd_text 才能调用 analyze_job
# 我们在 run() 里维护一个 job_id -> full_job 的缓存，工具执行时注入
_JD_CACHE: Dict[str, str] = {}


class JobSearchAgent:
    def __init__(
        self,
        user_profile: Dict[str, Any],
        api_key: str,
        base_url: str,
        model: str,
        output_dir: Path,
        max_steps: int = 30,
    ):
        self.profile = user_profile
        self.model = model
        self.output_dir = output_dir
        self.max_steps = max_steps
        self.messages: List[Dict] = []
        self._job_store: Dict[str, Dict] = {}
        self._results: Dict[str, Dict] = {}
        self._memory = mem.load()

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:
            raise RuntimeError("需要安装 openai 包：pip install openai")

    # ── 公开入口 ────────────────────────────────────────────────────────────

    def run(self, task: str = "帮我分析当前市场上适合我的 AI Agent 工程师职位") -> str:
        memory_context = mem.build_memory_prompt(self._memory) or "暂无历史记录"
        system = _SYSTEM_PROMPT.format(
            user_profile_json=json.dumps(self.profile, ensure_ascii=False, indent=2),
            memory_context=memory_context,
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
                    tools=TOOL_SCHEMAS,
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
                    # 完全没收到任何内容，重试一次（非流式）
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=self.messages,
                        tools=TOOL_SCHEMAS,
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
                self._save_memory(full_content)
                return full_content or "分析完成"

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

        self._save_memory("")
        return "已达到最大步骤数，分析终止"

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
            elif name == "generate_report":
                return self._handle_generate_report(args)
            else:
                return {"error": f"未知工具: {name}"}
        except Exception as exc:
            logger.exception("工具 %s 执行失败", name)
            return {"error": str(exc)}

    def _handle_search_jobs(self, args: Dict) -> Dict:
        from modules.scraper import fetch_jobs  # 直接调用以获取完整数据
        patched = dict(self.profile)
        patched["preferences"] = dict(self.profile.get("preferences", {}))
        patched["preferences"]["cities"] = args.get("cities", [])
        patched["target_roles"] = args.get("keywords", [])

        full_jobs = fetch_jobs(patched, max_results=args.get("max_results", 10))
        # 缓存完整数据供后续工具使用
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

    def _handle_analyze_job(self, args: Dict) -> Dict:
        job_id = args["job_id"]
        # 优先用缓存的完整 jd_text，允许 agent 传入覆盖
        jd_text = args.get("jd_text") or self._job_store.get(job_id, {}).get("jd_text", "")
        result = tool_analyze_job(job_id, jd_text)
        self._results.setdefault(job_id, {})["analysis"] = result
        return result

    def _handle_match_job(self, args: Dict) -> Dict:
        job_id = args["job_id"]
        analysis = args.get("analysis") or self._results.get(job_id, {}).get("analysis", {})
        result = tool_match_job(self.profile, job_id, analysis)
        self._results.setdefault(job_id, {})["match"] = result
        if result["score"] < 25:
            self._results[job_id]["repos"] = []
            result["recommend_learning_skipped"] = True
            result["skip_reason"] = "匹配分低于25，已自动跳过学习推荐"
        return result

    def _handle_recommend_learning(self, args: Dict) -> Dict:
        # 找到对应 job 的 analysis
        skill_gaps = args.get("skill_gaps", [])
        analysis = {}
        for job_id, data in self._results.items():
            match = data.get("match", {})
            if set(match.get("skill_gaps", [])) == set(skill_gaps):
                analysis = data.get("analysis", {})
                break

        result = tool_recommend_learning(
            skill_gaps=skill_gaps,
            top_n=args.get("top_n", 3),
            profile=self.profile,
            analysis=analysis,
        )
        for job_id, data in self._results.items():
            match = data.get("match", {})
            if set(match.get("skill_gaps", [])) == set(skill_gaps):
                data["repos"] = result["repos"]
                break
        return result

    def _handle_generate_report(self, args: Dict) -> Dict:
        # 合并 agent 收集的所有结果
        ranked_jobs = []
        for job_id, data in self._results.items():
            base = self._job_store.get(job_id, {"job_id": job_id})
            ranked_jobs.append({
                **base,
                "analysis": data.get("analysis", {}),
                "match": data.get("match", {}),
                "repos": data.get("repos", []),
            })

        # 允许 agent 传入自己整理的列表（优先使用），但需补全 base 字段
        if args.get("ranked_jobs"):
            agent_jobs = args["ranked_jobs"]
            merged = []
            for job in agent_jobs:
                job_id = job.get("job_id", "")
                base = self._job_store.get(job_id, {})
                merged.append({
                    "title": base.get("title", job.get("title", "未知职位")),
                    "company": base.get("company", job.get("company", "未知公司")),
                    "city": base.get("city", job.get("city", "未知城市")),
                    "salary": base.get("salary", job.get("salary", "面议")),
                    **job,
                })
            ranked_jobs = merged

        return tool_generate_report(self.profile, ranked_jobs, self.output_dir)

    # ── 工具函数 ────────────────────────────────────────────────────────────

    def _save_memory(self, _final_content: str) -> None:
        """Extract top result from this run and persist to memory."""
        if not self._results:
            return
        best = max(self._results.items(), key=lambda kv: kv[1].get("match", {}).get("score", 0))
        job_id, data = best
        job_info = self._job_store.get(job_id, {})
        top_job = job_info.get("title", job_id)
        top_score = data.get("match", {}).get("score", 0)
        main_gaps = data.get("match", {}).get("skill_gaps", [])
        mem.append_search(self._memory, top_job, top_score, main_gaps)
        mem.save(self._memory)
        logger.info("记忆已保存：top_job=%s score=%d", top_job, top_score)
