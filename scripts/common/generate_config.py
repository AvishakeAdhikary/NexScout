#!/usr/bin/env python3
"""Interactive generator for the three NexScout config files.

This is a STANDALONE, cross-platform helper (Windows / Linux / macOS). It only
needs the Python standard library plus ``pyyaml`` (already a NexScout
dependency). It interactively builds the three YAML files that NexScout loads
and deep-merges at runtime:

    profile.yaml      résumé / applicant facts   (lowest priority)
    settings.yaml     operational configuration  (middle priority)
    credentials.yaml  secrets, plaintext         (highest priority)

They are written into the NexScout config directory:

    $NEXSCOUT_DIR   (if set)   else   ~/.nexscout

Usage::

    python scripts/common/generate_config.py [TARGET_DIR]

If ``TARGET_DIR`` is omitted the directory above is used. Existing files are
never overwritten without an explicit y/n confirmation (default: no).

Run it directly; the launcher scripts call it automatically when the config
files are missing or when ``-Setup`` / ``--setup`` is passed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - guidance only
    sys.stderr.write(
        "ERROR: pyyaml is not installed. Install it with:\n"
        "    pip install pyyaml\n"
        "(or install NexScout itself, which depends on it).\n"
    )
    sys.exit(1)


# A sentinel meaning "the user typed '-' to skip this key entirely".
SKIP = object()


# --------------------------------------------------------------------------- #
# Prompt helpers
# --------------------------------------------------------------------------- #
def _ask(prompt: str, default: str | None = None, *, secret: bool = False) -> Any:
    """Ask a single free-text question.

    Returns:
        * the typed string,
        * the ``default`` if the user just pressed Enter,
        * the :data:`SKIP` sentinel if the user typed a single ``-``.

    Raises ``EOFError`` / ``KeyboardInterrupt`` upward so the caller can abort
    cleanly.
    """
    suffix = f" [{default}]" if default not in (None, "") else " [skip with -]"
    raw = input(f"  {prompt}{suffix}: ").strip()
    if raw == "-":
        return SKIP
    if raw == "":
        # Empty default still counts as "use default" (may be "" -> skip later).
        return default if default is not None else SKIP
    return raw


def _ask_bool(prompt: str, default: bool) -> Any:
    """Ask a yes/no question. ``-`` skips the key, Enter accepts the default."""
    dft = "y" if default else "n"
    raw = input(f"  {prompt} (y/n) [{dft}]: ").strip().lower()
    if raw == "-":
        return SKIP
    if raw == "":
        return default
    return raw in ("y", "yes", "true", "1")


def _ask_int(prompt: str, default: int | None) -> Any:
    """Ask for an integer. ``-`` skips, Enter accepts the default."""
    while True:
        raw = _ask(prompt, str(default) if default is not None else None)
        if raw is SKIP:
            return SKIP
        try:
            return int(str(raw))
        except (TypeError, ValueError):
            print("    ! please enter a whole number (or '-' to skip).")


def _ask_csv(prompt: str, default: list[str] | None) -> Any:
    """Ask for a comma-separated list -> list[str]. ``-`` skips."""
    dft = ", ".join(default) if default else None
    raw = _ask(prompt, dft)
    if raw is SKIP:
        return SKIP
    items = [piece.strip() for piece in str(raw).split(",") if piece.strip()]
    return items if items else SKIP


def _put(mapping: dict[str, Any], key: str, value: Any) -> None:
    """Assign ``key`` only when the value was not skipped/empty."""
    if value is SKIP or value is None:
        return
    if isinstance(value, str) and value == "":
        return
    mapping[key] = value


def _prune(mapping: dict[str, Any]) -> dict[str, Any]:
    """Drop empty dict / list values so skipped sub-sections don't appear."""
    out: dict[str, Any] = {}
    for key, val in mapping.items():
        if isinstance(val, dict):
            pruned = _prune(val)
            if pruned:
                out[key] = pruned
        elif val is SKIP or val is None:
            continue
        elif isinstance(val, (list, str)) and len(val) == 0:
            continue
        else:
            out[key] = val
    return out


