import json
import uuid
from typing import Any

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from pydantic import BaseModel, ConfigDict

from nexscout.agent_runtime.context_builder import (
    CompactionLostIds,
    CompactSummary,
    ContextOverflow,
    Section,
    build_context,
    compact,
    estimate_tokens,
    input_budget,
)
from nexscout.agents.profile_summary import verify_sentences
from nexscout.domain.errors import ValidationFailed
from nexscout.infrastructure.llm.base import (
    CompletionRequest,
    Message,
    ModelCapabilities,
    OutputInvalid,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderUnavailable,
    Usage,
    estimate_cost,
)
from nexscout.infrastructure.llm.mock import MockProvider
from nexscout.infrastructure.llm.openai_compat import OpenAICompatibleProvider
from nexscout.infrastructure.llm.structured import extract_json, structured
from nexscout.infrastructure.security.secrets import SecretBox, SecretsUnavailable
from nexscout.infrastructure.security.urls import check_outbound_url, is_local_address


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    score: int


def _req() -> CompletionRequest:
    return CompletionRequest(messages=[Message("user", "hi")], purpose="test")


NO_SCHEMA = ModelCapabilities(
    context_window=4096, max_output_tokens=512, json_schema=False, data_leaves_device=False
)


# ----------------------------------------------------------------------------- structured
async def test_structured_valid_first_try() -> None:
    res = await structured(MockProvider(script=['{"answer": "x", "score": 3}']), _req(), Out)
    assert res.value == Out(answer="x", score=3)
    assert len(res.calls) == 1


async def test_structured_repairs_once_with_validation_feedback() -> None:
    provider = MockProvider(script=['```json\n{"answer": "x"}\n```', '{"answer": "x", "score": 1}'])
    res = await structured(provider, _req(), Out)
    assert res.value.score == 1
    assert len(res.calls) == 2
    repair_prompt = provider.requests[1].messages[-1].content
    assert "score" in repair_prompt  # the model is told exactly what was wrong


async def test_structured_gives_up_after_repair() -> None:
    provider = MockProvider(script=["not json at all", '{"answer": 1, "score": "x", "z": 0}'])
    with pytest.raises(OutputInvalid):
        await structured(provider, _req(), Out)


async def test_structured_falls_back_to_instructions_without_native_schema() -> None:
    provider = MockProvider(script=['{"answer": "x", "score": 3}'], capabilities=NO_SCHEMA)
    await structured(provider, _req(), Out)
    sent = provider.requests[0]
    assert sent.json_schema is None
    assert "JSON Schema" in (sent.system or "")


def test_extract_json_tolerates_prose() -> None:
    assert extract_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def test_cost_estimate() -> None:
    caps = ModelCapabilities(
        1000, 100, True, True, input_cost_per_mtok=4.0, output_cost_per_mtok=20.0
    )
    assert estimate_cost(caps, Usage(1_000_000, 500_000)) == 14.0
    assert estimate_cost(NO_SCHEMA, Usage(10, 10)) is None


# -------------------------------------------------------------------- openai-compatible
def _transport(status: int, body: dict[str, Any], seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


async def test_openai_compatible_request_and_usage() -> None:
    seen: list[httpx.Request] = []
    body = {
        "model": "llama3.1:8b",
        "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    caps = ModelCapabilities(8192, 512, True, False)
    p = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1/",
        model="llama3.1:8b",
        api_key="sk-test-key",
        capabilities=caps,
        transport=_transport(200, body, seen),
    )
    req = CompletionRequest(
        messages=[Message("user", "hi")],
        system="sys",
        json_schema={"type": "object"},
        schema_name="Ping",
    )
    out = await p.complete(req)
    assert out.text == '{"ok":true}'
    assert out.usage == Usage(12, 3)
    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer sk-test-key"
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["response_format"]["json_schema"]["name"] == "Ping"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderAuthError),
        (429, ProviderUnavailable),
        (503, ProviderUnavailable),
        (400, ProviderBadRequest),
    ],
)
async def test_openai_compatible_error_mapping(status: int, error: type[Exception]) -> None:
    p = OpenAICompatibleProvider(
        base_url="http://localhost:1/v1",
        model="m",
        api_key=None,
        capabilities=NO_SCHEMA,
        transport=_transport(status, {"error": {"message": "x"}}, []),
    )
    with pytest.raises(error):
        await p.complete(_req())


