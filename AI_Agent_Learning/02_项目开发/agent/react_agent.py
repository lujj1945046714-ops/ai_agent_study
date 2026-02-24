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
        self._job_store: Dict[str, Dict] = {}  # job_id -> full job dict
        self._results: Dict[str, Dict] = {}    # job_id -> {analysis, match, repos}

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:
            raise RuntimeError("需要安装 openai 包：pip install openai")

    # ── 公开入口 ────────────────────────────────────────────────────────────

    def run(self, task: str = "帮我分析当前市场上适合我的 AI Agent 工程师职位") -> str:
        system = _SYSTEM_PROMPT.format(
            user_profile_json=json.dumps(self.profile, ensure_ascii=False, indent=2)
        )
        self.messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

        logger.info("Agent 启动，任务：%s", task)

        for step in range(1, self.max_steps + 1):
            logger.info("── Step %d ──", step)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            # 将 assistant 消息追加到历史（转为 dict 兼容序列化）
            self.messages.append(self._msg_to_dict(msg))

            if not msg.tool_calls:
                # LLM 不再调用工具 → 最终答案
                logger.info("Agent 完成，共 %d 步", step)
                return msg.content or "分析完成"

            # 执行所有工具调用
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                logger.info("调用工具: %s  参数: %s", name, args)
                result = self._dispatch(name, args)
                logger.info("工具结果: %s", json.dumps(result, ensure_ascii=False)[:200])

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

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
        result = tool_recommend_learning(
            skill_gaps=args.get("skill_gaps", []),
            top_n=args.get("top_n", 3),
        )
        # 尝试关联到最近处理的 job_id（通过 skill_gaps 反查）
        for job_id, data in self._results.items():
            match = data.get("match", {})
            if set(match.get("skill_gaps", [])) == set(args.get("skill_gaps", [])):
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

        # 允许 agent 传入自己整理的列表（优先使用）
        if args.get("ranked_jobs"):
            ranked_jobs = args["ranked_jobs"]

        return tool_generate_report(self.profile, ranked_jobs, self.output_dir)

    # ── 工具函数 ────────────────────────────────────────────────────────────

    @staticmethod
    def _msg_to_dict(msg) -> Dict:
        """将 openai Message 对象转为可序列化的 dict"""
        d: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return d
