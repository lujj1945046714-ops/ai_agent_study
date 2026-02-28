"""
上下文理解模块

功能：
1. 解析用户输入中的指代（"这个"、"它"、"再来几个"）
2. 理解简短追问
3. 结合记忆推断意图
4. LLM 增强意图识别（规则匹配兜底）
"""

import json
import logging
from typing import Dict, List, Any, Optional
from agent.conversation_memory import ConversationMemory

logger = logging.getLogger(__name__)

_LLM_INTENT_PROMPT = """\
你是一个意图识别助手。根据用户输入和对话上下文，判断用户的意图。

## 可选意图
- recommend_more: 用户想要更多学习项目推荐
- query_job: 用户想查询某个职位的详情/匹配度
- compare_jobs: 用户想对比多个职位
- create_plan: 用户想制定学习计划
- analyze_job: 用户想分析一个新职位
- search_jobs: 用户想搜索职位
- unknown: 无法判断

## 对话上下文
{context_summary}

## 用户输入
{user_input}

## 要求
只返回一个 JSON 对象，格式如下：
{{"intent": "<意图>", "confidence": <0.0-1.0>, "reason": "<简短理由>"}}
"""


class ContextualUnderstanding:
    """上下文理解"""

    # 意图识别模式
    INTENT_PATTERNS = {
        "recommend_more": ["再推荐", "更多项目", "还有吗", "再来几个", "多推荐几个"],
        "query_job": ["这个职位", "它", "怎么样", "匹配度", "要求"],
        "compare_jobs": ["对比", "比较", "哪个好", "选哪个"],
        "create_plan": ["学习计划", "规划", "路线图", "怎么学"],
        "analyze_job": ["分析", "看看", "评估"],
        "search_jobs": ["搜索", "找", "查找", "有哪些"],
    }

    # 指代词
    REFERENCE_WORDS = ["这个", "它", "那个", "该", "此"]

    def __init__(self, memory: ConversationMemory, llm_client=None, model: str = "deepseek-chat"):
        """
        初始化上下文理解

        Args:
            memory: 对话记忆系统
            llm_client: OpenAI 兼容客户端（可选，用于 LLM 意图识别）
            model: LLM 模型名称
        """
        self.memory = memory
        self._llm_client = llm_client
        self._model = model

    # ==================== 意图识别 ====================

    def understand(self, user_input: str) -> Dict[str, Any]:
        """
        理解用户输入

        Args:
            user_input: 用户输入

        Returns:
            理解结果字典
        """
        # 1. 检测意图
        intent = self._detect_intent(user_input)

        # 2. 解析指代
        references = self._resolve_references(user_input, intent)

        # 3. 提取参数
        params = self._extract_params(user_input, intent)

        return {
            "intent": intent,
            "references": references,
            "params": params,
            "original_input": user_input,
            "needs_context": self._needs_context(intent)
        }

    def _detect_intent(self, user_input: str) -> str:
        """规则匹配意图，unknown 时尝试 LLM 兜底"""
        user_input_lower = user_input.lower()

        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if pattern in user_input_lower:
                    return intent

        # 规则未命中，尝试 LLM
        if self._llm_client:
            llm_intent = self._detect_intent_llm(user_input)
            if llm_intent and llm_intent != "unknown":
                return llm_intent

        return "unknown"

    def _detect_intent_llm(self, user_input: str) -> str:
        """使用 LLM 识别意图（规则匹配兜底）"""
        try:
            context_summary = self.memory.get_context_summary() or "暂无上下文"
            prompt = _LLM_INTENT_PROMPT.format(
                context_summary=context_summary,
                user_input=user_input,
            )
            resp = self._llm_client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=100,
            )
            raw = resp.choices[0].message.content.strip()
            # 提取 JSON
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            intent = data.get("intent", "unknown")
            confidence = data.get("confidence", 0.0)
            logger.debug("LLM 意图识别: %s (置信度 %.2f) — %s", intent, confidence, data.get("reason", ""))
            # 置信度低于 0.6 视为 unknown
            return intent if confidence >= 0.6 else "unknown"
        except Exception as e:
            logger.warning("LLM 意图识别失败: %s", e)
            return "unknown"

    def _resolve_references(self, user_input: str, intent: str) -> Dict[str, Any]:
        """
        解析指代

        Args:
            user_input: 用户输入
            intent: 意图类型

        Returns:
            指代解析结果
        """
        references = {}

        # 检查是否包含指代词
        has_reference = any(word in user_input for word in self.REFERENCE_WORDS)

        if has_reference or intent in ["recommend_more", "query_job"]:
            # 获取最近分析的职位
            last_job = self.memory.get_last_analyzed_job()
            if last_job:
                references["job_id"] = last_job["job_id"]
                references["job_title"] = last_job["job_info"].get("title", "")

        if intent == "compare_jobs":
            # 获取所有已分析的职位
            all_jobs = self.memory.get_all_analyzed_jobs()
            references["job_ids"] = [job["job_id"] for job in all_jobs]
            references["job_count"] = len(all_jobs)

        return references

    def _extract_params(self, user_input: str, intent: str) -> Dict[str, Any]:
        """
        提取参数

        Args:
            user_input: 用户输入
            intent: 意图类型

        Returns:
            参数字典
        """
        params = {}

        # 提取数量
        if "几个" in user_input or "多少" in user_input:
            # 尝试提取数字
            import re
            numbers = re.findall(r'\d+', user_input)
            if numbers:
                params["count"] = int(numbers[0])
            else:
                params["count"] = 3  # 默认3个

        # 提取时间框架
        if "3个月" in user_input or "三个月" in user_input:
            params["timeframe"] = "3months"
        elif "6个月" in user_input or "半年" in user_input:
            params["timeframe"] = "6months"
        elif "12个月" in user_input or "一年" in user_input:
            params["timeframe"] = "12months"

        # 提取职位ID（如果明确提到）
        if "job-" in user_input or "职位" in user_input:
            import re
            job_ids = re.findall(r'job-\w+', user_input)
            if job_ids:
                params["job_id"] = job_ids[0]

        return params

    def _needs_context(self, intent: str) -> bool:
        """
        判断是否需要上下文

        Args:
            intent: 意图类型

        Returns:
            是否需要上下文
        """
        context_required_intents = [
            "recommend_more",
            "query_job",
            "compare_jobs",
            "create_plan"
        ]
        return intent in context_required_intents

    # ==================== 增强理解 ====================

    def enhance_with_context(self, understanding: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用上下文增强理解

        Args:
            understanding: 基础理解结果

        Returns:
            增强后的理解结果
        """
        intent = understanding["intent"]
        references = understanding["references"]

        # 添加上下文信息
        context = {}

        if intent == "recommend_more":
            # 获取已推荐的项目
            job_id = references.get("job_id")
            if job_id:
                recommended = self.memory.get_recommended_projects(job_id)
                context["already_recommended_count"] = len(recommended)
                context["already_recommended_repos"] = [
                    p.get("repo") for p in recommended
                ]

        if intent == "query_job":
            # 获取职位的匹配结果
            job_id = references.get("job_id")
            if job_id:
                match_result = self.memory.get_match_result(job_id)
                if match_result:
                    context["match_score"] = match_result["result"].get("score", 0)
                    context["skill_gaps"] = match_result["result"].get("skill_gaps", [])

        if intent == "compare_jobs":
            # 获取所有职位的匹配结果
            job_ids = references.get("job_ids", [])
            context["jobs_data"] = []
            for job_id in job_ids:
                job_data = self.memory.get_job_analysis(job_id)
                match_data = self.memory.get_match_result(job_id)
                if job_data and match_data:
                    context["jobs_data"].append({
                        "job_id": job_id,
                        "title": job_data["job_info"].get("title"),
                        "company": job_data["job_info"].get("company"),
                        "score": match_data["result"].get("score", 0)
                    })

        understanding["context"] = context
        return understanding

    # ==================== 生成提示 ====================

    def generate_prompt_enhancement(self, understanding: Dict[str, Any]) -> str:
        """
        生成用于增强 Agent prompt 的上下文信息

        Args:
            understanding: 理解结果

        Returns:
            上下文提示文本
        """
        intent = understanding["intent"]
        references = understanding["references"]
        context = understanding.get("context", {})

        lines = []

        if intent == "recommend_more":
            job_title = references.get("job_title", "当前职位")
            already_count = context.get("already_recommended_count", 0)
            lines.append(f"用户想要为「{job_title}」再推荐几个学习项目。")
            if already_count > 0:
                lines.append(f"已经推荐过 {already_count} 个项目，请推荐不同的项目。")

        elif intent == "query_job":
            job_title = references.get("job_title", "当前职位")
            match_score = context.get("match_score")
            lines.append(f"用户询问「{job_title}」的情况。")
            if match_score is not None:
                lines.append(f"匹配度：{match_score}分")

        elif intent == "compare_jobs":
            job_count = references.get("job_count", 0)
            lines.append(f"用户想要对比已分析的 {job_count} 个职位。")
            jobs_data = context.get("jobs_data", [])
            if jobs_data:
                lines.append("职位列表：")
                for job in jobs_data:
                    lines.append(f"  - {job['title']} @ {job['company']} (匹配度: {job['score']}分)")

        elif intent == "create_plan":
            job_title = references.get("job_title")
            if job_title:
                lines.append(f"用户想要为「{job_title}」制定学习计划。")

        return "\n".join(lines) if lines else ""

    # ==================== 简化接口 ====================

    def quick_understand(self, user_input: str) -> str:
        """
        快速理解（返回简单的意图字符串）

        Args:
            user_input: 用户输入

        Returns:
            意图字符串
        """
        return self._detect_intent(user_input)

    def get_referenced_job_id(self, user_input: str) -> Optional[str]:
        """
        获取用户输入中指代的职位ID

        Args:
            user_input: 用户输入

        Returns:
            职位ID，如果没有则返回 None
        """
        understanding = self.understand(user_input)
        return understanding["references"].get("job_id")

    # ==================== 对话补全 ====================

    def complete_user_input(self, user_input: str) -> str:
        """
        补全用户输入（将简短追问扩展为完整问题）

        Args:
            user_input: 用户输入

        Returns:
            补全后的输入
        """
        understanding = self.understand(user_input)
        intent = understanding["intent"]
        references = understanding["references"]

        if intent == "recommend_more":
            job_title = references.get("job_title", "这个职位")
            return f"为「{job_title}」再推荐几个学习项目"

        if intent == "query_job":
            job_title = references.get("job_title", "这个职位")
            return f"「{job_title}」的匹配度怎么样？有哪些技能缺口？"

        if intent == "compare_jobs":
            return "对比所有已分析的职位，帮我选择最合适的"

        if intent == "create_plan":
            job_title = references.get("job_title")
            if job_title:
                return f"为「{job_title}」制定学习计划"
            return "制定学习计划"

        # 无法补全，返回原输入
        return user_input

    # ==================== 调试信息 ====================

    def explain_understanding(self, user_input: str) -> str:
        """
        解释理解结果（用于调试）

        Args:
            user_input: 用户输入

        Returns:
            解释文本
        """
        understanding = self.understand(user_input)
        enhanced = self.enhance_with_context(understanding)

        lines = [
            "=== 上下文理解 ===",
            f"原始输入: {user_input}",
            f"意图: {enhanced['intent']}",
            f"需要上下文: {enhanced['needs_context']}",
            "",
            "指代解析:",
        ]

        for key, value in enhanced["references"].items():
            lines.append(f"  {key}: {value}")

        if enhanced.get("params"):
            lines.append("")
            lines.append("参数提取:")
            for key, value in enhanced["params"].items():
                lines.append(f"  {key}: {value}")

        if enhanced.get("context"):
            lines.append("")
            lines.append("上下文信息:")
            for key, value in enhanced["context"].items():
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)
