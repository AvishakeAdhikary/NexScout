#!/usr/bin/env python3
"""Switch NexScout's LLM model by rewriting the 3-file YAML config.

Standalone (Python 3.11+, stdlib + pyyaml — which NexScout already depends on).
It edits the ``llm`` block across the split layout so swapping providers/models
is a one-liner:

  * ``settings.yaml`` gets ``llm.primary`` / ``llm.fallback`` / ``llm.judge``
    and (for OpenAI-compatible schemes) ``llm.providers.<scheme>.{base_url,model}``.
  * ``credentials.yaml`` gets the secret: ``llm.providers.<scheme>.api_key``
    (highest-priority file, so the key stays out of settings.yaml).

These deep-merge at load time (profile.yaml < settings.yaml < credentials.yaml),
so ``Profile.from_path()`` sees the combined result.

Provider specs are ``"<scheme>:<model>"`` — and the router splits the scheme on
the FIRST colon only, so a model id that itself contains ``:`` (e.g.
``google/gemma-4-26b-a4b-it:free``) is preserved verbatim:
``openai_compat:google/gemma-4-26b-a4b-it:free``.

Presets:
  lmstudio       -> spec  lmstudio:<model>        (default model: local-model)
  openrouter     -> scheme openai_compat, base_url https://openrouter.ai/api/v1
  nim            -> scheme nim,           base_url https://integrate.api.nvidia.com/v1
  openai         -> spec  openai:<model>
  gemini         -> spec  <model>                 (bare, e.g. gemini-2.0-flash)
  anthropic      -> spec  anthropic:<model>
  ollama         -> spec  ollama:<model>
  openai_compat  -> generic; requires --base-url; spec openai_compat:<model>

By default primary = fallback = judge = the chosen spec; pass --judge-model to
give the judge a different model (same scheme).

Usage:
    python set_model.py --provider openrouter \
        --model google/gemma-4-26b-a4b-it:free --api-key sk-or-...
    python set_model.py --provider lmstudio --model local-model
    python set_model.py --provider gemini --model gemini-2.0-flash
    python set_model.py --provider openai_compat --model my-model \
        --base-url https://my-endpoint/v1 --api-key KEY
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - guidance only
    print(
        "ERROR: PyYAML is required. Install it (it ships with NexScout):\n"
        "  pip install pyyaml      # or: uv run python scripts/common/set_model.py ...",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


# Schemes that use an llm.providers.<scheme> endpoint block (base_url/api_key).
_OPENAI_COMPAT_SCHEMES = {"openai_compat", "nim"}


def _spec(scheme: str, model: str) -> str:
    """Build a ``scheme:model`` spec, or a bare model for the gemini default.

    The router splits on the FIRST colon, so the (possibly colon-bearing) model
    id is appended unchanged.
    """
    if scheme == "":  # bare model (gemini preset)
        return model
    return f"{scheme}:{model}"


class Preset:
    """A provider preset: how to turn (--model, --base-url) into config."""

    def __init__(
        self,
        name: str,
        *,
        scheme: str,
        default_base_url: str | None = None,
        default_model: str | None = None,
        requires_base_url: bool = False,
    ) -> None:
        self.name = name
        # ``scheme`` is the router scheme; "" means a bare model id (gemini).
        self.scheme = scheme
        self.default_base_url = default_base_url
        self.default_model = default_model
        self.requires_base_url = requires_base_url

    @property
    def uses_provider_block(self) -> bool:
        return self.scheme in _OPENAI_COMPAT_SCHEMES


# The preset registry. The CLI --provider value is the KEY.
PRESETS: dict[str, Preset] = {
    "lmstudio": Preset("lmstudio", scheme="lmstudio", default_model="local-model"),
    "openrouter": Preset(
        "openrouter",
        scheme="openai_compat",
        default_base_url="https://openrouter.ai/api/v1",
    ),
    "nim": Preset(
        "nim",
        scheme="nim",
        default_base_url="https://integrate.api.nvidia.com/v1",
    ),
    "openai": Preset("openai", scheme="openai"),
    "gemini": Preset("gemini", scheme=""),  # bare model id
    "anthropic": Preset("anthropic", scheme="anthropic"),
    "ollama": Preset("ollama", scheme="ollama"),
    "openai_compat": Preset(
        "openai_compat",
        scheme="openai_compat",
        requires_base_url=True,
    ),
}


def _config_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    override = os.environ.get("NEXSCOUT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".nexscout").resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping (preserving all keys), or {} if absent/empty."""
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise SystemExit(f"ERROR: {path} is not a YAML mapping; refusing to edit.")
    return doc