def _section(title: str) -> None:
    bar = "=" * len(title)
    print(f"\n{bar}\n{title}\n{bar}")


# --------------------------------------------------------------------------- #
# Builders for each file
# --------------------------------------------------------------------------- #
def build_profile() -> dict[str, Any]:
    """Interactively build the profile.yaml (résumé) document."""
    _section("RÉSUMÉ (profile.yaml)")
    print("Your applicant facts. Tailoring is constrained to what you enter here.")

    meta = {"v": 1}
    _put(meta, "locale", _ask("Locale", "en_US"))

    me: dict[str, Any] = {}
    _put(me, "legal", _ask("Legal name", "Jane Q. Public"))
    _put(me, "pref", _ask("Preferred name", "Jane"))
    _put(me, "email", _ask("Email", "jane@example.com"))
    _put(me, "phone", _ask("Phone", "+1-415-555-0100"))
    _put(me, "city", _ask("City", "San Francisco"))
    _put(me, "region", _ask("Region / state", "CA"))
    _put(me, "country", _ask("Country", "USA"))
    _put(me, "postcode", _ask("Postcode", "94110"))

    links: dict[str, Any] = {}
    _put(links, "li", _ask("LinkedIn URL", "linkedin.com/in/janepublic"))
    _put(links, "gh", _ask("GitHub URL", "github.com/janepublic"))
    _put(links, "web", _ask("Website", "jane.dev"))
    _put(links, "portfolio", _ask("Portfolio URL", "jane.dev/work"))
    if links:
        me["links"] = links

    auth: dict[str, Any] = {}
    _put(auth, "authorized", _ask_bool("Authorized to work in target country?", True))
    _put(auth, "sponsor", _ask_bool("Require visa sponsorship?", False))
    _put(auth, "permit", _ask("Work permit / status (e.g. USC, GC, H1B)", "USC"))

    pay: dict[str, Any] = {}
    _put(pay, "expect", _ask_int("Expected annual pay", 165000))
    rmin = _ask_int("Pay range minimum", 150000)
    rmax = _ask_int("Pay range maximum", 200000)
    if rmin is not SKIP and rmax is not SKIP:
        pay["range"] = [rmin, rmax]
    _put(pay, "currency", _ask("Currency", "USD"))

    avail: dict[str, Any] = {}
    _put(avail, "start", _ask("Availability / start", "Immediately"))
    _put(avail, "fulltime", _ask_bool("Open to full-time?", True))
    _put(avail, "contract", _ask_bool("Open to contract?", False))

    exp: dict[str, Any] = {}
    _put(exp, "years", _ask_int("Years of experience", 7))
    _put(exp, "edu", _ask("Highest education", "BSc Computer Science"))
    _put(exp, "current_title", _ask("Current title", "Senior Software Engineer"))
    _put(
        exp,
        "target_titles",
        _ask_csv("Target titles (comma-separated)", ["Staff Engineer", "Senior Backend Engineer"]),
    )

    skills: dict[str, Any] = {}
    _put(skills, "lang", _ask_csv("Languages (CSV)", ["Python", "TypeScript", "SQL"]))
    _put(skills, "fw", _ask_csv("Frameworks (CSV)", ["FastAPI", "React"]))
    _put(skills, "infra", _ask_csv("Infra (CSV)", ["Docker", "Kubernetes", "AWS"]))
    _put(skills, "data", _ask_csv("Data stores (CSV)", ["Postgres", "Redis"]))
    _put(skills, "tools", _ask_csv("Tools (CSV)", ["Git", "Linux"]))

    facts: dict[str, Any] = {}
    _put(facts, "companies", _ask_csv("Past companies (CSV)", ["Acme Corp", "Globex"]))
    _put(facts, "projects", _ask_csv("Notable projects (CSV)", ["Search Indexer", "Auth Gateway"]))
    _put(facts, "school", _ask("School", "State University"))
    _put(facts, "metrics", _ask_csv("Impact metrics (CSV)", ["reduced p99 by 38%", "10M MAU"]))

    eeo: dict[str, Any] = {}
    _put(eeo, "gender", _ask("EEO gender", "decline"))
    _put(eeo, "race", _ask("EEO race", "decline"))
    _put(eeo, "veteran", _ask("EEO veteran status", "not-protected"))
    _put(eeo, "disability", _ask("EEO disability", "decline"))

    profile: dict[str, Any] = {
        "meta": meta,
        "me": me,
        "auth": auth,
        "pay": pay,
        "avail": avail,
        "exp": exp,
        "skills": skills,
        "facts": facts,
        "eeo": eeo,
    }
    return _prune(profile)


