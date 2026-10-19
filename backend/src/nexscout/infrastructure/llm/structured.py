"""Structured output for any provider: native schema when supported, otherwise instructions;
always parsed and validated with Pydantic, with one repair attempt (ADR-0004).

Unvalidated model output is never returned.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from nexscout.infrastructure.llm.base import (
    TRUNCATED,
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    OutputInvalid,
    OutputTruncated,
)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass
class StructuredResult[T: BaseModel]:
    value: T
    calls: list[CompletionResult]


def output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for an LLM output model. Output models must declare every field required
    (use `X | None` for optional values) and forbid extra keys, as strict modes require."""
    return model.model_json_schema()


def extract_json(text: str) -> Any:
    """Parse JSON from model text, tolerating code fences and leading/trailing prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        return json.loads(cleaned[start : end + 1])


def _instructions(schema: dict[str, Any]) -> str:
    return (
        "Respond with a single JSON object only, no prose and no code fences. It must "
        "validate against this JSON Schema:\n" + json.dumps(schema, separators=(",", ":"))
    )


async def structured[T: BaseModel](
    provider: LLMProvider, request: CompletionRequest, output: type[T]
) -> StructuredResult[T]:
    schema = output_schema(output)
    req = replace(
        request,
        json_schema=schema if provider.capabilities.json_schema else None,
        schema_name=output.__name__,
    )
    if not provider.capabilities.json_schema:
        req = replace(req, system=((req.system or "") + "\n\n" + _instructions(schema)).strip())
    calls: list[CompletionResult] = []
    result = await provider.complete(req)
    calls.append(result)
    error = _validate(result.text, output)
    if isinstance(error, BaseModel):
        return StructuredResult(error, calls)
    if result.finish_reason in TRUNCATED:
        raise _truncated(req, calls)  # a repair would be cut off the same way

    # One repair attempt: show the model its output and the validation errors.
    repair = replace(
        req,
        messages=[
            *req.messages,
            Message("assistant", result.text[:8000]),
            Message(
                "user",
                "That response was not valid. Problems: "
                + error[:2000]
                + "\nReturn only the corrected JSON object.",
            ),
        ],
    )
    result = await provider.complete(repair)
    calls.append(result)
    second = _validate(result.text, output)
    if isinstance(second, BaseModel):
        return StructuredResult(second, calls)
    if result.finish_reason in TRUNCATED:
        raise _truncated(req, calls)
    raise OutputInvalid(
        f"The model's answer didn't have the expected structure ({second[:300]}).", calls
    )


def _truncated(req: CompletionRequest, calls: list[CompletionResult]) -> OutputTruncated:
    return OutputTruncated(
        f"The model ran out of room for its answer (its limit is {req.max_tokens} tokens; "
        'models that think first use part of it). Raise "Longest answer" for this model in '
        "Settings → AI models → Edit (for example to 8192), or choose another model.",
        calls,
    )


def _validate[T: BaseModel](text: str, output: type[T]) -> T | str:
    try:
        return output.model_validate(extract_json(text))
    except json.JSONDecodeError as exc:
        return f"not valid JSON ({exc.msg})"
    except ValidationError as exc:
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'value'}: {e['msg']}"
            for e in exc.errors()[:10]
        )
