# Codex API 集成实践

这份文档总结了把 Codex CLI 正在使用的模型配置复用到业务 Agent 项目里的关键经验，目标是：

- 复用本机 `~/.codex` 配置，而不是把 key 硬编码进项目
- 区分“OpenAI 兼容 SDK”与“Codex CLI 专用传输”
- 在别的项目里快速排查 `401 / 400 / 502 / output=[]` 这类问题

---

## 1. 先判断你接的是哪一类 provider

不要先假设“能用 OpenAI SDK 就一定能用 Codex”。

实际常见有两类：

1. **OpenAI-Compatible**
   - 直接兼容 `chat.completions` 或标准 `responses`
   - 用官方 SDK 往往就能通
2. **Codex CLI 风格 provider**
   - Codex CLI 能跑
   - 但 SDK 非流式 `responses.create()` 不一定能拿到正文
   - 往往要求走 `POST /codex/responses` + `text/event-stream`

这次项目的问题就属于第二类。

典型现象：

- 请求返回 `status=completed`
- 但 `output=[]`
- 或 `output_text=""`
- 业务层最终报“LLM 未返回合法 JSON”

这通常不是提示词问题，而是**传输协议不匹配**。

---

## 2. 配置优先级怎么设计

建议统一做成一个 `ResolvedLLMConfig`，按下面顺序取值：

1. 项目 `.env`
2. `~/.codex/config.toml`
3. `~/.codex/auth.json`
4. provider 子配置兜底

对 Codex provider，至少解析这些字段：

- `model_provider`
- `model`
- `base_url`
- `wire_api`
- `experimental_bearer_token`
- `model_reasoning_effort`
- `disable_response_storage`

这次项目里的做法：

- `JOB_ASSISTANT_LLM_PROVIDER=codex`
- 如果 `wire_api=responses`，走专门的 `CodexResponsesModel`
- `api_key` 优先级：
  - `JOB_ASSISTANT_LLM_API_KEY`
  - `model_providers.<name>.experimental_bearer_token`
  - `auth.json` 里的 key

这样可以直接复用 Codex CLI 正在工作的账号和网关配置。

---

## 3. 为什么普通 SDK 会失败

问题不一定出在认证。

常见根因有四种：

1. **路径不对**
   - provider 实际需要 `/codex/responses`
   - 但项目发到了普通 `/responses`
2. **流式要求**
   - provider 只在 `stream=true` + SSE 下返回完整正文
3. **请求体形状不同**
   - 某些 provider 只接受 CLI 风格字段
4. **头部要求不同**
   - 比如需要 `OpenAI-Beta: responses=experimental`
   - 或 `originator: pi`

所以“Codex CLI 正常”并不能证明“SDK 路径正常”。

---

## 4. 推荐请求形状

如果你接的是 Codex CLI 风格 provider，推荐直接按下面的协议发：

### 请求头

```text
Authorization: Bearer <token>
OpenAI-Beta: responses=experimental
originator: pi
accept: text/event-stream
content-type: application/json
```

如果 token 是可解析 JWT，还可以补：

```text
chatgpt-account-id: <account_id>
```

### 请求体

```json
{
  "model": "gpt-5.4",
  "store": false,
  "stream": true,
  "input": [...],
  "instructions": "...",
  "text": { "verbosity": "medium" },
  "include": ["reasoning.encrypted_content"],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "reasoning": {
    "effort": "xhigh",
    "summary": "auto"
  }
}
```

关键点：

- `stream=true` 基本是重点
- `store=false` 可与 `disable_response_storage=true` 对齐
- `text.verbosity`、`reasoning.effort` 直接从 Codex 配置映射

---

## 5. 程序结构怎么拆

不要把所有 provider 全塞进一个适配器。

推荐最小结构：

1. `resolve_llm_config()`
   - 只负责统一解析配置
2. `create_chat_model()`
   - 按 `provider + wire_api` 分流
3. `OpenAICompatibleChatModel`
   - 处理标准兼容模型
4. `OpenAIResponsesModel`
   - 处理标准 `responses`
5. `CodexResponsesModel`
   - 专门处理 `/codex/responses` + SSE

这样做的好处：

- 排错边界清晰
- 不会为了兼容一个网关污染所有 provider
- 方便单测覆盖不同传输层

---

## 6. SSE 解析时要抓什么

至少处理三类事件：

1. `response.output_text.delta`
   - 逐 token 拼接正文
2. `response.output_item.done`
   - 收集 tool call
3. `response.completed` / `response.done`
   - 提取最终 response payload

正文提取建议按这个优先级：

1. delta 拼出来的文本
2. `response.completed.response`
3. 原始响应文本

不要只依赖 `output_text`，因为很多兼容网关根本不会按官方 SDK 期望的形状返回。

---

## 7. JSON 输出为什么容易挂

结构化输出最常见的坑不是模型不会写 JSON，而是**你根本没拿到正文**。

建议这样排查：

1. 看是否 `status=completed`
2. 看 `output` 是否为空
3. 看 SSE 事件里有没有 `response.output_text.delta`
4. 记录：
   - `event_types`
   - `raw_text_preview`
   - `raw_json_preview`
   - `response_preview`

如果日志里出现：

- `status=completed`
- `output=[]`
- `raw_text_preview` 还是一串 SSE 原文

那基本就能确认是**适配器没正确消费流**。

---

## 8. 速度慢时先调什么

如果“能用但有点慢”，优先调下面三项：

1. **降低 reasoning**
   - `xhigh -> high / medium`
2. **降低 verbosity**
   - `medium -> low`
3. **减少大模型参与次数**
   - 先本地粗筛，再让模型精排

建议经验：

- 画像提取：`reasoning=medium/high`
- 批量打分：尽量不要每个候选都走高推理
- JSON 修复：只在解析失败时重试一次，不要无限 retry

---

## 9. 推荐保留的调试信息

无论你在哪个项目里接 Codex，都建议在 completion metadata 里保留：

- `transport`
- `status`
- `event_types`
- `output_item_types`
- `content_preview`
- `raw_text_preview`
- `raw_json_preview`
- `response_preview`

这样遇到问题时可以快速区分：

- 是认证问题
- 是网关协议问题
- 是 SDK 解析问题
- 还是模型内容问题

---

## 10. 一个可复用的排查清单

当别的项目接 Codex 失败时，按这个顺序看：

1. `~/.codex/config.toml` 里的 `wire_api` 是什么
2. `base_url` 末尾是否需要补 `/codex/responses`
3. 项目是否真的用了 `stream=true`
4. 是否带了 `OpenAI-Beta: responses=experimental`
5. 是否把 `experimental_bearer_token` 用上了
6. 返回里有没有 `response.output_text.delta`
7. `status=completed` 时 `output` 是否为空
8. 是否错误地把空响应当成“提示词不对”

---

## 11. 在这个仓库里的对应实现

- Codex SSE 适配器：`src/agent_framework/llm/codex_responses.py`
- LLM 配置解析与模型路由：`src/job_assistant/llm_runtime.py`
- 回归测试：
  - `tests/core/llm/test_codex_responses.py`
  - `tests/job_assistant/test_llm_runtime.py`

如果你要把这套方案复制到别的项目，优先迁移这三块。
