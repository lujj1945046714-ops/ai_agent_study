from __future__ import annotations

import base64
import codecs
import json
import logging
import platform
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

from agent_framework.llm.openai_responses import OpenAIResponsesConfig, OpenAIResponsesModel
from agent_framework.llm.types import LLMCompletion, Message, OnToken, ToolCall, ToolSchema

logger = logging.getLogger(__name__)

_JWT_CLAIM_PATH = "https://api.openai.com/auth"


@dataclass(frozen=True)
class CodexResponsesConfig:
    api_key: str
    model: str
    base_url: Optional[str] = None
    reasoning_effort: Optional[str] = None
    text_verbosity: str = "medium"
    store: bool = False


class CodexResponsesModel(OpenAIResponsesModel):
    def __init__(self, config: CodexResponsesConfig):
        super().__init__(
            OpenAIResponsesConfig(
                api_key=config.api_key,
                model=config.model,
                base_url=config.base_url,
                compat_mode="auto",
            )
        )
        self._codex_api_key = config.api_key
        self._codex_base_url = config.base_url
        self._reasoning_effort = config.reasoning_effort
        self._text_verbosity = config.text_verbosity or "medium"
        self._store = bool(config.store)
        self._session = requests.Session()
        self._timeout = (20.0, 60.0)

    def complete(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        tool_choice: str = "auto",
        stream: bool = False,
        on_token: Optional[OnToken] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> LLMCompletion:
        try:
            return self._complete_once(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                stream=stream,
                on_token=on_token,
                temperature=temperature,
                response_format=response_format,
                reasoning_effort=self._reasoning_effort,
            )
        except Exception as exc:
            if not self._is_premature_response_error(exc):
                raise

            retry_effort = self._retry_reasoning_effort(self._reasoning_effort)
            logger.warning(
                "Codex SSE 响应提前结束，自动重试 1 次（reasoning_effort=%s -> %s）",
                self._reasoning_effort or "",
                retry_effort or "",
                exc_info=True,
            )
            completion = self._complete_once(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                stream=stream,
                on_token=on_token,
                temperature=temperature,
                response_format=response_format,
                reasoning_effort=retry_effort,
            )
            metadata = dict(completion.metadata or {})
            metadata["retry_count"] = 1
            metadata["retry_reason"] = "response_ended_prematurely"
            metadata["effective_reasoning_effort"] = retry_effort or ""
            return LLMCompletion(
                content=completion.content,
                tool_calls=completion.tool_calls,
                metadata=metadata,
            )

    def _complete_once(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[ToolSchema]],
        tool_choice: str,
        stream: bool,
        on_token: Optional[OnToken],
        temperature: Optional[float],
        response_format: Optional[Dict[str, Any]],
        reasoning_effort: Optional[str],
    ) -> LLMCompletion:
        instructions, input_items = self._translate_messages(messages, compatibility=True)
        tool_defs = self._translate_tools(tools, compatibility=True)

        body: Dict[str, Any] = {
            "model": self.model,
            "store": self._store,
            "stream": True,
            "input": input_items,
            "text": {"verbosity": self._text_verbosity},
            "include": ["reasoning.encrypted_content"],
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }
        if instructions:
            body["instructions"] = instructions
        if tool_defs:
            body["tools"] = tool_defs
        if temperature is not None:
            body["temperature"] = temperature
        if reasoning_effort:
            body["reasoning"] = {
                "effort": reasoning_effort,
                "summary": "auto",
            }
        if response_format and response_format.get("type") == "json_object":
            body["text"] = {"verbosity": self._text_verbosity}

        headers = self._build_headers()
        url = self._resolve_codex_url(self._codex_base_url)

        raw_chunks: List[str] = []
        event_types: List[str] = []
        final_response: Dict[str, Any] | None = None
        content_parts: List[str] = []
        tool_calls: List[ToolCall] = []

        with self._stream_request(url=url, headers=headers, body=body) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"Codex SSE 请求失败: HTTP {response.status_code} - {response.text}")

            buffer = ""
            for chunk in self._iter_decoded_chunks(response):
                if not chunk:
                    continue
                raw_chunks.append(chunk)
                buffer += chunk
                buffer, final_response = self._consume_sse_buffer(
                    buffer=buffer,
                    event_types=event_types,
                    content_parts=content_parts,
                    tool_calls=tool_calls,
                    on_token=on_token if stream else None,
                    current_final_response=final_response,
                )

            if buffer.strip():
                final_response = self._consume_sse_frame(
                    buffer,
                    event_types=event_types,
                    content_parts=content_parts,
                    tool_calls=tool_calls,
                    on_token=on_token if stream else None,
                    current_final_response=final_response,
                )

        raw_text = "".join(raw_chunks)
        content = "".join(content_parts).strip()
        if not content and final_response is not None:
            content = self._extract_text_from_raw_json(final_response)
        if not content and final_response is None:
            stripped = raw_text.lstrip()
            if stripped and not stripped.startswith("data:") and "\ndata:" not in stripped:
                content = self._extract_text_from_raw_text(raw_text)

        metadata = {
            "transport": "codex_sse",
            "event_types": event_types,
            "raw_text_preview": self._safe_preview(raw_text, limit=1200),
            "raw_json_preview": self._safe_preview(final_response, limit=800),
            "content_preview": self._safe_preview(content, limit=320),
            "response_preview": self._safe_preview(final_response, limit=800),
            "output_preview": "[]",
        }
        if final_response:
            status = str(final_response.get("status", "") or "").strip()
            if status:
                metadata["status"] = status
        if reasoning_effort:
            metadata["effective_reasoning_effort"] = reasoning_effort

        return LLMCompletion(content=content, tool_calls=tool_calls, metadata=metadata)

    def _stream_request(self, *, url: str, headers: Dict[str, str], body: Dict[str, Any]):
        return self._session.post(
            url,
            headers=headers,
            json=body,
            stream=True,
            timeout=self._timeout,
        )

    def _iter_decoded_chunks(self, response: Any) -> Iterator[str]:
        decoder = codecs.getincrementaldecoder("utf-8")()
        for chunk in response.iter_content(chunk_size=None, decode_unicode=False):
            if not chunk:
                continue
            if isinstance(chunk, str):
                yield chunk
                continue
            yield decoder.decode(chunk)

        tail = decoder.decode(b"", final=True)
        if tail:
            yield tail

    def _is_premature_response_error(self, exc: Exception) -> bool:
        pending: List[BaseException] = [exc]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            current_id = id(current)
            if current_id in seen:
                continue
            seen.add(current_id)

            if isinstance(current, requests.exceptions.ChunkedEncodingError):
                return True

            message = str(current).strip().lower()
            if "response ended prematurely" in message:
                return True

            cause = getattr(current, "__cause__", None)
            if isinstance(cause, BaseException):
                pending.append(cause)

            context = getattr(current, "__context__", None)
            if isinstance(context, BaseException):
                pending.append(context)

        return False

    def _retry_reasoning_effort(self, current: Optional[str]) -> Optional[str]:
        normalized = (current or "").strip().lower()
        if not normalized:
            return None
        if normalized in {"low", "medium"}:
            return normalized
        return "medium"

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._codex_api_key}",
            "OpenAI-Beta": "responses=experimental",
            "originator": "pi",
            "User-Agent": f"pi ({platform.system().lower()} {platform.release()}; {platform.machine()})",
            "accept": "text/event-stream",
            "content-type": "application/json",
        }
        account_id = self._extract_account_id(self._codex_api_key)
        if account_id:
            headers["chatgpt-account-id"] = account_id
        return headers

    def _extract_account_id(self, token: str) -> str:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return ""
            payload = parts[1]
            padding = "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
            payload_json = json.loads(decoded)
            account = ((payload_json.get(_JWT_CLAIM_PATH) or {}).get("chatgpt_account_id") or "").strip()
            return account
        except Exception:
            return ""

    def _resolve_codex_url(self, base_url: Optional[str]) -> str:
        raw = (base_url or "https://chatgpt.com/backend-api").rstrip("/")
        if raw.endswith("/codex/responses"):
            return raw
        if raw.endswith("/codex"):
            return f"{raw}/responses"
        return f"{raw}/codex/responses"

    def _consume_sse_buffer(
        self,
        *,
        buffer: str,
        event_types: List[str],
        content_parts: List[str],
        tool_calls: List[ToolCall],
        on_token: Optional[OnToken],
        current_final_response: Dict[str, Any] | None,
    ) -> Tuple[str, Dict[str, Any] | None]:
        final_response = current_final_response
        remaining = buffer
        while "\n\n" in remaining:
            frame, remaining = remaining.split("\n\n", 1)
            final_response = self._consume_sse_frame(
                frame,
                event_types=event_types,
                content_parts=content_parts,
                tool_calls=tool_calls,
                on_token=on_token,
                current_final_response=final_response,
            )
        return remaining, final_response

    def _consume_sse_frame(
        self,
        frame: str,
        *,
        event_types: List[str],
        content_parts: List[str],
        tool_calls: List[ToolCall],
        on_token: Optional[OnToken],
        current_final_response: Dict[str, Any] | None,
    ) -> Dict[str, Any] | None:
        event = self._parse_sse_frame(frame)
        if event is None:
            return current_final_response

        event_type = str(event.get("type", "") or "")
        if event_type:
            event_types.append(event_type)
        self._consume_event(
            event,
            content_parts=content_parts,
            tool_calls=tool_calls,
            on_token=on_token,
        )
        if event_type in {"response.completed", "response.done"}:
            response_payload = event.get("response")
            if isinstance(response_payload, dict):
                return response_payload
        return current_final_response

    def _parse_sse_frame(self, frame: str) -> Dict[str, Any] | None:
        data_lines = []
        for line in frame.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            return None
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return None
        try:
            return json.loads(data)
        except Exception:
            logger.debug("忽略无法解析的 SSE 事件: %s", data)
            return None

    def _consume_event(
        self,
        event: Dict[str, Any],
        *,
        content_parts: List[str],
        tool_calls: List[ToolCall],
        on_token: Optional[OnToken],
    ) -> None:
        event_type = str(event.get("type", "") or "")
        if event_type == "response.output_text.delta":
            delta = str(event.get("delta", "") or "")
            if delta:
                content_parts.append(delta)
                if on_token is not None:
                    on_token(delta)
            return

        if event_type == "response.output_item.done":
            item = event.get("item")
            tool_call = self._tool_call_from_item(item)
            if tool_call is not None:
                tool_calls.append(tool_call)
            return

        if event_type == "error":
            message = str(event.get("message", "") or event.get("code", "") or json.dumps(event, ensure_ascii=False))
            raise RuntimeError(f"Codex SSE 返回错误: {message}")

        if event_type == "response.failed":
            response = event.get("response") or {}
            if isinstance(response, dict):
                error = response.get("error") or {}
                if isinstance(error, dict):
                    message = str(error.get("message", "") or "").strip()
                    if message:
                        raise RuntimeError(message)
            raise RuntimeError("Codex SSE 返回 response.failed")
