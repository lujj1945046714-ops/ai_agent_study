from __future__ import annotations

import json

from agent_framework.llm.codex_responses import CodexResponsesModel
from agent_framework.llm.openai_compatible import OpenAICompatibleChatModel
from agent_framework.llm.types import LLMCompletion
from job_assistant.llm_runtime import (
    complete_json,
    complete_json_flexible,
    create_chat_model,
    resolve_llm_config,
)


class FakeLLM:
    def __init__(self, content: str | list[str]):
        self._contents = [content] if isinstance(content, str) else list(content)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return LLMCompletion(content=self._contents.pop(0), tool_calls=[])


class FakeDebugLLM:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)

    def complete(self, **kwargs):
        payload = self._responses.pop(0)
        return LLMCompletion(
            content=payload.get("content", ""),
            tool_calls=[],
            metadata=payload.get("metadata", {}),
        )


def test_resolve_llm_config_uses_legacy_deepseek_env():
    config = resolve_llm_config(
        env={
            "DEEPSEEK_API_KEY": "deepseek-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-chat",
        }
    )

    assert config.provider == "openai_compatible"
    assert config.api_key == "deepseek-key"
    assert config.base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-chat"
    assert config.wire_api == "chat_completions"
    assert config.responses_compat_mode == "off"


def test_resolve_llm_config_reads_codex_files(tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "codex-key"}), encoding="utf-8")
    (codex_home / "config.toml").write_text(
        """
model_provider = "yunyi"
model = "gpt-5.4"
model_reasoning_effort = "xhigh"
disable_response_storage = true

[model_providers.yunyi]
base_url = "https://yunyi.example.com/codex"
wire_api = "responses"
requires_openai_auth = true
""".strip(),
        encoding="utf-8",
    )

    config = resolve_llm_config(
        env={"JOB_ASSISTANT_LLM_PROVIDER": "codex"},
        codex_home=codex_home,
    )

    assert config.provider == "codex"
    assert config.api_key == "codex-key"
    assert config.base_url == "https://yunyi.example.com/codex"
    assert config.model == "gpt-5.4"
    assert config.wire_api == "responses"
    assert config.responses_compat_mode == "auto"
    assert config.reasoning_effort == "xhigh"
    assert config.store is False


def test_create_chat_model_chooses_responses_for_codex(tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    (codex_home / "config.toml").write_text(
        """
model_provider = "yunyi"
model = "gpt-5.4"
model_reasoning_effort = "xhigh"

[model_providers.yunyi]
base_url = "https://yunyi.example.com/codex"
wire_api = "responses"
experimental_bearer_token = "codex-key"
""".strip(),
        encoding="utf-8",
    )

    resolved = resolve_llm_config(
        env={"JOB_ASSISTANT_LLM_PROVIDER": "codex"},
        codex_home=codex_home,
    )

    assert isinstance(create_chat_model(resolved), CodexResponsesModel)
    assert resolved.api_key == "codex-key"
    assert resolved.reasoning_effort == "xhigh"


def test_create_chat_model_chooses_chat_completions_for_legacy_env():
    resolved = resolve_llm_config(
        env={
            "DEEPSEEK_API_KEY": "deepseek-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-chat",
        }
    )

    assert isinstance(create_chat_model(resolved), OpenAICompatibleChatModel)


def test_complete_json_strips_code_fence():
    payload = complete_json(
        [{"role": "user", "content": "return json"}],
        llm=FakeLLM("```json\n{\"ok\": true}\n```"),
    )

    assert payload == {"ok": True}


def test_complete_json_repairs_non_json_output():
    llm = FakeLLM(
        [
            "当然可以，结果如下：name=张三, score=95",
            '{"name":"张三","score":95}',
        ]
    )

    payload = complete_json(
        [{"role": "user", "content": "return json"}],
        llm=llm,
    )

    assert payload == {"name": "张三", "score": 95}
    assert len(llm.calls) == 2
    assert llm.calls[1]["messages"][0]["role"] == "system"


def test_complete_json_retries_generation_when_first_response_empty():
    llm = FakeLLM(
        [
            "",
            '{"ok":true}',
        ]
    )

    payload = complete_json(
        [{"role": "user", "content": "return json"}],
        llm=llm,
    )

    assert payload == {"ok": True}
    assert len(llm.calls) == 2
    assert llm.calls[1]["messages"][-1]["content"].startswith("请严格只返回单个合法 JSON")


def test_complete_json_flexible_requests_json_object():
    llm = FakeLLM('{"ok": true}')

    payload = complete_json_flexible(
        [{"role": "user", "content": "return json"}],
        llm=llm,
    )

    assert payload == {"ok": True}
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_complete_json_flexible_surfaces_response_metadata_when_empty():
    llm = FakeDebugLLM(
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

    try:
        complete_json_flexible(
            [{"role": "user", "content": "return json"}],
            llm=llm,
        )
    except json.JSONDecodeError as exc:
        assert "status=incomplete" in exc.doc
        assert "output_item_types=['reasoning']" in exc.doc
        assert "response_preview=" in exc.doc
    else:  # pragma: no cover
        raise AssertionError("expected JSONDecodeError")
