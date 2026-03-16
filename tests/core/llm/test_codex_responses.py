from __future__ import annotations

import requests

from agent_framework.llm.codex_responses import CodexResponsesConfig, CodexResponsesModel


class FakeStreamResponse:
    def __init__(self, chunks, *, status_code: int = 200, text: str = ""):
        self._chunks = list(chunks)
        self.status_code = status_code
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        return None

    def iter_content(self, chunk_size=None, decode_unicode=False):
        for chunk in self._chunks:
            yield chunk


class FailingStreamResponse(FakeStreamResponse):
    def __init__(self, error: Exception, chunks=None, *, status_code: int = 200, text: str = ""):
        super().__init__(chunks or [], status_code=status_code, text=text)
        self._error = error

    def iter_content(self, chunk_size=None, decode_unicode=False):
        for chunk in self._chunks:
            yield chunk
        raise self._error


class FakeSession:
    def __init__(self, response: FakeStreamResponse | list[FakeStreamResponse]):
        self._responses = list(response) if isinstance(response, list) else [response]
        self.calls = []

    def post(self, url, *, headers=None, json=None, stream=False, timeout=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers or {},
                "json": json or {},
                "stream": stream,
                "timeout": timeout,
            }
        )
        return self._responses.pop(0)


def test_codex_responses_model_streams_cli_style_request():
    model = CodexResponsesModel(
        CodexResponsesConfig(
            api_key="test-key",
            model="gpt-5.4",
            base_url="https://yunyi.example.com/codex",
            reasoning_effort="xhigh",
        )
    )
    session = FakeSession(
        FakeStreamResponse(
            [
                'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":"}\n\n',
                'data: {"type":"response.output_text.delta","delta":"true}"}\n\n',
                'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_1","name":"echo","arguments":"{}"}}\n\n',
                'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n',
            ]
        )
    )
    model._session = session

    tokens = []
    completion = model.complete(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "return json"},
        ],
        stream=True,
        on_token=tokens.append,
        response_format={"type": "json_object"},
    )

    assert "".join(tokens) == '{"ok":true}'
    assert completion.content == '{"ok":true}'
    assert completion.tool_calls[0].id == "call_1"
    assert completion.metadata["transport"] == "codex_sse"
    assert "response.output_text.delta" in completion.metadata["event_types"]

    request = session.calls[0]
    assert request["url"] == "https://yunyi.example.com/codex/responses"
    assert request["headers"]["OpenAI-Beta"] == "responses=experimental"
    assert request["stream"] is True
    assert request["json"]["stream"] is True
    assert request["json"]["store"] is False
    assert request["json"]["instructions"] == "system prompt"
    assert request["json"]["text"] == {"verbosity": "medium"}
    assert request["json"]["include"] == ["reasoning.encrypted_content"]
    assert request["json"]["parallel_tool_calls"] is True
    assert request["json"]["reasoning"] == {"effort": "xhigh", "summary": "auto"}


def test_codex_responses_model_extracts_text_from_completed_event_without_deltas():
    model = CodexResponsesModel(
        CodexResponsesConfig(
            api_key="test-key",
            model="gpt-5.4",
            base_url="https://yunyi.example.com/codex",
        )
    )
    session = FakeSession(
        FakeStreamResponse(
            [
                'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"{\\"ok\\": true}"}]}]}}'
            ]
        )
    )
    model._session = session

    completion = model.complete(messages=[{"role": "user", "content": "return json"}])

    assert completion.content == '{"ok": true}'
    assert completion.metadata["status"] == "completed"


def test_codex_responses_model_decodes_utf8_sse_chunks_without_mojibake():
    model = CodexResponsesModel(
        CodexResponsesConfig(
            api_key="test-key",
            model="gpt-5.4",
            base_url="https://yunyi.example.com/codex",
        )
    )
    delta_frame = 'data: {"type":"response.output_text.delta","delta":"你好，世界"}\n\n'.encode("utf-8")
    split_at = delta_frame.index("你".encode("utf-8")) + 1
    session = FakeSession(
        FakeStreamResponse(
            [
                delta_frame[:split_at],
                delta_frame[split_at:],
                b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n',
            ]
        )
    )
    model._session = session

    completion = model.complete(messages=[{"role": "user", "content": "say hello"}])

    assert completion.content == "你好，世界"
    assert "你好，世界" in completion.metadata["raw_text_preview"]


def test_codex_responses_model_retries_premature_response_once_with_medium_reasoning():
    model = CodexResponsesModel(
        CodexResponsesConfig(
            api_key="test-key",
            model="gpt-5.4",
            base_url="https://yunyi.example.com/codex",
            reasoning_effort="xhigh",
        )
    )
    session = FakeSession(
        [
            FailingStreamResponse(
                requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
            ),
            FakeStreamResponse(
                [
                    'data: {"type":"response.output_text.delta","delta":"ok"}\n\n',
                    'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n',
                ]
            ),
        ]
    )
    model._session = session

    completion = model.complete(messages=[{"role": "user", "content": "say hello"}])

    assert completion.content == "ok"
    assert completion.metadata["retry_count"] == 1
    assert completion.metadata["retry_reason"] == "response_ended_prematurely"
    assert completion.metadata["effective_reasoning_effort"] == "medium"
    assert len(session.calls) == 2
    assert session.calls[0]["json"]["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert session.calls[1]["json"]["reasoning"] == {"effort": "medium", "summary": "auto"}
