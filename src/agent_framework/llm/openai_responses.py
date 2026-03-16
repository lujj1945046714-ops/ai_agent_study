from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agent_framework.llm.types import LLMCompletion, Message, OnToken, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    api_key: str
    model: str
    base_url: Optional[str] = None
    compat_mode: str = "off"


class OpenAIResponsesModel:
    """
    Adapter for OpenAI-compatible Responses APIs.

    Works with providers exposing `/responses` semantics, including Codex-style
    providers configured with `wire_api=responses`.
    """

    def __init__(self, config: OpenAIResponsesConfig):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime dependent
            raise RuntimeError("Missing dependency: openai") from exc

        self._model = config.model
        self._compat_mode = self._normalize_compat_mode(config.compat_mode)
        self._client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    @property
    def model(self) -> str:
        return self._model

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
        if stream:
            try:
                request_kwargs = self._build_request_kwargs(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    response_format=response_format,
                )
                return self._complete_streaming(request_kwargs=request_kwargs, on_token=on_token)
            except Exception as exc:
                if not self._should_fallback_to_non_stream(exc):
                    raise
                logger.warning("Responses streaming failed; retrying with non-stream compatibility fallback", exc_info=True)

        request_kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            response_format=response_format,
        )
        return self._complete_non_streaming(request_kwargs=request_kwargs)

    def _complete_non_streaming(self, *, request_kwargs: Dict[str, Any]) -> LLMCompletion:
        try:
            response, raw_json, raw_text = self._create_non_streaming_response(request_kwargs=request_kwargs)
            return self._build_completion(response, raw_json=raw_json, raw_text=raw_text)
        except Exception as exc:
            retry_kwargs = self._build_retry_request_kwargs(request_kwargs=request_kwargs, exc=exc)
            if retry_kwargs is None:
                raise
            logger.warning("Responses request failed; retrying with reduced compatibility payload", exc_info=True)
            response, raw_json, raw_text = self._create_non_streaming_response(request_kwargs=retry_kwargs)
            return self._build_completion(response, raw_json=raw_json, raw_text=raw_text)

    def _create_non_streaming_response(self, *, request_kwargs: Dict[str, Any]) -> Tuple[Any, Any, str]:
        raw_client = getattr(self._client.responses, "with_raw_response", None)
        if raw_client is None:
            return self._client.responses.create(**request_kwargs), None, ""

        raw_response = raw_client.create(**request_kwargs)
        raw_json = None
        raw_text = ""
        try:
            raw_text = raw_response.text()
        except Exception:
            raw_text = ""
        try:
            raw_json = raw_response.json()
        except Exception:
            raw_json = None
        return raw_response.parse(), raw_json, raw_text

    def _build_request_kwargs(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[ToolSchema]],
        tool_choice: str,
        temperature: Optional[float],
        response_format: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        compatibility = self._compat_mode != "off"
        instructions, input_items = self._translate_messages(messages, compatibility=compatibility)
        tool_defs = self._translate_tools(tools, compatibility=compatibility)
        text_config = self._translate_response_format(response_format, compatibility=compatibility)

        request_kwargs: Dict[str, Any] = {
            "model": self._model,
            "input": input_items,
        }
        if instructions:
            request_kwargs["instructions"] = instructions
        if tool_defs:
            request_kwargs["tools"] = tool_defs
            if tool_choice != "auto" or not compatibility:
                request_kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if text_config is not None:
            request_kwargs["text"] = text_config
        return request_kwargs

    def _complete_streaming(
        self,
        *,
        request_kwargs: Dict[str, Any],
        on_token: Optional[OnToken],
    ) -> LLMCompletion:
        full_content = ""
        streamed_tool_calls: List[ToolCall] = []

        with self._client.responses.stream(**request_kwargs) as stream:
            for event in stream:
                event_type = getattr(event, "type", "")

                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or ""
                    if delta:
                        full_content += delta
                        if on_token is not None:
                            try:
                                on_token(delta)
                            except Exception:  # pragma: no cover - callback dependent
                                logger.warning("on_token callback failed", exc_info=True)
                    continue

                if event_type == "response.output_item.done":
                    item = getattr(event, "item", None)
                    tool_call = self._tool_call_from_item(item)
                    if tool_call is not None:
                        streamed_tool_calls.append(tool_call)

            response = stream.get_final_response()

        completion = self._build_completion(response)
        content = full_content or completion.content
        tool_calls = streamed_tool_calls or completion.tool_calls
        return LLMCompletion(content=content, tool_calls=tool_calls, metadata=completion.metadata)

    def _build_completion(self, response: Any, *, raw_json: Any = None, raw_text: str = "") -> LLMCompletion:
        content = getattr(response, "output_text", "") or ""
        tool_calls: List[ToolCall] = []
        output_items = getattr(response, "output", []) or []

        if not content:
            output_parsed = self._get_value(response, "output_parsed", None)
            content = self._stringify_json_like(output_parsed)
        if not content:
            content = self._extract_text_from_output(output_items)
        if not content and raw_json is not None:
            content = self._extract_text_from_raw_json(raw_json)
        if not content and raw_text:
            content = self._extract_text_from_raw_text(raw_text)

        for item in output_items:
            tool_call = self._tool_call_from_item(item)
            if tool_call is not None:
                tool_calls.append(tool_call)

        return LLMCompletion(
            content=content,
            tool_calls=tool_calls,
            metadata=self._build_response_metadata(response, output_items, raw_json=raw_json, raw_text=raw_text),
        )

    def _translate_messages(
        self,
        messages: List[Message],
        *,
        compatibility: bool,
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        instructions_parts: List[str] = []
        input_items: List[Dict[str, Any]] = []

        for index, message in enumerate(messages):
            role = message.get("role", "")
            content = self._stringify_content(message.get("content"))

            if role == "system":
                if content:
                    instructions_parts.append(content)
                continue

            if role in {"user", "assistant"}:
                if content:
                    item: Dict[str, Any] = {"type": "message", "role": role, "content": content}
                    if role == "assistant" and not compatibility:
                        item["phase"] = "commentary"
                    input_items.append(item)

                for tool_call in message.get("tool_calls") or []:
                    function = tool_call.get("function", {}) or {}
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": tool_call.get("id") or f"call_{index}",
                            "name": function.get("name", ""),
                            "arguments": function.get("arguments", "") or "{}",
                        }
                    )
                continue

            if role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id", ""),
                        "output": content,
                    }
                )

        instructions = "\n\n".join(part for part in instructions_parts if part).strip()
        return instructions or None, input_items

    def _translate_tools(
        self,
        tools: Optional[List[ToolSchema]],
        *,
        compatibility: bool,
    ) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None

        translated: List[Dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function", {}) if tool.get("type") == "function" else {}
            item = {
                "type": "function",
                "name": function.get("name", ""),
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {}),
            }
            if not compatibility:
                item["strict"] = True
            translated.append(item)
        return translated

    def _translate_response_format(
        self,
        response_format: Optional[Dict[str, Any]],
        *,
        compatibility: bool,
    ) -> Optional[Dict[str, Any]]:
        if not response_format:
            return None
        return {"format": response_format}

    def _build_retry_request_kwargs(
        self,
        *,
        request_kwargs: Dict[str, Any],
        exc: Exception,
    ) -> Optional[Dict[str, Any]]:
        if not self._is_retryable_compat_error(exc):
            return None

        retry_kwargs = dict(request_kwargs)
        changed = False

        if "text" in retry_kwargs:
            retry_kwargs.pop("text", None)
            changed = True

        if retry_kwargs.get("tool_choice") == "auto":
            retry_kwargs.pop("tool_choice", None)
            changed = True

        return retry_kwargs if changed else None

    def _should_fallback_to_non_stream(self, exc: Exception) -> bool:
        return self._compat_mode == "auto" and self._is_retryable_compat_error(exc)

    def _is_retryable_compat_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)

        body = ""
        if response is not None:
            try:
                json_body = response.json()
                body = json.dumps(json_body, ensure_ascii=False)
            except Exception:
                body = str(response)
        else:
            body = str(exc)

        body_lower = body.lower()
        if status_code in {500, 502, 503, 504} or "upstream" in body_lower:
            return True
        if status_code == 400 and any(marker in body_lower for marker in ("text", "format", "tool_choice")):
            if any(marker in body_lower for marker in ("unsupported", "unknown", "invalid", "extra", "unexpected")):
                return True
        return False

    def _normalize_compat_mode(self, compat_mode: str) -> str:
        normalized = (compat_mode or "off").strip().lower()
        if normalized not in {"off", "auto"}:
            raise RuntimeError(f"Unsupported Responses compatibility mode: {compat_mode}")
        return normalized

    def _tool_call_from_item(self, item: Any) -> ToolCall | None:
        item_type = self._get_value(item, "type")
        if item_type != "function_call":
            return None
        return ToolCall(
            id=self._get_value(item, "call_id") or self._get_value(item, "id"),
            name=self._get_value(item, "name"),
            arguments=self._get_value(item, "arguments") or "{}",
        )

    def _stringify_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
                        continue
                parts.append(json.dumps(item, ensure_ascii=False))
            return "\n".join(part for part in parts if part)
        return str(content)

    def _extract_text_from_output(self, output_items: List[Any]) -> str:
        parts: List[str] = []
        for item in output_items:
            parts.extend(self._extract_text_segments(item))
        return "".join(parts).strip()

    def _extract_text_segments(self, value: Any) -> List[str]:
        if value is None:
            return []
        normalized = self._normalize_value(value)
        if normalized is not value:
            return self._extract_text_segments(normalized)
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            parts: List[str] = []
            for item in value:
                parts.extend(self._extract_text_segments(item))
            return parts
        if isinstance(value, dict):
            for key in ("text", "value", "output_text"):
                direct_text = value.get(key)
                if isinstance(direct_text, str) and direct_text:
                    return [direct_text]
            parts: List[str] = []
            for key in ("content", "contents", "parts", "items", "data", "result", "choices", "message", "messages", "output", "response", "answer"):
                nested = value.get(key)
                if nested is not None:
                    parts.extend(self._extract_text_segments(nested))
            return parts
        for key in ("text", "value", "output_text"):
            direct_text = getattr(value, key, None)
            if isinstance(direct_text, str) and direct_text:
                return [direct_text]
        parts: List[str] = []
        for key in ("content", "contents", "parts", "items", "data", "result", "choices", "message", "messages", "output", "response", "answer"):
            nested = getattr(value, key, None)
            if nested is not None:
                parts.extend(self._extract_text_segments(nested))
        return parts

    def _get_value(self, item: Any, key: str, default: str = "") -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _build_response_metadata(self, response: Any, output_items: List[Any], *, raw_json: Any = None, raw_text: str = "") -> Dict[str, Any]:
        output_parsed = self._get_value(response, "output_parsed", None)
        return {
            "transport": "responses",
            "status": self._get_value(response, "status"),
            "output_item_types": [self._get_value(item, "type") for item in output_items if self._get_value(item, "type")],
            "output_parsed_preview": self._safe_preview(output_parsed, limit=320),
            "content_preview": self._safe_preview(self._extract_text_from_output(output_items), limit=320),
            "output_preview": self._safe_preview(self._normalize_value(output_items), limit=500),
            "raw_json_preview": self._safe_preview(raw_json, limit=600),
            "raw_text_preview": self._safe_preview(raw_text, limit=600),
            "incomplete_details": self._safe_preview(self._get_value(response, "incomplete_details", None), limit=240),
            "error": self._safe_preview(self._get_value(response, "error", None), limit=240),
            "response_preview": self._safe_preview(response, limit=500),
        }

    def _safe_preview(self, value: Any, *, limit: int) -> str:
        if value is None:
            return ""
        try:
            normalized = self._normalize_value(value)
            if isinstance(normalized, (dict, list)):
                rendered = json.dumps(normalized, ensure_ascii=False)
            elif normalized is not value:
                rendered = str(normalized)
            else:
                rendered = str(value)
        except Exception:
            rendered = str(value)
        rendered = rendered.strip()
        if len(rendered) > limit:
            return f"{rendered[:limit]}..."
        return rendered

    def _normalize_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool, dict, list)):
            return value
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump(mode="json")
            except Exception:
                pass
        if hasattr(value, "dict"):
            try:
                return value.dict()
            except Exception:
                pass
        return value

    def _stringify_json_like(self, value: Any) -> str:
        normalized = self._normalize_value(value)
        if normalized is None:
            return ""
        if isinstance(normalized, (dict, list)):
            return json.dumps(normalized, ensure_ascii=False)
        if isinstance(normalized, str):
            return normalized
        return ""

    def _extract_text_from_raw_json(self, raw_json: Any) -> str:
        normalized = self._normalize_value(raw_json)
        if normalized is None:
            return ""
        return "".join(self._extract_text_segments(normalized)).strip()

    def _extract_text_from_raw_text(self, raw_text: str) -> str:
        text = (raw_text or "").strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        return self._extract_text_from_raw_json(parsed)