# ----------------------------------------------------------------------- context builder
def test_context_respects_budget_and_priorities() -> None:
    lines = [f"item {i} " + "x" * 50 for i in range(100)]
    built = build_context(
        [
            Section("task", ["Do the thing."], required=True),
            Section("low", lines, priority=50),
            Section("high", lines[:3], priority=1),
        ],
        budget_tokens=200,
    )
    assert built.tokens <= 200
    assert built.included["high"] == 3  # more important section kept in full
    assert built.dropped["low"] > 0
    assert built.text.index("## task") < built.text.index("## low")  # original order kept


def test_required_context_must_fit() -> None:
    with pytest.raises(ContextOverflow):
        build_context([Section("task", ["x" * 5000], required=True)], budget_tokens=100)


def test_input_budget_reserves_output_and_margin() -> None:
    assert input_budget(8192, 1024) == int((8192 - 1024) * 0.9)
    assert estimate_tokens("a" * 35) == 11


async def test_compaction_must_keep_every_id() -> None:
    ids = [str(uuid.uuid4()) for _ in range(3)]
    items = [f"fact {i} supports the claim" for i in ids]

    async def good(_: list[str]) -> CompactSummary:
        return CompactSummary(summary="all facts", ids=ids)

    async def lossy(_: list[str]) -> CompactSummary:
        return CompactSummary(summary=f"only {ids[0]}", ids=[])

    assert (await compact(items, good)).ids == ids
    with pytest.raises(CompactionLostIds):
        await compact(items, lossy)


# ---------------------------------------------------------------------- claim verifier
def test_verifier_drops_unsupported_sentences() -> None:
    facts = [
        {
            "id": "a",
            "section": "employment",
            "label": "Engineer at Acme",
            "data": {"title": "Engineer", "organization": "Acme", "start": "2021"},
        }
    ]
    kept, dropped = verify_sentences(
        [
            {"text": "Worked as Engineer at Acme since 2021.", "fact_ids": ["a"]},
            {"text": "Led a team of 12 engineers.", "fact_ids": ["a"]},
            {"text": "Award-winning researcher.", "fact_ids": []},
            {"text": "Worked at Google.", "fact_ids": ["zzz"]},
        ],
        facts,
    )
    assert [k["text"] for k in kept] == ["Worked as Engineer at Acme since 2021."]
    reasons = [d["reason"] for d in dropped]
    assert reasons[0].startswith("numbers not in the cited entries: 12")
    assert reasons[1] == "cites no profile entry"
    assert reasons[2] == "cites entries that don't exist"


# ------------------------------------------------------------------- secrets and URLs
def test_secret_box_roundtrip_and_binding() -> None:
    box = SecretBox(b"k" * 32)
    owner = uuid.uuid4()
    sealed = box.seal("sk-live-123456", owner_id=owner, purpose="provider_api_key")
    assert b"sk-live" not in sealed.ciphertext
    assert box.open(sealed, owner_id=owner, purpose="provider_api_key") == "sk-live-123456"
    with pytest.raises(InvalidTag):  # bound to another owner
        box.open(sealed, owner_id=uuid.uuid4(), purpose="provider_api_key")
    with pytest.raises(SecretsUnavailable):
        SecretBox(b"short")


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://[fd00:ec2::254]/",
        "ftp://example.com",
        "http://user:pw@example.com",
    ],
)
def test_metadata_and_bad_urls_always_blocked(url: str) -> None:
    with pytest.raises(ValidationFailed):
        check_outbound_url(url, allow_private=True, resolve=False)


def test_private_networks_depend_on_setting() -> None:
    assert check_outbound_url("http://127.0.0.1:11434/v1", allow_private=True, resolve=False)
    with pytest.raises(ValidationFailed):
        check_outbound_url("http://127.0.0.1:11434/v1", allow_private=False, resolve=False)
    with pytest.raises(ValidationFailed):
        check_outbound_url("http://10.0.0.5/v1", allow_private=False, resolve=False)
    assert is_local_address("http://localhost:1234/v1")
    assert not is_local_address("https://api.openai.com/v1")
