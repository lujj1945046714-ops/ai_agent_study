from __future__ import annotations

from types import SimpleNamespace

from agent_framework.llm.openai_responses import OpenAIResponsesConfig, OpenAIResponsesModel


class FakeResponseStream:
    def __init__(self, events, final_response):
        self._events = events
        self._final_response = final_response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        return None

    def __iter__(self):
        return iter(self._events)

    def get_final_response(self):
        return self._final_response


class FakeResponsesAPI:
    def __init__(self, *, create_response=None, stream_events=None, final_response=None):
        self.create_response = create_response
        self.stream_events = stream_events or []
        self.final_response = final_response
        self.raw_json = None
        self.raw_text = ""
        self.create_calls = []
        self.stream_calls = []
        self.create_exception = None
        self.stream_exception = None
        self.with_raw_response = FakeResponsesWithRawResponse(self)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.create_exception is not None:
            exc = self.create_exception
            self.create_exception = None
            raise exc
        return self.create_response

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        if self.stream_exception is not None:
            raise self.stream_exception
        return FakeResponseStream(self.stream_events, self.final_response)


class FakeClient:
    def __init__(self, responses_api: FakeResponsesAPI):
        self.responses = responses_api


class FakeRawHTTPResponse:
    def __init__(self, parsed_response, raw_json, raw_text):
        self._parsed_response = parsed_response
        self._raw_json = raw_json
        self._raw_text = raw_text

    def parse(self):
        return self._parsed_response

    def json(self):
        return self._raw_json

    def text(self):
        return self._raw_text


class FakeResponsesWithRawResponse:
    def __init__(self, api: FakeResponsesAPI):
        self._api = api

    def create(self, **kwargs):
        self._api.create_calls.append(kwargs)
        if self._api.create_exception is not None:
            exc = self._api.create_exception
            self._api.create_exception = None
            raise exc
        return FakeRawHTTPResponse(self._api.create_response, self._api.raw_json, self._api.raw_text)


class FakeUpstreamError(RuntimeError):
    def __init__(self, message: str = "upstream error", status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def test_responses_model_translates_messages_and_tools():
    create_response = SimpleNamespace(
        output_text="done",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_1",
                name="search_jobs",
                arguments='{"query":"agent"}',
            )
        ],
    )
    responses_api = FakeResponsesAPI(create_response=create_response)
    model = OpenAIResponsesModel(OpenAIResponsesConfig(api_key="test-key", model="gpt-test", base_url="https://llm.test"))
    model._client = FakeClient(responses_api)

    completion = model.complete(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "帮我找岗位"},
            {
                "role": "assistant",
                "content": "先搜索一下",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search_jobs", "arguments": '{"query":"agent"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"items": []}'},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_jobs",
                    "description": "Search jobs",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            }
        ],
        response_format={"type": "json_object"},
    )

    assert completion.content == "done"
    assert completion.tool_calls[0].id == "call_1"
    assert completion.tool_calls[0].name == "search_jobs"

    request = responses_api.create_calls[0]
    assert request["instructions"] == "system prompt"
    assert request["input"][0]["role"] == "user"
    assert request["input"][1]["role"] == "assistant"
    assert request["input"][2]["type"] == "function_call"
    assert request["input"][3]["type"] == "function_call_output"
    assert request["tools"][0]["name"] == "search_jobs"
    assert request["text"] == {"format": {"type": "json_object"}}


def test_responses_model_compat_mode_omits_optional_fields():
    create_response = SimpleNamespace(output_text='{"ok": true}', output=[])
    responses_api = FakeResponsesAPI(create_response=create_response)
    model = OpenAIResponsesModel(
        OpenAIResponsesConfig(
            api_key="test-key",
            model="gpt-test",
            base_url="https://llm.test",
            compat_mode="auto",
        )
    )
    model._client = FakeClient(responses_api)

    completion = model.complete(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "return json"},
            {"role": "assistant", "content": "draft"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_jobs",
                    "description": "Search jobs",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            }
        ],
        tool_choice="auto",
        response_format={"type": "json_object"},
    )

    assert completion.content == '{"ok": true}'
    request = responses_api.create_calls[0]
    assert request["text"] == {"format": {"type": "json_object"}}
    assert "tool_choice" not in request
    assert "phase" not in request["input"][1]
    assert "strict" not in request["tools"][0]


def test_responses_model_extracts_text_from_output_items_when_output_text_empty():
    create_response = SimpleNamespace(
        output_text="",
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(type="output_text", text='{"ok": true}'),
                ],
            )
        ],
    )
    responses_api = FakeResponsesAPI(create_response=create_response)
    model = OpenAIResponsesModel(OpenAIResponsesConfig(api_key="test-key", model="gpt-test"))
    model._client = FakeClient(responses_api)

    completion = model.complete(messages=[{"role": "user", "content": "return json"}])

    assert completion.content == '{"ok": true}'
    assert completion.metadata["status"] == ""
    assert completion.metadata["output_item_types"] == ["message"]


