# Agent Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build OpenClaw-inspired layered agent framework with TDD approach

**Architecture:** Gateway → Runtime → Tool → Memory four-layer architecture with Hooks system and Markdown memory

**Tech Stack:** Python 3.10+, pytest, OpenAI SDK, pathlib

---

## Phase 1: Project Setup & Tool Layer

### Task 1: Project Structure Setup

**Files:**
- Create: `core/__init__.py`
- Create: `core/tools/__init__.py`
- Create: `core/tools/base.py`
- Create: `core/tools/registry.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/tools/__init__.py`
- Create: `pytest.ini`

**Step 1: Create directory structure**

Run:
```bash
mkdir -p core/tools core/runtime core/gateway core/memory
mkdir -p tests/core/tools tests/core/runtime tests/core/gateway tests/core/memory
mkdir -p tools tests/tools tests/integration
mkdir -p memory/sessions
```

**Step 2: Create pytest.ini**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short --strict-markers
markers =
    unit: Unit tests
    integration: Integration tests
```

**Step 3: Create conftest.py with base fixtures**

```python
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
```

**Step 4: Commit**

```bash
git add core/ tests/ pytest.ini
git commit -m "chore: initialize project structure with pytest config

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: BaseTool Abstract Class

**Files:**
- Create: `tests/core/tools/test_base_tool.py`
- Create: `core/tools/base.py`

**Step 1: Write failing test for BaseTool interface**

