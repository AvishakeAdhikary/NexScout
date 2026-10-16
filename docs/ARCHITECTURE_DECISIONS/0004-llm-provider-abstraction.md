# ADR-0004: Own LLM provider abstraction with capability metadata

- **Status:** Accepted
- **Date:** 2026-10-16

## Context
We must support OpenAI, Anthropic, Gemini, Ollama, LM Studio and other OpenAI-compatible endpoints (§11),
including 7–9B local models with weak or missing structured output and tool calling. Provider
credentials must stay out of agent context and logs (BYOK).

## Decision
A small `LLMProvider` protocol in `infrastructure/llm/base.py`:
`async complete(request: CompletionRequest) -> CompletionResult`. The request carries messages, an
optional JSON schema, max tokens, temperature, a timeout and a cancel scope. The result carries text,
parsed JSON, a usage object (input/output tokens), latency, model and a finish reason.
Each configured model has a `ModelCapabilities` record: context window, max output,
`json_schema`, `json_mode`, `tools`, `streaming`, a tokenizer hint, and pricing (optional).

Adapters:
- `openai_compat`: plain httpx against `/v1/chat/completions`. Covers OpenAI, Ollama (`/v1`),
  LM Studio, vLLM and llama.cpp server. Uses `response_format` json_schema when the capability is
  set, otherwise json_object or prompt-only.
- `anthropic`: official SDK.
- `gemini`: official `google-genai` SDK.
- `mock`: deterministic, schema-aware fixtures. Results are labelled `provider="mock"` and surfaced
  in the UI.

`structured()` helper: request → parse → Pydantic validate → on failure one repair attempt with
the validation error → then a reduced-context retry → then a typed failure. Never accept
unvalidated output.

LangChain chat-model wrappers are **not** used on the core path. Our needs are narrow, and owning the
abstraction keeps capability reporting honest. LangGraph is still used for orchestration.

## Consequences
- Each adapter has a contract test against a recorded fixture, plus an opt-in live test (`-m live`).
- A provider counts as "supported" only once its live test has passed and been recorded in
  `docs/KNOWN_LIMITATIONS.md` → provider capability matrix.