def build_settings() -> dict[str, Any]:
    """Interactively build the settings.yaml (operational config) document."""
    _section("SETTINGS (settings.yaml)")
    print("Operational knobs: search, LLM, apply behaviour, captcha, channel, SMTP.")

    # --- search ----------------------------------------------------------- #
    search: dict[str, Any] = {}
    queries: list[dict[str, Any]] = []
    q1 = _ask("Search query #1", "staff engineer")
    if q1 is not SKIP:
        queries.append({"q": q1, "tier": 1})
    q2 = _ask("Search query #2", "senior backend")
    if q2 is not SKIP:
        queries.append({"q": q2, "tier": 1})
    if queries:
        search["queries"] = queries

    locations: list[dict[str, Any]] = []
    loc = _ask("Primary location query", "San Francisco, CA")
    if loc is not SKIP:
        locations.append({"label": "Primary", "q": loc, "remote": False})
    remote = _ask_bool("Include a Remote-US location?", True)
    if remote is True:
        locations.append({"label": "Remote US", "q": "Remote", "remote": True})
    if locations:
        search["locations"] = locations

    _put(search, "min_score", _ask_int("Minimum fit score to apply (0-10)", 7))
    _put(search, "hours_old", _ask_int("Only postings newer than N hours", 72))

    # --- llm -------------------------------------------------------------- #
    print(
        "\n  NOTE: LLM backend is LM Studio (OpenAI-compatible) on http://localhost:1234/v1.\n"
        "  Set the model id to whatever LM Studio is serving, e.g. lmstudio:gemma-2-9b-it.\n"
        "  The placeholder 'lmstudio:local-model' works once LM Studio has any model loaded."
    )
    llm: dict[str, Any] = {}
    _put(llm, "primary", _ask("LLM primary (lmstudio:<model-id>)", "lmstudio:local-model"))
    _put(llm, "fallback", _ask("LLM fallback", "lmstudio:local-model"))
    _put(llm, "judge", _ask("LLM judge", "lmstudio:local-model"))

    # --- apply ------------------------------------------------------------ #
    apply: dict[str, Any] = {}
    _put(apply, "workers", _ask_int("Apply workers (parallel browsers)", 2))
    _put(apply, "headless", _ask_bool("Run browser headless?", True))
    _put(apply, "dry_run", _ask_bool("Dry-run (don't actually submit)?", False))
    _put(apply, "max_attempts", _ask_int("Max attempts per job", 3))

    # --- captcha ---------------------------------------------------------- #
    captcha: dict[str, Any] = {}
    print(
        "\n  CAPTCHA is OPTIONAL. With no api_key, captcha-walled jobs are parked for\n"
        "  manual review (apply_status='captcha_manual'). The api_key goes in credentials.yaml."
    )
    _put(captcha, "provider", _ask("Captcha provider (capsolver/twocaptcha/anticaptcha)", "capsolver"))

    # --- openclaw --------------------------------------------------------- #
    openclaw: dict[str, Any] = {}
    print(
        "\n  OpenClaw relays clarifying questions to you over a chat channel.\n"
        "  Channel tokens are set via ENV, not in these files (see the SECRETS section)."
    )
    channel = _ask("OpenClaw channel (cli/telegram/discord)", "cli")
    _put(openclaw, "channel", channel)

    # --- smtp ------------------------------------------------------------- #
    smtp: dict[str, Any] = {}
    print(
        "\n  SMTP is OPTIONAL (used for email-only postings). The password goes in\n"
        "  credentials.yaml. Skip the host to fall back to browser-driven Gmail."
    )
    _put(smtp, "host", _ask("SMTP host", "smtp.gmail.com"))
    _put(smtp, "port", _ask_int("SMTP port", 465))
    _put(smtp, "user", _ask("SMTP user / email", "jane@example.com"))
    _put(smtp, "use_ssl", _ask_bool("SMTP use SSL?", True))
    _put(smtp, "use_tls", _ask_bool("SMTP use STARTTLS?", False))

    settings: dict[str, Any] = {
        "search": search,
        "llm": llm,
        "apply": apply,
        "captcha": captcha,
        "openclaw": openclaw,
        "smtp": smtp,
    }
    return _prune(settings), channel


