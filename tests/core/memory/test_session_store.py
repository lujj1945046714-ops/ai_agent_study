import pytest
import json
from pathlib import Path
from core.memory.session_store import SessionStore


def test_save_session(temp_memory_dir):
    """Can save session state to JSON"""
    store = SessionStore(temp_memory_dir)
    session_id = "test_session_001"
    state = {
        "session_id": session_id,
        "user_profile": {"name": "测试"},
        "analyzed_jobs": {}
    }

    store.save(session_id, state)

    session_file = temp_memory_dir / "sessions" / f"{session_id}.json"
    assert session_file.exists()
    with open(session_file) as f:
        saved_data = json.load(f)
    assert saved_data == state


def test_load_session(temp_memory_dir):
    """Can load session state from JSON"""
    store = SessionStore(temp_memory_dir)
    session_id = "test_session_002"
    state = {"session_id": session_id, "data": "test"}

    store.save(session_id, state)
    loaded = store.load(session_id)

    assert loaded == state


def test_load_nonexistent_session(temp_memory_dir):
    """Returns None for nonexistent session"""
    store = SessionStore(temp_memory_dir)

    result = store.load("nonexistent")

    assert result is None


def test_delete_session(temp_memory_dir):
    """Can delete session"""
    store = SessionStore(temp_memory_dir)
    session_id = "test_session_003"
    store.save(session_id, {"data": "test"})

    store.delete(session_id)

    assert store.load(session_id) is None
    session_file = temp_memory_dir / "sessions" / f"{session_id}.json"
    assert not session_file.exists()


def test_list_sessions(temp_memory_dir):
    """Can list all sessions"""
    store = SessionStore(temp_memory_dir)
    store.save("session_1", {"data": "1"})
    store.save("session_2", {"data": "2"})

    sessions = store.list_sessions()

    assert len(sessions) == 2
    assert "session_1" in sessions
    assert "session_2" in sessions
