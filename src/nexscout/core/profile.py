"""User profile schema (§3 of plan.md).

The YAML file at ``~/.nexscout/profile.yaml`` is the single source of truth
for everything the agent knows about the candidate.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import credentials_path, profile_path, settings_path
from .errors import ConfigError

CURRENT_SCHEMA_VERSION = 1
_ENV_PATTERN = re.compile(r"\$\{env:([A-Z0-9_]+)\}")

#: Top-level sections that belong in the résumé file (``profile.yaml``). Any
#: unknown ``extra="allow"`` key (e.g. ``certifications``/``publications``/
#: ``languages``) also routes here when splitting.
_PROFILE_SECTIONS = ("meta", "me", "auth", "pay", "avail", "exp", "skills", "facts", "eeo")
#: Top-level sections that belong in the operational-config file (``settings.yaml``).
_SETTINGS_SECTIONS = ("search", "llm", "apply", "openclaw")
#: Top-level keys that belong in the secrets file (``credentials.yaml``).
_CREDENTIAL_KEYS = ("gmail_password", "password", "proxy")


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into ``base`` in place (overlay wins).

    Nested mappings are merged key-by-key; any non-mapping value replaces the
    value in ``base``. Used to combine ``profile.yaml`` < ``settings.yaml`` <
    ``credentials.yaml``.
    """
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _load_sidecar(path: Path) -> dict[str, Any] | None:
    """Read a sidecar YAML mapping, or ``None`` if absent/empty/not-a-mapping."""
    if not path.exists():
        return None
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc is None:
        return None
    if not isinstance(doc, dict):
        raise ConfigError(f"config sidecar at {path} is not a YAML mapping")
    return doc


def _resolve_env(value: Any) -> Any:
    """Recursively resolve ``${env:NAME}`` placeholders in strings."""
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class Meta(BaseModel):
    v: int = 1
    locale: str = "en_US"
    updated: date | None = None


class Links(BaseModel):
    li: str = ""
    gh: str = ""
    web: str = ""
    portfolio: str = ""


class Me(BaseModel):
    legal: str
    pref: str
    email: str
    phone: str
    city: str = ""
    region: str = ""
    country: str = ""
    postcode: str = ""
    address: str = ""
    links: Links = Field(default_factory=Links)


class Auth(BaseModel):
    authorized: bool = True
    sponsor: bool = False
    permit: str = "USC"


class Pay(BaseModel):
    expect: int = 0
    range: list[int] = Field(default_factory=lambda: [0, 0])
    currency: str = "USD"
    hourly_note: str = "divide annual by 2080"


class Avail(BaseModel):
    start: str = "Immediately"
    fulltime: bool = True
    contract: bool = False
    notice: str = "2w"


class Exp(BaseModel):
    years: int = 0
    edu: str = ""
    current_title: str = ""
    target_titles: list[str] = Field(default_factory=list)


class Skills(BaseModel):
    lang: list[str] = Field(default_factory=list)
    fw: list[str] = Field(default_factory=list)
    infra: list[str] = Field(default_factory=list)
    data: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)

    def all_skills(self) -> list[str]:
        return [*self.lang, *self.fw, *self.infra, *self.data, *self.tools]


class Facts(BaseModel):
    companies: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    school: str = ""
    metrics: list[str] = Field(default_factory=list)


class Eeo(BaseModel):
    gender: str = "decline"
    race: str = "decline"
    veteran: str = "not-protected"
    disability: str = "decline"


class SearchQuery(BaseModel):
    q: str
    tier: int = 1


class SearchLocation(BaseModel):
    label: str
    q: str
    remote: bool = False


class JobspyBoardsCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    # The list of boards (indeed, linkedin, ...)
    boards: list[str] = Field(default_factory=list)


class WebSearchCfg(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["tavily", "brave", "duckduckgo", "searxng"])
    queries_per_day: int = 200


class BoardsCfg(BaseModel):
    jobspy: list[str] = Field(default_factory=lambda: ["indeed", "linkedin", "glassdoor", "zip_recruiter", "google"])
    jobspy_results_per_site: int = 100
    websearch: WebSearchCfg = Field(default_factory=WebSearchCfg)


class SearchConfig(BaseModel):
    queries: list[SearchQuery] = Field(default_factory=list)
    locations: list[SearchLocation] = Field(default_factory=list)
    exclude_titles: list[str] = Field(default_factory=list)
    hours_old: int = 72
    min_score: int = 7
    boards: BoardsCfg = Field(default_factory=BoardsCfg)
    location_accept: list[str] = Field(default_factory=list)
    location_reject_non_remote: list[str] = Field(default_factory=list)
    workday_max_tier: int = 2


class LLMBudgets(BaseModel):
    monthly_usd: float = 30.0
    daily_calls: int = 5000


class LLMConfig(BaseModel):
    primary: str = "gemini-2.0-flash"
    fallback: str = "ollama:llama3.1:70b"
    judge: str = "anthropic:claude-haiku-4-5-20251001"
    budgets: LLMBudgets = Field(default_factory=LLMBudgets)


