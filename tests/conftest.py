import pytest
from pathlib import Path
from unittest.mock import Mock

@pytest.fixture
def temp_memory_dir(tmp_path):
    """Provide temporary memory directory"""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return memory_dir

@pytest.fixture
def sample_user_profile():
    """Provide sample user profile"""
    return {
        "name": "测试用户",
        "skills": ["Python", "LLM", "Agent"],
        "experience_years": 3,
        "target_roles": ["AI Agent 工程师"]
    }
