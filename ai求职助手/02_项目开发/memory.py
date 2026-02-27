"""
轻量记忆系统 — JSON 文件持久化用户偏好和历史搜索摘要。

结构：
{
  "user_preferences": {"cities": ["上海"], "salary_min_k": 20},
  "search_history": [
    {"date": "2026-02-25", "top_job": "AI Agent工程师", "top_score": 78, "main_gaps": ["RAG"]}
  ],
  "known_skill_gaps": ["RAG", "向量数据库"]
}
"""
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_MEMORY_FILE = Path(__file__).resolve().parent / "memory.json"

_DEFAULT: Dict[str, Any] = {
    "user_preferences": {},
    "search_history": [],
    "known_skill_gaps": [],
}


def load() -> Dict[str, Any]:
    if _MEMORY_FILE.exists():
        try:
            return json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("记忆文件读取失败，使用默认值：%s", e)
    return {k: v.copy() if isinstance(v, (list, dict)) else v for k, v in _DEFAULT.items()}


def save(memory: Dict[str, Any]) -> None:
    try:
        _MEMORY_FILE.write_text(
            json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("记忆文件保存失败：%s", e)


def append_search(memory: Dict[str, Any], top_job: str, top_score: int, main_gaps: List[str]) -> None:
    entry = {
        "date": str(date.today()),
        "top_job": top_job,
        "top_score": top_score,
        "main_gaps": main_gaps[:4],
    }
    history: List[Dict] = memory.setdefault("search_history", [])
    history.append(entry)
    memory["search_history"] = history[-10:]  # keep last 10

    known: List[str] = memory.setdefault("known_skill_gaps", [])
    for gap in main_gaps:
        if gap not in known:
            known.append(gap)
    memory["known_skill_gaps"] = known[-20:]


def build_memory_prompt(memory: Dict[str, Any]) -> str:
    parts = []
    history = memory.get("search_history", [])
    if history:
        last = history[-1]
        parts.append(
            f"上次搜索（{last['date']}）：Top职位「{last['top_job']}」匹配分{last['top_score']}，"
            f"主要差距：{', '.join(last['main_gaps'])}"
        )
    gaps = memory.get("known_skill_gaps", [])
    if gaps:
        parts.append(f"历史已知技能缺口：{', '.join(gaps[:8])}")
    return "\n".join(parts)