File: `tests/core/tools/test_base_tool.py`
```python
import pytest
from abc import ABC
from core.tools.base import BaseTool


def test_base_tool_is_abstract():
    """BaseTool cannot be instantiated directly"""
    with pytest.raises(TypeError):
        BaseTool()


def test_base_tool_requires_name():
    """Subclass must implement name property"""
    class IncompleteTool(BaseTool):
        @property
        def description(self):
            return "test"

        @property
        def schema(self):
            return {}

        def execute(self, **kwargs):
            return {}

    with pytest.raises(TypeError):
        IncompleteTool()


def test_base_tool_requires_all_methods():
    """Subclass must implement all abstract methods"""
    class CompleteTool(BaseTool):
        @property
        def name(self):
            return "test_tool"

        @property
        def description(self):
            return "A test tool"

        @property
        def schema(self):
            return {
                "type": "object",
                "properties": {},
                "required": []
            }

        def execute(self, **kwargs):
            return {"status": "success"}

    tool = CompleteTool()
    assert tool.name == "test_tool"
    assert tool.description == "A test tool"
    assert isinstance(tool.schema, dict)
    assert tool.execute() == {"status": "success"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/tools/test_base_tool.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'core.tools.base'"

**Step 3: Implement BaseTool**

File: `core/tools/base.py`
```python
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseTool(ABC):
    """
    Abstract base class for all tools.

    All tools must implement:
    - name: Tool identifier
    - description: Human-readable description
    - schema: OpenAI function calling schema
    - execute: Tool execution logic
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (unique identifier)"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM"""
        pass

    @property
    @abstractmethod
    def schema(self) -> Dict[str, Any]:
        """
        OpenAI function calling schema.

        Format:
        {
            "type": "object",
            "properties": {
                "param_name": {
                    "type": "string",
                    "description": "..."
                }
            },
            "required": ["param_name"]
        }
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool parameters matching schema

        Returns:
            Dict with execution result
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """
        Validate parameters against schema (optional override).

        Args:
            params: Parameters to validate

        Returns:
            True if valid, False otherwise
        """
        # Basic validation: check required fields
        required = self.schema.get("required", [])
        return all(key in params for key in required)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/tools/test_base_tool.py -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add core/tools/base.py tests/core/tools/test_base_tool.py
git commit -m "feat: add BaseTool abstract class with interface contract

- Define abstract methods: name, description, schema, execute
- Add optional validate_params method
- Include comprehensive tests for abstract interface

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: ToolRegistry Implementation

**Files:**
- Create: `tests/core/tools/test_registry.py`
- Create: `core/tools/registry.py`

**Step 1: Write failing test for tool registration**

File: `tests/core/tools/test_registry.py`
```python
import pytest
from core.tools.registry import ToolRegistry
from core.tools.base import BaseTool


class MockTool(BaseTool):
    """Mock tool for testing"""
    @property
    def name(self):
        return "mock_tool"

    @property
    def description(self):
        return "A mock tool"

    @property
    def schema(self):
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            },
            "required": ["input"]
        }

    def execute(self, **kwargs):
        return {"result": kwargs.get("input", "")}


def test_registry_register_tool():
    """Can register a tool"""
    registry = ToolRegistry()
    tool = MockTool()

    registry.register(tool)

    assert "mock_tool" in registry.list_tools()


def test_registry_get_tool():
    """Can retrieve registered tool"""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    retrieved = registry.get_tool("mock_tool")

    assert retrieved is tool
    assert retrieved.name == "mock_tool"


def test_registry_get_nonexistent_tool():
    """Returns None for nonexistent tool"""
    registry = ToolRegistry()

    result = registry.get_tool("nonexistent")

    assert result is None


def test_registry_unregister_tool():
    """Can unregister a tool"""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    registry.unregister("mock_tool")

    assert "mock_tool" not in registry.list_tools()
    assert registry.get_tool("mock_tool") is None


def test_registry_get_schemas():
    """Can get all tool schemas for LLM"""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    schemas = registry.get_schemas()

    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "mock_tool"
    assert schemas[0]["function"]["description"] == "A mock tool"
    assert "parameters" in schemas[0]["function"]


def test_registry_duplicate_registration():
    """Registering same tool twice replaces the old one"""
    registry = ToolRegistry()
    tool1 = MockTool()
    tool2 = MockTool()

    registry.register(tool1)
    registry.register(tool2)

    assert len(registry.list_tools()) == 1
    assert registry.get_tool("mock_tool") is tool2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/tools/test_registry.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'core.tools.registry'"

**Step 3: Implement ToolRegistry**

File: `core/tools/registry.py`
```python
from typing import Dict, List, Optional
from core.tools.base import BaseTool


class ToolRegistry:
    """
    Registry for managing tools dynamically.

    Supports:
    - Register/unregister tools
    - Query tools by name
    - Generate schemas for LLM
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool instance to register
        """
        self._tools[tool.name] = tool

    def unregister(self, tool_name: str) -> None:
        """
        Unregister a tool.

        Args:
            tool_name: Name of tool to unregister
        """
        self._tools.pop(tool_name, None)

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """
        Get tool by name.

        Args:
            tool_name: Tool name

        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """
        List all registered tool names.

        Returns:
            List of tool names
        """
        return list(self._tools.keys())

    def get_schemas(self) -> List[Dict]:
        """
        Get all tool schemas in OpenAI function calling format.

        Returns:
            List of tool schemas
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema
                }
            })
        return schemas
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/tools/test_registry.py -v`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add core/tools/registry.py tests/core/tools/test_registry.py
git commit -m "feat: add ToolRegistry for dynamic tool management

- Support register/unregister tools
- Query tools by name
- Generate OpenAI function calling schemas
- Handle duplicate registration

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 2: Memory Layer

### Task 4: SessionStore Implementation

**Files:**
- Create: `tests/core/memory/__init__.py`
- Create: `tests/core/memory/test_session_store.py`
- Create: `core/memory/__init__.py`
- Create: `core/memory/session_store.py`

**Step 1: Write failing test for session save/load**

File: `tests/core/memory/test_session_store.py`
```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/memory/test_session_store.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement SessionStore**

File: `core/memory/session_store.py`
```python
import json
from pathlib import Path
from typing import Dict, List, Optional, Any


class SessionStore:
    """
    Store session state in JSON format.

    Storage structure:
    memory_dir/
      sessions/
        session_001.json
        session_002.json
    """

    def __init__(self, memory_dir: Path):
        """
        Initialize session store.

        Args:
            memory_dir: Base memory directory
        """
        self.memory_dir = Path(memory_dir)
        self.sessions_dir = self.memory_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, state: Dict[str, Any]) -> None:
        """
        Save session state.

        Args:
            session_id: Session identifier
            state: Session state dict
        """
        session_file = self.sessions_dir / f"{session_id}.json"
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def load(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load session state.

        Args:
            session_id: Session identifier

        Returns:
            Session state dict or None if not found
        """
        session_file = self.sessions_dir / f"{session_id}.json"
        if not session_file.exists():
            return None

        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete(self, session_id: str) -> None:
        """
        Delete session.

        Args:
            session_id: Session identifier
        """
        session_file = self.sessions_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()

    def list_sessions(self) -> List[str]:
        """
        List all session IDs.

        Returns:
            List of session IDs
        """
        return [f.stem for f in self.sessions_dir.glob("*.json")]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/memory/test_session_store.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add core/memory/session_store.py tests/core/memory/test_session_store.py