class ApplyConfig(BaseModel):
    workers: int = 2
    headless: bool = True
    dry_run: bool = False
    max_attempts: int = 3
    max_per_run: int = 0
    permitted_atss: list[str] = Field(
        default_factory=lambda: ["greenhouse", "lever", "ashby", "workday", "taleo", "icims", "smartrecruiters"]
    )
    always_cover_letter: bool = False


class CaptchaConfig(BaseModel):
    provider: str = "capsolver"
    api_key: str = ""
    manual_ats_domains: list[str] = Field(default_factory=lambda: ["ibegin.tcsapps.com"])


class SmtpConfig(BaseModel):
    """Optional SMTP settings for ``send_email`` (§13.2).

    All fields are optional. When ``host`` is set the apply agent uses
    ``smtplib`` directly. When ``host`` is *not* set but the user's email is a
    ``@gmail.com`` address and ``password`` is provided, the agent falls back
    to a browser-driven Gmail login flow (see :mod:`apply.email_browser`).
    """

    host: str = ""
    port: int = 465
    user: str = ""
    password: str = ""
    use_ssl: bool = True
    use_tls: bool = False


class OpenClawTickBudget(BaseModel):
    discover_per_engine: int = 10
    enrich: int = 20
    score: int = 50
    tailor: int = 5
    apply: int = 3


class OpenClawConfig(BaseModel):
    tick_budget: OpenClawTickBudget = Field(default_factory=OpenClawTickBudget)
    #: Active delivery channel: ``cli``, ``telegram`` or ``discord`` (future:
    #: ``slack``). ``cli`` means inbox-only — no message is pushed to a bot.
    #: ``telegram`` requires ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID``;
    #: ``discord`` requires ``DISCORD_WEBHOOK_URL`` (or ``DISCORD_BOT_TOKEN`` +
    #: ``DISCORD_CHANNEL_ID``) in the environment.
    channel: str = "cli"


# ---------------------------------------------------------------------------
# Top-level Profile
# ---------------------------------------------------------------------------


