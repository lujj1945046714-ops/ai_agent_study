from __future__ import annotations

import json
import os
from dataclasses import dataclass
from json import JSONDecoder
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from agent_framework.llm.codex_responses import CodexResponsesConfig, CodexResponsesModel
from agent_framework.llm.openai_compatible import OpenAICompatibleChatModel, OpenAICompatibleConfig
from agent_framework.llm.openai_responses import OpenAIResponsesConfig, OpenAIResponsesModel
from agent_framework.llm.types import LLMCompletion, Message, OnToken
from job_assistant import config as _config  # noqa: F401

try:  # pragma: no cover - import path depends on Python version
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


DEFAULT_LLM_PROVIDER = "openai_compatible"
DEFAULT_CHAT_WIRE_API = "chat_completions"
DEFAULT_RESPONSES_WIRE_API = "responses"
JSON_REPAIR_SYSTEM_PROMPT = (
    "你是一个 JSON 修复器。"
    "你的任务是输出单个合法 JSON，不能输出解释、markdown 代码块或额外文本。"
)


@dataclass(frozen=True)
class ResolvedLLMConfig:
    provider: str
    api_key: str
    model: str
    base_url: Optional[str]
    wire_api: str
    responses_compat_mode: str
    source: str
    reasoning_effort: Optional[str] = None
    text_verbosity: str = "medium"
    store: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)