git commit -m "feat: add SessionStore for JSON session persistence

- Save/load session state
- Delete sessions
- List all sessions
- Auto-create sessions directory

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: MarkdownMemory Implementation

**Files:**
- Create: `tests/core/memory/test_markdown_memory.py`
- Create: `core/memory/markdown_memory.py`

**Step 1: Write failing test for Markdown memory**

File: `tests/core/memory/test_markdown_memory.py`
```python
import pytest
from pathlib import Path
from datetime import datetime
from core.memory.markdown_memory import MarkdownMemory


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/memory/test_markdown_memory.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement MarkdownMemory**

File: `core/memory/markdown_memory.py`
```python
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


class MarkdownMemory:
    """
    Store conversation history in Markdown format.

    Human-readable format for easy review and version control.
    """

    def __init__(self, memory_dir: Path):
        """
        Initialize Markdown memory.

        Args:
            memory_dir: Base memory directory
        """
        self.memory_dir = Path(memory_dir)
        self.sessions_dir = self.memory_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session_file(self, session_id: str, user_profile: Dict[str, Any]) -> None:
        """
        Create new session markdown file.

        Args:
            session_id: Session identifier
            user_profile: User profile dict
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        content = f"""# Session: {session_id}

**Started:** {timestamp}
**User Profile:** {user_profile.get('name', 'Unknown')}

---

## Conversation History

"""
        session_file.write_text(content, encoding="utf-8")

    def append_conversation(self, session_id: str, user_msg: str, agent_msg: str) -> None:
        """
        Append conversation turn.

        Args:
            session_id: Session identifier
            user_msg: User message
            agent_msg: Agent response
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        if not session_file.exists():
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        turn = f"""
### Turn ({timestamp})
**User:** {user_msg}
**Agent:** {agent_msg}

"""
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(turn)

    def append_job_analysis(self, session_id: str, job_id: str, analysis: Dict[str, Any]) -> None:
        """
        Append job analysis.

        Args:
            session_id: Session identifier
            job_id: Job identifier
            analysis: Analysis result dict
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        if not session_file.exists():
            return

        content = session_file.read_text(encoding="utf-8")
        if "## Analyzed Jobs" not in content:
            with open(session_file, "a", encoding="utf-8") as f:
                f.write("\n---\n\n## Analyzed Jobs\n\n")

        job_section = f"""
### Job: {job_id}
- **Title:** {analysis.get('title', 'N/A')}
- **Company:** {analysis.get('company', 'N/A')}
- **Match Score:** {analysis.get('match_score', 'N/A')}

"""
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(job_section)

    def read_session(self, session_id: str) -> str:
        """
        Read session content.

        Args:
            session_id: Session identifier

        Returns:
            Session markdown content or empty string
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        if not session_file.exists():
            return ""

        return session_file.read_text(encoding="utf-8")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/memory/test_markdown_memory.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add core/memory/markdown_memory.py tests/core/memory/test_markdown_memory.py
git commit -m "feat: add MarkdownMemory for human-readable conversation logs

- Create session files with header
- Append conversation turns with timestamps
- Append job analysis sections
- Read session content

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 3: Runtime Layer

