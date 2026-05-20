"""Stage 2 — Enrichment (§9 of plan.md).

The 3-tier cascade (JSON-LD → deterministic CSS → LLM) lives in :mod:`.detail`.
"""

from __future__ import annotations

from .detail import (
    APPLY_SELECTORS,
    DESCRIPTION_SELECTORS,
    LLM_PROMPT,
    SITE_DELAYS,
    SKIP_SITES,
    EnrichmentResult,
    clean_description_html,
    enrich_html,
    extract_apply_url_from_posting,
    extract_main_content,
    extract_posting_from_jsonld,
    is_permanent_http_error,
    is_transient_http_error,
    parse_jsonld_blocks,
    resolve_relative_url,
    tier1_jsonld,
    tier2_css,
    tier3_llm,
)

__all__ = [
    "APPLY_SELECTORS",
    "DESCRIPTION_SELECTORS",
    "LLM_PROMPT",
    "SITE_DELAYS",
    "SKIP_SITES",
    "EnrichmentResult",
    "clean_description_html",
    "enrich_html",
    "extract_apply_url_from_posting",
    "extract_main_content",
    "extract_posting_from_jsonld",
    "is_permanent_http_error",
    "is_transient_http_error",
    "parse_jsonld_blocks",
    "resolve_relative_url",
    "tier1_jsonld",
    "tier2_css",
    "tier3_llm",
]