class Profile(BaseModel):
    """The full user profile. Loaded from ``~/.nexscout/profile.yaml``."""

    model_config = ConfigDict(extra="allow")

    meta: Meta = Field(default_factory=Meta)
    me: Me
    auth: Auth = Field(default_factory=Auth)
    pay: Pay = Field(default_factory=Pay)
    avail: Avail = Field(default_factory=Avail)
    exp: Exp = Field(default_factory=Exp)
    skills: Skills = Field(default_factory=Skills)
    facts: Facts = Field(default_factory=Facts)
    eeo: Eeo = Field(default_factory=Eeo)
    search: SearchConfig = Field(default_factory=SearchConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    apply: ApplyConfig = Field(default_factory=ApplyConfig)
    captcha: CaptchaConfig = Field(default_factory=CaptchaConfig)
    openclaw: OpenClawConfig = Field(default_factory=OpenClawConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)
    proxy: str | None = None
    password: str | None = None
    #: Gmail-specific app-password fallback (env-resolved). When the user's
    #: ``me.email`` is a ``@gmail.com`` address and no SMTP host is set, the
    #: agent will drive the browser to mail.google.com using this credential
    #: (or ``smtp.password`` as a fallback).
    gmail_password: str | None = None

    @field_validator("meta", mode="before")
    @classmethod
    def _coerce_meta(cls, v: Any) -> Any:
        return v or {}

    # ---- IO ----
    @classmethod
    def from_path(
        cls,
        path: str | Path | None = None,
        *,
        settings: str | Path | None = None,
        credentials: str | Path | None = None,
    ) -> Profile:
        """Load the profile, deep-merging optional ``settings``/``credentials`` sidecars.

        The résumé lives in ``profile.yaml``; operational config and secrets may
        be split into sibling ``settings.yaml`` and ``credentials.yaml`` files
        (merge priority profile < settings < credentials). When those sidecars
        are absent, a single monolithic ``profile.yaml`` loads exactly as before
        — the split is fully backward-compatible.
        """
        p = Path(path) if path else profile_path()
        if not p.exists():
            raise ConfigError(f"profile not found at {p}; run `nexscout init` first")
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigError(f"profile at {p} is not a YAML mapping")

        # Resolve sidecar locations: explicit args win, else default sibling
        # paths next to the profile file (``<dir>/settings.yaml`` etc.).
        if path is None:
            settings_p = Path(settings) if settings else settings_path()
            creds_p = Path(credentials) if credentials else credentials_path()
        else:
            settings_p = Path(settings) if settings else p.parent / "settings.yaml"
            creds_p = Path(credentials) if credentials else p.parent / "credentials.yaml"

        for sidecar in (settings_p, creds_p):
            doc = _load_sidecar(sidecar)
            if doc is not None:
                _deep_merge(raw, doc)

        raw = _resolve_env(raw)
        raw = _migrate(raw)
        try:
            return cls.model_validate(raw)
        except Exception as e:  # pydantic ValidationError → ConfigError
            raise ConfigError(f"invalid profile: {e}") from e

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json", exclude_none=False)
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def save(self, path: str | Path | None = None) -> None:
        p = Path(path) if path else profile_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_yaml(), encoding="utf-8")

    def save_split(self, directory: str | Path | None = None) -> dict[str, Path]:
        """Write the profile across three files: profile / settings / credentials.

        Routes résumé sections to ``profile.yaml``, operational config to
        ``settings.yaml``, and secrets to ``credentials.yaml`` (``captcha`` and
        ``smtp`` are split so their secret field lives in ``credentials.yaml``
        while the rest stays in ``settings.yaml``). All three files are written
        so the split layout is internally consistent and round-trips through
        :meth:`from_path`. Returns the paths written, keyed by ``profile`` /
        ``settings`` / ``credentials``.
        """
        d = Path(directory) if directory else profile_path().parent
        d.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json", exclude_none=False)

        profile_doc: dict[str, Any] = {}
        settings_doc: dict[str, Any] = {}
        cred_doc: dict[str, Any] = {}

        for key, val in data.items():
            if key in _SETTINGS_SECTIONS:
                settings_doc[key] = val
            elif key == "captcha" and isinstance(val, dict):
                api_key = val.get("api_key")
                settings_doc["captcha"] = {k: v for k, v in val.items() if k != "api_key"}
                if api_key:
                    cred_doc["captcha"] = {"api_key": api_key}
            elif key == "smtp" and isinstance(val, dict):
                password = val.get("password")
                settings_doc["smtp"] = {k: v for k, v in val.items() if k != "password"}
                if password:
                    cred_doc["smtp"] = {"password": password}
            elif key in _CREDENTIAL_KEYS:
                if val not in (None, ""):
                    cred_doc[key] = val
            else:
                # _PROFILE_SECTIONS plus any extra="allow" CV keys.
                profile_doc[key] = val

        def _dump(doc: dict[str, Any]) -> str:
            return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)

        paths = {
            "profile": d / "profile.yaml",
            "settings": d / "settings.yaml",
            "credentials": d / "credentials.yaml",
        }
        headers = {
            "profile": "# NexScout résumé — who you are. Tailored into every application.\n",
            "settings": "# NexScout settings — search / llm / apply / openclaw / captcha provider / smtp.\n",
            "credentials": "# NexScout secrets — plaintext. Keep private; never commit. ${env:NAME} also works here.\n",
        }
        docs = {"profile": profile_doc, "settings": settings_doc, "credentials": cred_doc}
        for name, target in paths.items():
            target.write_text(headers[name] + _dump(docs[name]), encoding="utf-8")
        return paths

    # ---- Helpers ----
    def to_resume_text(self) -> str:
        """Produce a minimal plain-text resume used by scorer/tailor."""
        me, exp, sk, facts = self.me, self.exp, self.skills, self.facts
        lines: list[str] = []
        lines.append(me.legal)
        if exp.current_title:
            lines.append(exp.current_title)
        contact = " | ".join(filter(None, [me.email, me.phone, me.links.gh, me.links.li]))
        if contact:
            lines.append(contact)
        lines.append("")
        lines.append("SUMMARY")
        target = ", ".join(exp.target_titles[:2]) if exp.target_titles else exp.current_title
        years = f"{exp.years}+ years" if exp.years else "experienced"
        lines.append(f"{years} engineer targeting {target}.")
        lines.append("")

        lines.append("TECHNICAL SKILLS")
        if sk.lang:
            lines.append(f"Languages: {', '.join(sk.lang)}")
        if sk.fw:
            lines.append(f"Frameworks: {', '.join(sk.fw)}")
        if sk.infra:
            lines.append(f"Infra: {', '.join(sk.infra)}")
        if sk.data:
            lines.append(f"Data: {', '.join(sk.data)}")
        if sk.tools:
            lines.append(f"Tools: {', '.join(sk.tools)}")
        lines.append("")

        lines.append("EXPERIENCE")
        for company in facts.companies:
            lines.append(company)
        lines.append("")

        lines.append("PROJECTS")
        for proj in facts.projects:
            lines.append(f"- {proj}")
        lines.append("")

        if facts.metrics:
            lines.append("HIGHLIGHTS")
            for m in facts.metrics:
                lines.append(f"- {m}")
            lines.append("")

        lines.append("EDUCATION")
        lines.append(f"{facts.school} | {exp.edu}".strip(" |"))
        return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# Forward migrations
# ---------------------------------------------------------------------------


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Forward-migrate raw profile dicts based on ``meta.v``.

    Currently a no-op; future schema bumps register here.
    """
    meta = raw.get("meta") or {}
    v = meta.get("v", 1)
    while v < CURRENT_SCHEMA_VERSION:
        # placeholder for future migrations
        v += 1
        meta["v"] = v
    raw["meta"] = meta
    return raw