def build_credentials() -> dict[str, Any]:
    """Interactively build the credentials.yaml (secrets) document."""
    _section("SECRETS (credentials.yaml)")
    print(
        "!!! WARNING: these are written in PLAINTEXT to credentials.yaml.\n"
        "    Protect that file (chmod 600 on Linux). Channel tokens (Telegram /\n"
        "    Discord) are NOT stored here — they are set via ENV variables.\n"
        "    Press Enter to accept the (usually empty) default, or '-' to skip a key.\n"
        "    You can also use ${env:NAME} as a value to defer to an env var at load time."
    )

    captcha: dict[str, Any] = {}
    _put(captcha, "api_key", _ask("Captcha API key (empty = skip / manual review)", ""))

    smtp: dict[str, Any] = {}
    _put(smtp, "password", _ask("SMTP password", "", secret=True))

    creds: dict[str, Any] = {"captcha": captcha, "smtp": smtp}
    _put(creds, "gmail_password", _ask("Gmail app password", "", secret=True))
    _put(creds, "password", _ask("Account password (job-board login)", "", secret=True))
    _put(creds, "proxy", _ask("Outbound proxy URL (e.g. http://user:pass@host:port)", ""))

    return _prune(creds)


# --------------------------------------------------------------------------- #
# File writing
# --------------------------------------------------------------------------- #
_HEADERS = {
    "profile.yaml": "# NexScout profile.yaml — your résumé / applicant facts (lowest merge priority).\n",
    "settings.yaml": "# NexScout settings.yaml — operational config: search, llm, apply, captcha, openclaw, smtp.\n",
    "credentials.yaml": "# NexScout credentials.yaml — SECRETS in plaintext (highest merge priority). Keep private.\n",
}


def _confirm_overwrite(path: Path) -> bool:
    """Return True if it is OK to write ``path`` (asking only when it exists)."""
    if not path.exists():
        return True
    raw = input(f"  {path.name} already exists — overwrite? (y/n) [n]: ").strip().lower()
    return raw in ("y", "yes")