def resolve_llm_config(
    *,
    env: Mapping[str, str] | None = None,
    codex_home: Path | None = None,
) -> ResolvedLLMConfig:
    env_map = env or os.environ
    provider = (env_map.get("JOB_ASSISTANT_LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()

    if provider == "codex":
        return _resolve_codex_config(env_map=env_map, codex_home=codex_home)

    if provider in {"openai_compatible", "deepseek", "openai"}:
        return _resolve_openai_compatible_config(env_map)

    raise RuntimeError(f"不支持的 LLM provider: {provider}")


def ensure_llm_configured(
    *,
    env: Mapping[str, str] | None = None,
    codex_home: Path | None = None,
) -> ResolvedLLMConfig:
    resolved = resolve_llm_config(env=env, codex_home=codex_home)
    if resolved.api_key and resolved.model:
        return resolved

    if resolved.provider == "codex":
        raise RuntimeError(
            "Codex 模式已启用，但未从 `~/.codex/auth.json` / `~/.codex/config.toml` 读取到完整配置。"
        )

    raise RuntimeError(
        "未配置 LLM。请设置 `DEEPSEEK_API_KEY`（兼容旧配置）或使用 `JOB_ASSISTANT_LLM_PROVIDER=codex`。"
    )


def has_llm_configured(
    *,
    env: Mapping[str, str] | None = None,
    codex_home: Path | None = None,
) -> bool:
    try:
        return ensure_llm_configured(env=env, codex_home=codex_home).is_configured
    except RuntimeError:
        return False


def create_chat_model(resolved: ResolvedLLMConfig | None = None):
    llm_config = resolved or ensure_llm_configured()
    wire_api = _normalize_wire_api(llm_config.wire_api)

    if wire_api == DEFAULT_RESPONSES_WIRE_API:
        if llm_config.provider == "codex":
            return CodexResponsesModel(
                CodexResponsesConfig(
                    api_key=llm_config.api_key,
                    model=llm_config.model,
                    base_url=llm_config.base_url,
                    reasoning_effort=llm_config.reasoning_effort,
                    text_verbosity=llm_config.text_verbosity,
                    store=llm_config.store,
                )
            )
        return OpenAIResponsesModel(
            OpenAIResponsesConfig(
                api_key=llm_config.api_key,
                model=llm_config.model,
                base_url=llm_config.base_url,
                compat_mode=llm_config.responses_compat_mode,
            )
        )

    return OpenAICompatibleChatModel(
        OpenAICompatibleConfig(
            api_key=llm_config.api_key,
            model=llm_config.model,
            base_url=llm_config.base_url,
        )
    )


def complete_messages(
    messages: List[Message],
    *,
    llm=None,
    stream: bool = False,
    on_token: Optional[OnToken] = None,
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> LLMCompletion:
    model = llm or create_chat_model()
    return model.complete(
        messages=messages,
        stream=stream,
        on_token=on_token,
        temperature=temperature,
        response_format=response_format,
    )


def complete_text(
    messages: List[Message],
    *,
    llm=None,
    stream: bool = False,
    on_token: Optional[OnToken] = None,
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    return (
        complete_messages(
            messages,
            llm=llm,
            stream=stream,
            on_token=on_token,
            temperature=temperature,
            response_format=response_format,
        ).content
        or ""
    )


def _complete_text_with_debug(
    messages: List[Message],
    *,
    llm=None,
    stream: bool = False,
    on_token: Optional[OnToken] = None,
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> tuple[str, Dict[str, Any]]:
    completion = complete_messages(
        messages,
        llm=llm,
        stream=stream,
        on_token=on_token,
        temperature=temperature,
        response_format=response_format,
    )
    return (completion.content or "", dict(completion.metadata or {}))


def complete_json(
    messages: List[Message],
    *,
    llm=None,
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Any:
    model = llm or create_chat_model()
    raw, raw_metadata = _complete_text_with_debug(
        messages,
        llm=model,
        temperature=temperature,
        response_format=response_format or {"type": "json_object"},
    )
    try:
        return parse_json_response(raw)
    except json.JSONDecodeError:
        retry_raw, retry_metadata = _retry_json_generation(
            messages=messages,
            raw=raw,
            llm=model,
            temperature=temperature,
        )
        try:
            return parse_json_response(retry_raw)
        except json.JSONDecodeError as exc:
            raise _json_error_with_debug(raw=retry_raw or raw, metadata=retry_metadata or raw_metadata) from exc


def complete_json_flexible(
    messages: List[Message],
    *,
    llm=None,
    temperature: Optional[float] = None,
) -> Any:
    model = llm or create_chat_model()
    raw, raw_metadata = _complete_text_with_debug(
        messages,
        llm=model,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    try:
        return parse_json_response(raw)
    except json.JSONDecodeError:
        retry_raw, retry_metadata = _retry_json_generation(
            messages=messages,
            raw=raw,
            llm=model,
            temperature=temperature,
        )
        try:
            return parse_json_response(retry_raw)
        except json.JSONDecodeError as exc:
            raise _json_error_with_debug(raw=retry_raw or raw, metadata=retry_metadata or raw_metadata) from exc


def parse_json_response(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        segments = text.split("```")
        if len(segments) >= 2:
            text = segments[1].removeprefix("json").strip()

    decoder = JSONDecoder()
    try:
        return decoder.decode(text)
    except json.JSONDecodeError:
        pass

    for char in ("{", "["):
        start = text.find(char)
        if start < 0:
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
            return value
        except json.JSONDecodeError:
            continue

    raise json.JSONDecodeError("无法解析 JSON 响应", text, 0)


def _retry_json_generation(
    *,
    messages: List[Message],
    raw: str,
    llm,
    temperature: Optional[float],
) -> tuple[str, Dict[str, Any]]:
    stripped = (raw or "").strip()
    if stripped:
        return _complete_text_with_debug(
            [
                {"role": "system", "content": JSON_REPAIR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"请把下面内容修复为合法 JSON，只返回 JSON：\n\n{stripped}",
                },
            ],
            llm=llm,
            temperature=0,
        )

    retry_messages = list(messages)
    retry_messages.append(
        {
            "role": "user",
            "content": "请严格只返回单个合法 JSON，不要解释，不要 markdown 代码块。",
        }
    )
    return _complete_text_with_debug(
        retry_messages,
        llm=llm,
        temperature=temperature if temperature is not None else 0,
    )


def _json_error_with_debug(*, raw: str, metadata: Dict[str, Any]) -> json.JSONDecodeError:
    text = (raw or "").strip()
    if text:
        return json.JSONDecodeError("无法解析 JSON 响应", text, 0)

    parts = []
    status = str(metadata.get("status", "") or "").strip()
    if status:
        parts.append(f"status={status}")

    output_item_types = metadata.get("output_item_types") or []
    if output_item_types:
        parts.append(f"output_item_types={output_item_types}")

    output_parsed_preview = str(metadata.get("output_parsed_preview", "") or "").strip()
    if output_parsed_preview:
        parts.append(f"output_parsed_preview={output_parsed_preview}")

    content_preview = str(metadata.get("content_preview", "") or "").strip()
    if content_preview:
        parts.append(f"content_preview={content_preview}")

    output_preview = str(metadata.get("output_preview", "") or "").strip()
    if output_preview:
        parts.append(f"output_preview={output_preview}")

    raw_json_preview = str(metadata.get("raw_json_preview", "") or "").strip()
    if raw_json_preview:
        parts.append(f"raw_json_preview={raw_json_preview}")

    raw_text_preview = str(metadata.get("raw_text_preview", "") or "").strip()
    if raw_text_preview:
        parts.append(f"raw_text_preview={raw_text_preview}")

    incomplete_details = str(metadata.get("incomplete_details", "") or "").strip()
    if incomplete_details:
        parts.append(f"incomplete_details={incomplete_details}")

    error = str(metadata.get("error", "") or "").strip()
    if error:
        parts.append(f"error={error}")

    response_preview = str(metadata.get("response_preview", "") or "").strip()
    if response_preview:
        parts.append(f"response_preview={response_preview}")

    return json.JSONDecodeError("无法解析 JSON 响应", "; ".join(parts), 0)


def _resolve_openai_compatible_config(env_map: Mapping[str, str]) -> ResolvedLLMConfig:
    api_key = (env_map.get("JOB_ASSISTANT_LLM_API_KEY") or env_map.get("DEEPSEEK_API_KEY") or "").strip()
    base_url = (
        env_map.get("JOB_ASSISTANT_LLM_BASE_URL")
        or env_map.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    ).strip()
    model = (env_map.get("JOB_ASSISTANT_LLM_MODEL") or env_map.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
    wire_api = (
        env_map.get("JOB_ASSISTANT_LLM_WIRE_API")
        or env_map.get("DEEPSEEK_WIRE_API")
        or DEFAULT_CHAT_WIRE_API
    ).strip()

    return ResolvedLLMConfig(
        provider="openai_compatible",
        api_key=api_key,
        model=model,
        base_url=base_url or None,
        wire_api=wire_api or DEFAULT_CHAT_WIRE_API,
        responses_compat_mode=_normalize_responses_compat_mode(
            env_map.get("JOB_ASSISTANT_RESPONSES_COMPAT_MODE") or "off"
        ),
        source="environment",
        text_verbosity=_normalize_text_verbosity(env_map.get("JOB_ASSISTANT_LLM_TEXT_VERBOSITY") or "medium"),
        store=_coerce_optional_bool(env_map.get("JOB_ASSISTANT_LLM_STORE")) or False,
    )


def _resolve_codex_config(
    *,
    env_map: Mapping[str, str],
    codex_home: Path | None,
) -> ResolvedLLMConfig:
    home = (codex_home or Path(env_map.get("CODEX_HOME", "~/.codex"))).expanduser()
    auth_path = home / "auth.json"
    config_path = home / "config.toml"

    auth_data = _load_json_file(auth_path)
    codex_config = _load_toml_file(config_path)

    provider_name = (
        env_map.get("JOB_ASSISTANT_CODEX_MODEL_PROVIDER")
        or codex_config.get("model_provider")
        or ""
    ).strip()
    provider_section = {}
    if provider_name:
        provider_section = ((codex_config.get("model_providers") or {}).get(provider_name) or {})

    api_key = (
        env_map.get("JOB_ASSISTANT_LLM_API_KEY")
        or provider_section.get("experimental_bearer_token")
        or auth_data.get("OPENAI_API_KEY")
        or auth_data.get("api_key")
        or ""
    ).strip()
    base_url = (
        env_map.get("JOB_ASSISTANT_LLM_BASE_URL")
        or provider_section.get("base_url")
        or ""
    ).strip()
    model = (
        env_map.get("JOB_ASSISTANT_LLM_MODEL")
        or codex_config.get("model")
        or ""
    ).strip()
    wire_api = (
        env_map.get("JOB_ASSISTANT_LLM_WIRE_API")
        or provider_section.get("wire_api")
        or DEFAULT_RESPONSES_WIRE_API
    ).strip()
    reasoning_effort = (
        env_map.get("JOB_ASSISTANT_LLM_REASONING_EFFORT")
        or str(codex_config.get("model_reasoning_effort") or "")
    ).strip()
    disable_response_storage = _coerce_optional_bool(
        env_map.get("JOB_ASSISTANT_DISABLE_RESPONSE_STORAGE")
    )
    if disable_response_storage is None:
        disable_response_storage = _coerce_optional_bool(codex_config.get("disable_response_storage"))
    store = _coerce_optional_bool(env_map.get("JOB_ASSISTANT_LLM_STORE"))
    if store is None:
        store = False if disable_response_storage is None else not disable_response_storage

    return ResolvedLLMConfig(
        provider="codex",
        api_key=api_key,
        model=model,
        base_url=base_url or None,
        wire_api=wire_api or DEFAULT_RESPONSES_WIRE_API,
        responses_compat_mode=_normalize_responses_compat_mode(
            env_map.get("JOB_ASSISTANT_RESPONSES_COMPAT_MODE") or "auto"
        ),
        source=str(home),
        reasoning_effort=reasoning_effort or None,
        text_verbosity=_normalize_text_verbosity(env_map.get("JOB_ASSISTANT_LLM_TEXT_VERBOSITY") or "medium"),
        store=bool(store),
    )


def _load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_toml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _normalize_wire_api(wire_api: str) -> str:
    normalized = (wire_api or DEFAULT_CHAT_WIRE_API).strip().lower()
    aliases = {
        "chat": DEFAULT_CHAT_WIRE_API,
        "chat_completions": DEFAULT_CHAT_WIRE_API,
        "responses": DEFAULT_RESPONSES_WIRE_API,
    }
    if normalized not in aliases:
        raise RuntimeError(f"不支持的 wire_api: {wire_api}")
    return aliases[normalized]


def _normalize_responses_compat_mode(compat_mode: str) -> str:
    normalized = (compat_mode or "off").strip().lower()
    if normalized not in {"off", "auto"}:
        raise RuntimeError(f"不支持的 JOB_ASSISTANT_RESPONSES_COMPAT_MODE: {compat_mode}")
    return normalized


def _normalize_text_verbosity(verbosity: str) -> str:
    normalized = (verbosity or "medium").strip().lower()
    if normalized not in {"low", "medium", "high"}:
        raise RuntimeError(f"不支持的 JOB_ASSISTANT_LLM_TEXT_VERBOSITY: {verbosity}")
    return normalized


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"无法解析布尔配置值: {value}")
