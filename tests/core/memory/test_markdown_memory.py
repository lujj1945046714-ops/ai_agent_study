import pytest
from pathlib import Path
from datetime import datetime
from agent_framework.memory.markdown_memory import MarkdownMemory


def test_create_session_file(temp_memory_dir):
    """Can create session markdown file"""
    memory = MarkdownMemory(temp_memory_dir)
    session_id = "sess_001"
    user_profile = {"name": "测试用户", "skills": ["Python"]}

    memory.create_session_file(session_id, user_profile)

    session_file = temp_memory_dir / "sessions" / f"{session_id}.md"
    assert session_file.exists()
    content = session_file.read_text(encoding="utf-8")
    assert f"# Session: {session_id}" in content
    assert "测试用户" in content


def test_append_conversation(temp_memory_dir):
    """Can append conversation turn"""
    memory = MarkdownMemory(temp_memory_dir)
    session_id = "sess_002"
    memory.create_session_file(session_id, {})

    memory.append_conversation(session_id, "帮我分析职位", "好的，我来分析")

    content = memory.read_session(session_id)
    assert "## Conversation History" in content
    assert "**User:** 帮我分析职位" in content
    assert "**Agent:** 好的，我来分析" in content


def test_append_job_analysis(temp_memory_dir):
    """Can append job analysis"""
    memory = MarkdownMemory(temp_memory_dir)
    session_id = "sess_003"
    memory.create_session_file(session_id, {})

    analysis = {
        "title": "AI工程师",
        "company": "测试公司",
        "match_score": 75
    }
    memory.append_job_analysis(session_id, "job_001", analysis)

    content = memory.read_session(session_id)
    assert "## Analyzed Jobs" in content
    assert "### Job: job_001" in content
    assert "AI工程师" in content
    assert "测试公司" in content


def test_read_session(temp_memory_dir):
    """Can read session content"""
    memory = MarkdownMemory(temp_memory_dir)
    session_id = "sess_004"
    memory.create_session_file(session_id, {"name": "用户"})

    content = memory.read_session(session_id)

    assert isinstance(content, str)
    assert len(content) > 0
    assert "用户" in content


def test_read_nonexistent_session(temp_memory_dir):
    """Returns empty string for nonexistent session"""
    memory = MarkdownMemory(temp_memory_dir)

    content = memory.read_session("nonexistent")

    assert content == ""