def _write_yaml(path: Path, data: dict[str, Any]) -> bool:
    """Write ``data`` as YAML with a header comment. Returns True if written."""
    if not data:
        print(f"  (skipped {path.name}: nothing to write)")
        return False
    if not _confirm_overwrite(path):
        print(f"  (kept existing {path.name})")
        return False
    header = _HEADERS.get(path.name, "")
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path.write_text(header + body, encoding="utf-8")
    try:
        # Best-effort tighten perms on the secrets file (POSIX only).
        if path.name == "credentials.yaml" and os.name == "posix":
            path.chmod(0o600)
    except OSError:
        pass
    print(f"  wrote {path}")
    return True


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def _target_dir(argv: list[str]) -> Path:
    if len(argv) > 1 and argv[1].strip():
        return Path(argv[1]).expanduser()
    env = os.environ.get("NEXSCOUT_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".nexscout"


def _print_channel_env_help(channel: str) -> None:
    """Offer to print the export / $env: lines for the chosen channel's ENV vars."""
    if channel not in ("telegram", "discord"):
        return
    if channel == "telegram":
        wanted = "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    else:
        wanted = "DISCORD_WEBHOOK_URL  (or DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID)"
    raw = input(f"\n  Print the ENV export lines for '{channel}' ({wanted})? (y/n) [y]: ").strip().lower()
    if raw not in ("", "y", "yes"):
        return

    print("\n  --- bash / zsh (Linux/macOS) ---")
    if channel == "telegram":
        print('  export TELEGRAM_BOT_TOKEN="123456:ABC..."')
        print('  export TELEGRAM_CHAT_ID="987654321"')
    else:
        print('  export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."')
        print("  # OR, instead of the webhook:")
        print('  export DISCORD_BOT_TOKEN="..."')
        print('  export DISCORD_CHANNEL_ID="..."')

    print("\n  --- PowerShell (Windows) ---")
    if channel == "telegram":
        print('  $env:TELEGRAM_BOT_TOKEN = "123456:ABC..."')
        print('  $env:TELEGRAM_CHAT_ID   = "987654321"')
    else:
        print('  $env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."')
        print("  # OR, instead of the webhook:")
        print('  $env:DISCORD_BOT_TOKEN  = "..."')
        print('  $env:DISCORD_CHANNEL_ID = "..."')


def main(argv: list[str]) -> int:
    target = _target_dir(argv)
    print("NexScout interactive config generator")
    print("=====================================")
    print(
        "This builds three YAML files. For EVERY prompt:\n"
        "  * press ENTER to accept the [default] shown in brackets;\n"
        "  * type a value to override it;\n"
        "  * type a single dash '-' to SKIP that key entirely (it will be omitted).\n"
    )
    print(f"Target directory: {target}")
    print("  (override with the NEXSCOUT_DIR env var or a path argument)\n")

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write(f"ERROR: cannot create {target}: {exc}\n")
        return 1

    try:
        profile = build_profile()
        settings, channel = build_settings()
        credentials = build_credentials()
    except (EOFError, KeyboardInterrupt):
        print("\n\nAborted — no files were written.")
        return 130

    print("\n--- Writing files ---")
    written: list[str] = []
    for name, data in (
        ("profile.yaml", profile),
        ("settings.yaml", settings),
        ("credentials.yaml", credentials),
    ):
        if _write_yaml(target / name, data):
            written.append(name)

    try:
        _print_channel_env_help(channel)
    except (EOFError, KeyboardInterrupt):
        pass

    # --- Summary --------------------------------------------------------- #
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    if written:
        print("Files written:")
        for name in written:
            print(f"  - {target / name}")
    else:
        print("No files were written (all skipped or kept existing).")

    print("\nDashboards (after you start the stack):")
    print("  NexScout web UI:    http://localhost:8765")
    print("  OpenClaw dashboard: http://localhost:18789")

    print("\nStart the stack with one of:")
    if os.name == "nt":
        print("  Direct : powershell -File scripts\\windows\\start-direct.ps1")
        print("  uv     : powershell -File scripts\\windows\\start-uv.ps1")
        print("  Docker : powershell -File scripts\\windows\\start-docker.ps1")
    else:
        print("  Direct : ./scripts/linux/start-direct.sh")
        print("  uv     : ./scripts/linux/start-uv.sh")
        print("  Docker : ./scripts/linux/start-docker.sh")
    print("\nReminder: LM Studio must be running on http://localhost:1234 with a model loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
