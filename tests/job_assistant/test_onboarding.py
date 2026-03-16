from __future__ import annotations

import builtins

import pytest

from agent_framework.llm.types import LLMCompletion
from job_assistant.onboarding import (
    ONBOARDING_KICKOFF_PROMPT,
    _run_conversation,
    extract_profile_from_resume,
    extract_profile_from_history,
)


class SpyLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return LLMCompletion(content=self._responses.pop(0), tool_calls=[])


class DebugLLM:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)

    def complete(self, **kwargs):
        payload = self._responses.pop(0)
        return LLMCompletion(
            content=payload.get("content", ""),
            tool_calls=[],
            metadata=payload.get("metadata", {}),
        )


def test_run_conversation_seeds_first_request_with_user_kickoff(monkeypatch):
    llm = SpyLLM(
        [
            "你好，请问怎么称呼你？",
            "收到，我已经收集完成。[COLLECTION_COMPLETE]",
            '{"name":"张三","target_cities":[],"target_keywords":[],"skills":{},"experience_years":0,"education":"","experience_level":"初级","preferences":{"cities":[],"salary_min_k":0,"salary_max_k":0}}',
        ]
    )
    answers = iter(["张三"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    profile = _run_conversation(llm=llm)

    assert profile["name"] == "张三"
    first_messages = llm.calls[0]["messages"]
    assert any(
        message.get("role") == "user" and message.get("content") == ONBOARDING_KICKOFF_PROMPT
        for message in first_messages
    )


def test_extract_profile_from_resume_retries_with_non_empty_user_content():
    llm = SpyLLM(
        [
            "",
            '{"name":"李四","target_cities":[],"target_keywords":[],"skills":{},"experience_years":0,"education":"","experience_level":"初级","preferences":{"cities":[],"salary_min_k":0,"salary_max_k":0}}',
        ]
    )

    profile = extract_profile_from_resume("李四的简历", llm=llm)

    assert profile["name"] == "李四"
    retry_messages = llm.calls[1]["messages"]
    assert retry_messages[1]["role"] == "user"
    assert retry_messages[1]["content"].strip()


def test_extract_profile_from_resume_raises_when_llm_never_returns_json():
    llm = SpyLLM(["", "", ""])

    with pytest.raises(RuntimeError, match="LLM 未返回合法 JSON"):
        extract_profile_from_resume(
            "姓名：王五\n3年 Python / LangChain / RAG 经验\n期望城市：上海\n期望薪资：25-35K",
            llm=llm,
        )


def test_extract_profile_from_history_raises_when_llm_never_returns_json():
    llm = SpyLLM(["", "", ""])

    with pytest.raises(RuntimeError, match="LLM 未返回合法 JSON"):
        extract_profile_from_history(
            [
                {"role": "user", "content": "我叫赵六，2年经验，想去北京，主要做 Python 和 Agent。"},
                {"role": "assistant", "content": "收到"},
            ],
            llm=llm,
        )


def test_extract_profile_from_resume_includes_response_debug_when_empty():
    llm = DebugLLM(
        [
            {
                "content": "",
                "metadata": {
                    "status": "incomplete",
                    "output_item_types": ["reasoning"],
                    "response_preview": '{"status":"incomplete","output":[{"type":"reasoning"}]}',
                },
            },
            {
                "content": "",
                "metadata": {
                    "status": "incomplete",
                    "output_item_types": ["reasoning"],
                    "response_preview": '{"status":"incomplete","output":[{"type":"reasoning"}]}',
                },
            },
        ]
    )

    with pytest.raises(RuntimeError, match="status=incomplete"):
        extract_profile_from_resume("李四的简历", llm=llm)