def test_responses_model_uses_output_parsed_when_text_empty():
    create_response = SimpleNamespace(
        output_text="",
        output=[],
        output_parsed={"ok": True},
        status="completed",
    )
    responses_api = FakeResponsesAPI(create_response=create_response)
    model = OpenAIResponsesModel(OpenAIResponsesConfig(api_key="test-key", model="gpt-test"))
    model._client = FakeClient(responses_api)

    completion = model.complete(messages=[{"role": "user", "content": "return json"}])

    assert completion.content == '{"ok": true}'
    assert completion.metadata["output_parsed_preview"] == '{"ok": true}'


def test_responses_model_falls_back_to_raw_json_when_provider_uses_nonstandard_shape():
    create_response = SimpleNamespace(
        output_text="",
        output=[],
        output_parsed=None,
        status="completed",
    )
    responses_api = FakeResponsesAPI(create_response=create_response)
    responses_api.raw_json = {
        "id": "resp_x",
        "status": "completed",
        "choices": [
            {
                "message": {
                    "content": '{"ok": true}',
                }
            }
        ],
    }
    model = OpenAIResponsesModel(OpenAIResponsesConfig(api_key="test-key", model="gpt-test"))
    model._client = FakeClient(responses_api)

    completion = model.complete(messages=[{"role": "user", "content": "return json"}])

    assert completion.content == '{"ok": true}'
    assert '"choices"' in completion.metadata["raw_json_preview"]


def test_responses_model_falls_back_to_raw_text_when_raw_json_unavailable():
    create_response = SimpleNamespace(
        output_text="",
        output=[],
        output_parsed=None,
        status="completed",
    )
    responses_api = FakeResponsesAPI(create_response=create_response)
    responses_api.raw_text = '{"choices":[{"message":{"content":"{\\"ok\\": true}"}}]}'
    model = OpenAIResponsesModel(OpenAIResponsesConfig(api_key="test-key", model="gpt-test"))
    model._client = FakeClient(responses_api)

    completion = model.complete(messages=[{"role": "user", "content": "return json"}])

    assert completion.content == '{"ok": true}'
    assert '"choices"' in completion.metadata["raw_text_preview"]


def test_responses_model_streams_tokens_and_collects_tool_calls():
    final_response = SimpleNamespace(
        output_text="Hello",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_2",
                name="echo",
                arguments='{"text":"hi"}',
            )
        ],
    )
    responses_api = FakeResponsesAPI(
        stream_events=[
            SimpleNamespace(type="response.output_text.delta", delta="Hel"),
            SimpleNamespace(type="response.output_text.delta", delta="lo"),
            SimpleNamespace(
                type="response.output_item.done",
                item=SimpleNamespace(
                    type="function_call",
                    call_id="call_2",
                    name="echo",
                    arguments='{"text":"hi"}',
                ),
            ),
        ],
        final_response=final_response,
    )
    model = OpenAIResponsesModel(OpenAIResponsesConfig(api_key="test-key", model="gpt-test"))
    model._client = FakeClient(responses_api)

    tokens = []
    completion = model.complete(
        messages=[{"role": "user", "content": "say hello"}],
        stream=True,
        on_token=tokens.append,
    )

    assert "".join(tokens) == "Hello"
    assert completion.content == "Hello"
    assert completion.tool_calls == [completion.tool_calls[0]]
    assert completion.tool_calls[0].id == "call_2"
    assert completion.tool_calls[0].name == "echo"


def test_responses_model_retries_streaming_with_non_stream_create():
    create_response = SimpleNamespace(output_text="fallback", output=[])
    responses_api = FakeResponsesAPI(create_response=create_response)
    responses_api.stream_exception = FakeUpstreamError()

    model = OpenAIResponsesModel(
        OpenAIResponsesConfig(api_key="test-key", model="gpt-test", compat_mode="auto")
    )
    model._client = FakeClient(responses_api)

    completion = model.complete(
        messages=[{"role": "user", "content": "say hello"}],
        stream=True,
    )

    assert completion.content == "fallback"
    assert len(responses_api.stream_calls) == 1
    assert len(responses_api.create_calls) == 1


def test_responses_model_auto_mode_retries_without_text_on_unsupported_400():
    create_response = SimpleNamespace(output_text='{"ok": true}', output=[])
    responses_api = FakeResponsesAPI(create_response=create_response)

    class FakeUnsupportedTextError(RuntimeError):
        def __init__(self):
            super().__init__("unknown parameter: text.format")
            self.status_code = 400

    responses_api.create_exception = FakeUnsupportedTextError()

    model = OpenAIResponsesModel(
        OpenAIResponsesConfig(api_key="test-key", model="gpt-test", compat_mode="auto")
    )
    model._client = FakeClient(responses_api)

    completion = model.complete(
        messages=[{"role": "user", "content": "return json"}],
        response_format={"type": "json_object"},
    )

    assert completion.content == '{"ok": true}'
    assert len(responses_api.create_calls) == 2
    assert "text" in responses_api.create_calls[0]
    assert "text" not in responses_api.create_calls[1]
