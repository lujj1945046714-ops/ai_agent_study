"""
Job analysis module.

Input: JD text
Output: structured requirement dict
"""

import json
import os
import re
import sys
from functools import lru_cache
from typing import Any, Dict, List

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - fallback path is runtime dependent
    OpenAI = None


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


_PROMPT = """你是一个技术岗位分析专家。分析以下职位描述（JD），提取关键信息。

严格按照下面的 JSON 格式输出，不要有任何额外内容：

{{
  "required_skills": ["必备技能1", "必备技能2"],
  "nice_to_have":    ["加分项1", "加分项2"],
  "core_work":       ["核心职责1", "核心职责2"],
  "tech_stack":      ["技术/框架/工具1", "技术/框架/工具2"],
  "job_level":       "初级 或 中级 或 高级",
  "summary":         "一句话概括这个岗位"
}}

注意：
- required_skills 只写岗位明确要求的硬技能
- nice_to_have 写"优先/加分"等字眼对应的技能
- core_work 用动词开头，描述具体做什么（不超过5条）
- tech_stack 只写工具和框架名称，不写描述

职位描述：
{jd_text}"""


_KEYWORD_MAP = {
    "python": "Python",
    "langchain": "LangChain",
    "llamaindex": "LlamaIndex",
    "autogen": "AutoGen",
    "prompt": "Prompt Engineering",
    "rag": "RAG",
    "向量": "向量数据库",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "sql": "SQL",
    "sqlite": "SQLite",
    "redis": "Redis",
    "docker": "Docker",
    "git": "Git",
    "agent": "Agent",
    "react": "ReAct",
    "cot": "CoT",
    "tree-of-thought": "Tree-of-Thought",
    "tot": "Tree-of-Thought",
}

_WORK_PREFIXES = ("负责", "设计", "开发", "实现", "优化", "搭建", "维护", "推进")
_NICE_MARKERS = ("优先", "加分", "bonus", "plus", "preferred")


@lru_cache(maxsize=1)
def _get_client():
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")
    return OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
    )


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def _extract_skills(lines: List[str]) -> Dict[str, List[str]]:
    required: List[str] = []
    nice_to_have: List[str] = []
    tech_stack: List[str] = []

    for raw_line in lines:
        line = raw_line.lower()
        for key, canonical in _KEYWORD_MAP.items():
            if key not in line:
                continue
            if canonical not in tech_stack:
                tech_stack.append(canonical)
            if any(marker in line for marker in _NICE_MARKERS):
                if canonical not in nice_to_have:
                    nice_to_have.append(canonical)
            else:
                if canonical not in required:
                    required.append(canonical)

    if "Python" not in required and "Python" in tech_stack:
        required.insert(0, "Python")

    return {
        "required_skills": required[:8],
        "nice_to_have": nice_to_have[:6],
        "tech_stack": tech_stack[:10],
    }


def _extract_core_work(lines: List[str]) -> List[str]:
    works: List[str] = []
    for raw_line in lines:
        line = _normalize_line(raw_line.lstrip("-*0123456789. "))
        if not line:
            continue
        if line.startswith(_WORK_PREFIXES) and line not in works:
            works.append(line)
        if len(works) >= 5:
            break
    return works


def _detect_job_level(text: str) -> str:
    low = text.lower()
    if any(token in low for token in ("资深", "高级", "senior", "专家", "lead")):
        return "高级"
    if any(token in low for token in ("中级", "3年", "4年", "5年")):
        return "中级"
    if any(token in low for token in ("初级", "应届", "校招", "junior", "1年")):
        return "初级"
    return "中级"


def _summarize(core_work: List[str], tech_stack: List[str]) -> str:
    if core_work:
        return f"岗位核心是{core_work[0]}，技术重点包括{', '.join(tech_stack[:3]) or '通用工程能力'}。"
    return f"岗位聚焦 AI 应用工程，技术重点包括{', '.join(tech_stack[:3]) or 'Python 与 LLM'}。"


def _heuristic_analyze_jd(jd_text: str) -> Dict[str, Any]:
    lines = [line for line in jd_text.splitlines() if line.strip()]
    skill_info = _extract_skills(lines)
    core_work = _extract_core_work(lines)
    job_level = _detect_job_level(jd_text)

    return {
        "required_skills": skill_info["required_skills"],
        "nice_to_have": skill_info["nice_to_have"],
        "core_work": core_work,
        "tech_stack": skill_info["tech_stack"],
        "job_level": job_level,
        "summary": _summarize(core_work, skill_info["tech_stack"]),
    }


def _llm_analyze_jd(jd_text: str) -> Dict[str, Any]:
    client = _get_client()
    prompt = _PROMPT.format(jd_text=jd_text)

    response = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


def _validate_result(result: Dict[str, Any]) -> Dict[str, Any]:
    required_keys = {
        "required_skills",
        "nice_to_have",
        "core_work",
        "tech_stack",
        "job_level",
        "summary",
    }
    missing = required_keys - set(result)
    if missing:
        raise ValueError(f"analysis result missing keys: {sorted(missing)}")
    return result


def analyze_jd(jd_text: str) -> Dict[str, Any]:
    """
    Analyze JD text and return structured requirements.
    Uses LLM when available, falls back to heuristic extraction for offline runs.
    """
    if config.DEEPSEEK_API_KEY and OpenAI is not None:
        try:
            return _validate_result(_llm_analyze_jd(jd_text))
        except Exception:
            pass
    return _validate_result(_heuristic_analyze_jd(jd_text))


if __name__ == "__main__":
    _MOCK_JD = """
    岗位：AI Agent 工程师
    职位描述：
    - 负责基于大语言模型的 Agent 系统设计与开发
    - 设计并实现 Multi-Agent 协作框架
    - 优化 Agent 工作流，提升任务执行成功率
    任职要求：
    - 熟练掌握 Python
    - 熟悉 LangChain / LlamaIndex
    - 有 RAG 经验优先
    """
    print(json.dumps(analyze_jd(_MOCK_JD), ensure_ascii=False, indent=2))
