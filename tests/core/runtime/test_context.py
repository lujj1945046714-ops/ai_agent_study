import pytest
from core.runtime.context import ContextManager


def test_build_system_prompt(sample_user_profile):
    """Can build system prompt"""
    ctx = ContextManager()

    prompt = ctx.build_system_prompt(sample_user_profile, "记忆上下文")

    assert "测试用户" in prompt or "AI Agent 工程师" in prompt
    assert "记忆上下文" in prompt


def test_add_message():
    """Can add messages"""
    ctx = ContextManager()

    ctx.add_message("user", "Hello")
    ctx.add_message("assistant", "Hi there")

    messages = ctx.get_messages()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[1]["role"] == "assistant"


def test_get_messages_empty():
    """Returns empty list initially"""
    ctx = ContextManager()

    messages = ctx.get_messages()

    assert messages == []


def test_clear_context():
    """Can clear all messages"""
    ctx = ContextManager()
    ctx.add_message("user", "Test")

    ctx.clear()

    assert ctx.get_messages() == []