def _dump_yaml(path: Path, doc: dict[str, Any], header: str | None = None) -> None:
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    text = (header + body) if header else body
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="set_model.py",
        description="Switch the NexScout LLM model by rewriting settings.yaml + credentials.yaml.",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=sorted(PRESETS),
        help="Provider preset.",
    )
    parser.add_argument("--model", required=True, help="Model id (may contain ':').")
    parser.add_argument("--api-key", default=None, help="Bearer API key -> credentials.yaml.")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL ending in /v1.")
    parser.add_argument("--judge-model", default=None, help="Override the judge model (same scheme).")
    parser.add_argument("--target", default=None, help="Config dir (default: $NEXSCOUT_DIR or ~/.nexscout).")
    return parser.parse_args(argv)


def apply_model(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    judge_model: str | None,
    target: Path,
) -> dict[str, Any]:
    """Rewrite the llm config in settings.yaml (+ credentials.yaml). Returns the
    resulting ``llm`` settings block (as written to settings.yaml).

    Raises SystemExit with a clear message on a missing required option.
    """
    preset = PRESETS[provider]

    if preset.requires_base_url and not base_url:
        raise SystemExit(f"ERROR: the '{provider}' preset needs an endpoint — pass --base-url https://your-endpoint/v1")

    effective_base_url = base_url or preset.default_base_url
    chosen_model = model or preset.default_model
    if not chosen_model:
        raise SystemExit(f"ERROR: the '{provider}' preset needs a model — pass --model <id>")

    spec = _spec(preset.scheme, chosen_model)
    judge_spec = spec
    if judge_model:
        judge_spec = _spec(preset.scheme, judge_model)

    settings_path = target / "settings.yaml"
    creds_path = target / "credentials.yaml"

    # --- settings.yaml: load -> modify llm block -> dump (keep other keys) -- #
    settings = _load_yaml(settings_path)
    llm = settings.get("llm")
    if not isinstance(llm, dict):
        llm = {}
    llm["primary"] = spec
    llm["fallback"] = spec
    llm["judge"] = judge_spec

    if preset.uses_provider_block:
        providers = llm.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        entry = providers.get(preset.scheme)
        if not isinstance(entry, dict):
            entry = {}
        if effective_base_url:
            entry["base_url"] = effective_base_url
        # Store the default model on the provider entry too, so a bare scheme
        # spec still resolves; harmless and matches LLMProviderEndpoint.model.
        entry["model"] = chosen_model
        providers[preset.scheme] = entry
        llm["providers"] = providers

    settings["llm"] = llm
    _dump_yaml(
        settings_path,
        settings,
        header="# NexScout settings — search / llm / apply / openclaw / captcha provider / smtp.\n",
    )

    # --- credentials.yaml: write the api_key under llm.providers.<scheme> ---- #
    if api_key is not None and preset.uses_provider_block:
        creds = _load_yaml(creds_path)
        c_llm = creds.get("llm")
        if not isinstance(c_llm, dict):
            c_llm = {}
        c_providers = c_llm.get("providers")
        if not isinstance(c_providers, dict):
            c_providers = {}
        c_entry = c_providers.get(preset.scheme)
        if not isinstance(c_entry, dict):
            c_entry = {}
        c_entry["api_key"] = api_key
        c_providers[preset.scheme] = c_entry
        c_llm["providers"] = c_providers
        creds["llm"] = c_llm
        _dump_yaml(
            creds_path,
            creds,
            header="# NexScout secrets — plaintext. Keep private; never commit. ${env:NAME} also works here.\n",
        )
    elif api_key is not None and not preset.uses_provider_block:
        # openai / anthropic / gemini read their key from the env var
        # (OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY). We don't
        # invent a provider block for those — just inform the user.
        print(
            f"[set-model] NOTE: '{provider}' reads its key from an environment variable, not "
            f"credentials.yaml. --api-key was ignored; set the env var instead.",
        )

    return llm


def main(argv: list[str] | None = None) -> int:
    args = build_args(argv)
    target = _config_dir(args.target)
    print(f"NexScout config dir: {target}")

    try:
        llm_block = apply_model(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            judge_model=args.judge_model,
            target=target,
        )
    except SystemExit as e:
        # Re-raise with the message already attached (argparse-style clean exit).
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            return 2
        raise

    print("\n[set-model] Wrote the following llm block to settings.yaml:")
    print(yaml.safe_dump({"llm": llm_block}, sort_keys=False, allow_unicode=True).rstrip())
    if args.api_key is not None and args.provider in {"openrouter", "nim", "openai_compat"}:
        print(f"[set-model] Wrote llm.providers.{PRESETS[args.provider].scheme}.api_key to credentials.yaml.")

    print(
        "\n[set-model] Done. In Docker the autopilot reloads the profile each pass, so the\n"
        "            switch applies live within a minute or two. To apply it immediately,\n"
        "            recreate the services:  docker compose up -d nexscout nexscout-web nexscout-mcp"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