### Task 6: ContextManager Implementation

**Files:**
- Create: `tests/core/runtime/__init__.py`
- Create: `tests/core/runtime/test_context.py`
- Create: `core/runtime/__init__.py`
- Create: `core/runtime/context.py`

**Step 1: Write failing test for context management**

File: `tests/core/runtime/test_context.py`
```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/runtime/test_context.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement ContextManager**

File: `core/runtime/context.py`
```python
from typing import Dict, List, Any


class ContextManager:
    """
    Manage conversation context and system prompts.
    """

    def __init__(self):
        self._messages: List[Dict[str, str]] = []

    def build_system_prompt(self, user_profile: Dict[str, Any], memory_context: str) -> str:
        """
        Build system prompt from user profile and memory.

        Args:
            user_profile: User profile dict
            memory_context: Memory context string

        Returns:
            System prompt string
        """
        skills = ", ".join(user_profile.get("skills", []))
        roles = ", ".join(user_profile.get("target_roles", []))

        prompt = f"""你是一个专业的 AI 求职助手 Agent。

## 用户画像
- 姓名: {user_profile.get('name', '未知')}
- 技能: {skills}
- 经验: {user_profile.get('experience_years', 0)} 年
- 目标职位: {roles}

## 历史记忆
{memory_context}

## 工作原则
1. 分析职位要求，计算匹配度
2. 找出技能缺口
3. 推荐学习项目
4. 生成求职报告
"""
        return prompt

    def add_message(self, role: str, content: str) -> None:
        """
        Add message to context.

        Args:
            role: Message role (user/assistant/system)
            content: Message content
        """
        self._messages.append({"role": role, "content": content})

    def get_messages(self) -> List[Dict[str, str]]:
        """
        Get all messages.

        Returns:
            List of message dicts
        """
        return self._messages.copy()

    def clear(self) -> None:
        """Clear all messages"""
        self._messages.clear()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/runtime/test_context.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add core/runtime/context.py tests/core/runtime/test_context.py
git commit -m "feat: add ContextManager for conversation context

- Build system prompt from user profile
- Add/get messages
- Clear context

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 7: HooksRegistry Implementation

**Files:**
- Create: `tests/core/gateway/__init__.py`
- Create: `tests/core/gateway/test_hooks.py`
- Create: `core/gateway/__init__.py`
- Create: `core/gateway/hooks.py`

**Step 1: Write failing test for hooks system**

File: `tests/core/gateway/test_hooks.py`
```python
import pytest
from core.gateway.hooks import HooksRegistry


def test_register_hook():
    """Can register a hook"""
    hooks = HooksRegistry()
    called = []

    def callback(context):
        called.append(context)

    hooks.register("on_startup", callback)
    hooks.trigger("on_startup", {"data": "test"})

    assert len(called) == 1
    assert called[0] == {"data": "test"}


def test_trigger_multiple_hooks():
    """Multiple hooks execute in order"""
    hooks = HooksRegistry()
    order = []

    def callback1(ctx):
        order.append(1)

    def callback2(ctx):
        order.append(2)

    hooks.register("before_tool", callback1)
    hooks.register("before_tool", callback2)
    hooks.trigger("before_tool", {})

    assert order == [1, 2]


def test_unregister_hook():
    """Can unregister a hook"""
    hooks = HooksRegistry()
    called = []

    def callback(ctx):
        called.append(1)

    hooks.register("on_error", callback)
    hooks.unregister("on_error", callback)
    hooks.trigger("on_error", {})

    assert len(called) == 0


def test_trigger_nonexistent_hook():
    """Triggering nonexistent hook does nothing"""
    hooks = HooksRegistry()

    # Should not raise error
    hooks.trigger("nonexistent", {})


def test_hook_exception_handling():
    """Hook exceptions are caught and logged"""
    hooks = HooksRegistry()
    called = []

    def bad_callback(ctx):
        raise ValueError("Hook error")

    def good_callback(ctx):
        called.append(1)

    hooks.register("after_tool", bad_callback)
    hooks.register("after_tool", good_callback)

    # Should not raise, good_callback should still run
    hooks.trigger("after_tool", {})

    assert len(called) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/gateway/test_hooks.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement HooksRegistry**

File: `core/gateway/hooks.py`
```python
import logging
from typing import Dict, List, Callable, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class HooksRegistry:
    """
    Registry for lifecycle hooks.

    Supported hooks:
    - on_startup, on_shutdown
    - before_message, after_message
    - before_tool, after_tool
    - on_error
    """

    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)

    def register(self, hook_name: str, callback: Callable) -> None:
        """
        Register a hook callback.

        Args:
            hook_name: Hook name
            callback: Callback function(context: Dict) -> None
        """
        self._hooks[hook_name].append(callback)

    def unregister(self, hook_name: str, callback: Callable) -> None:
        """
        Unregister a hook callback.

        Args:
            hook_name: Hook name
            callback: Callback to remove
        """
        if hook_name in self._hooks:
            try:
                self._hooks[hook_name].remove(callback)
            except ValueError:
                pass

    def trigger(self, hook_name: str, context: Dict[str, Any]) -> None:
        """
        Trigger all callbacks for a hook.

        Args:
            hook_name: Hook name
            context: Context dict passed to callbacks
        """
        for callback in self._hooks.get(hook_name, []):
            try:
                callback(context)
            except Exception as e:
                logger.error(f"Hook {hook_name} callback failed: {e}", exc_info=True)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/gateway/test_hooks.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add core/gateway/hooks.py tests/core/gateway/test_hooks.py
git commit -m "feat: add HooksRegistry for lifecycle hooks

- Register/unregister hooks
- Trigger hooks with context
- Handle hook exceptions gracefully
- Support multiple callbacks per hook

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 8: ToolDispatcher Implementation

**Files:**
- Create: `tests/core/runtime/test_tool_dispatcher.py`
- Create: `core/runtime/tool_dispatcher.py`

**Step 1: Write failing test for tool dispatcher**

File: `tests/core/runtime/test_tool_dispatcher.py`
```python
import pytest
from unittest.mock import Mock
from core.runtime.tool_dispatcher import ToolDispatcher, ToolCall, ToolResult
from core.tools.registry import ToolRegistry
from core.tools.base import BaseTool
from core.gateway.hooks import HooksRegistry


class MockTool(BaseTool):
    @property
    def name(self):
        return "mock_tool"

    @property
    def description(self):
        return "Mock"

    @property
    def schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return {"result": "success", "input": kwargs}


def test_dispatch_tool_call():
    """Can dispatch tool call"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(MockTool())
    dispatcher = ToolDispatcher(registry, hooks)

    tool_call = ToolCall(id="call_1", name="mock_tool", arguments={"arg": "value"})
    result = dispatcher.dispatch(tool_call)

    assert isinstance(result, ToolResult)
    assert result.tool_call_id == "call_1"
    assert result.success is True
    assert result.output["result"] == "success"


def test_dispatch_nonexistent_tool():
    """Handles nonexistent tool gracefully"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    dispatcher = ToolDispatcher(registry, hooks)

    tool_call = ToolCall(id="call_2", name="nonexistent", arguments={})
    result = dispatcher.dispatch(tool_call)

    assert result.success is False
    assert "not found" in result.error.lower()


def test_dispatch_tool_error():
    """Handles tool execution error"""
    class ErrorTool(BaseTool):
        @property
        def name(self):
            return "error_tool"

        @property
        def description(self):
            return "Error"

        @property
        def schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            raise ValueError("Tool error")

    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(ErrorTool())
    dispatcher = ToolDispatcher(registry, hooks)

    tool_call = ToolCall(id="call_3", name="error_tool", arguments={})
    result = dispatcher.dispatch(tool_call)

    assert result.success is False
    assert "Tool error" in result.error


def test_dispatch_triggers_hooks():
    """Dispatching triggers before/after hooks"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(MockTool())
    dispatcher = ToolDispatcher(registry, hooks)

    called_hooks = []

    def before_hook(ctx):
        called_hooks.append("before")

    def after_hook(ctx):
        called_hooks.append("after")

    hooks.register("before_tool", before_hook)
    hooks.register("after_tool", after_hook)

    tool_call = ToolCall(id="call_4", name="mock_tool", arguments={})
    dispatcher.dispatch(tool_call)

    assert called_hooks == ["before", "after"]


def test_dispatch_batch():
    """Can dispatch multiple tool calls"""
    registry = ToolRegistry()
    hooks = HooksRegistry()
    registry.register(MockTool())
    dispatcher = ToolDispatcher(registry, hooks)

    tool_calls = [
        ToolCall(id="call_5", name="mock_tool", arguments={"n": 1}),
        ToolCall(id="call_6", name="mock_tool", arguments={"n": 2})
    ]
    results = dispatcher.dispatch_batch(tool_calls)

    assert len(results) == 2
    assert all(r.success for r in results)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/runtime/test_tool_dispatcher.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement ToolDispatcher**

File: `core/runtime/tool_dispatcher.py`
```python
import logging
from typing import List, Dict, Any
from dataclasses import dataclass
from core.tools.registry import ToolRegistry
from core.gateway.hooks import HooksRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Tool call request"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Tool execution result"""
    tool_call_id: str
    success: bool
    output: Dict[str, Any] = None
    error: str = None


class ToolDispatcher:
    """
    Dispatch tool calls to registered tools.
    """

    def __init__(self, tool_registry: ToolRegistry, hooks: HooksRegistry):
        """
        Initialize dispatcher.

        Args:
            tool_registry: Tool registry
            hooks: Hooks registry
        """
        self.registry = tool_registry
        self.hooks = hooks

    def dispatch(self, tool_call: ToolCall) -> ToolResult:
        """
        Dispatch single tool call.

        Args:
            tool_call: Tool call request

        Returns:
            Tool result
        """
        # Trigger before_tool hook
        self.hooks.trigger("before_tool", {
            "tool_name": tool_call.name,
            "arguments": tool_call.arguments
        })

        # Get tool
        tool = self.registry.get_tool(tool_call.name)
        if tool is None:
            result = ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=f"Tool '{tool_call.name}' not found"
            )
            self.hooks.trigger("after_tool", {"result": result})
            return result

        # Execute tool
        try:
            output = tool.execute(**tool_call.arguments)
            result = ToolResult(
                tool_call_id=tool_call.id,
                success=True,
                output=output
            )
        except Exception as e:
            logger.error(f"Tool {tool_call.name} execution failed: {e}", exc_info=True)
            result = ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=str(e)
            )

        # Trigger after_tool hook
        self.hooks.trigger("after_tool", {"result": result})

        return result

    def dispatch_batch(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """
        Dispatch multiple tool calls.

        Args:
            tool_calls: List of tool calls

        Returns:
            List of tool results
        """
        return [self.dispatch(tc) for tc in tool_calls]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/runtime/test_tool_dispatcher.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add core/runtime/tool_dispatcher.py tests/core/runtime/test_tool_dispatcher.py
git commit -m "feat: add ToolDispatcher for tool execution

- Dispatch tool calls to registry
- Handle tool not found errors
- Handle tool execution errors
- Trigger before/after hooks
- Support batch dispatch

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Summary & Next Steps

**Completed:**
- ✅ Project structure and pytest setup
- ✅ Tool Layer: BaseTool, ToolRegistry
- ✅ Memory Layer: SessionStore, MarkdownMemory
- ✅ Runtime Layer: ContextManager, ToolDispatcher
- ✅ Gateway Layer: HooksRegistry

**Remaining Tasks:**
- ReactEngine (ReAct loop with LLM)
- SessionManager (session lifecycle)
- MessageRouter (message routing)
- Business tools migration (search_jobs, analyze_job, etc.)
- Integration tests
- CLI/Web UI integration

**Plan complete and saved to `docs/plans/2026-03-04-agent-framework-implementation.md`.**

Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach would you like?



