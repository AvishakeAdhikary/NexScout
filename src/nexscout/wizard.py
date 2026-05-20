"""Interactive ``nexscout init`` wizard.

Walks the user through the YAML schema in §3 and writes
``~/.nexscout/profile.yaml``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from rich.prompt import Confirm, IntPrompt, Prompt

from .core.config import ensure_dirs, profile_path
from .core.logging import console
from .core.profile import (
    Auth,
    Avail,
    BoardsCfg,
    CaptchaConfig,
    Exp,
    Facts,
    Links,
    LLMConfig,
    Me,
    Meta,
    Pay,
    Profile,
    SearchConfig,
    SearchLocation,
    SearchQuery,
    Skills,
)


def _split_csv(s: str) -> list[str]:
    return [p.strip() for p in s.split(",") if p.strip()]


def run_wizard(out_path: Path | None = None, force: bool = False) -> Path:
    """Run the interactive wizard and write the profile YAML.

    Returns the path written.
    """
    ensure_dirs()
    target = out_path or profile_path()
    c = console()

    if (
        target.exists()
        and not force
        and not Confirm.ask(f"[yellow]{target} exists. Overwrite?[/yellow]", default=False)
    ):
        c.print("[dim]Aborted.[/dim]")
        return target

    c.rule("[bold cyan]NexScout — profile wizard[/bold cyan]")

    legal = Prompt.ask("Legal name", default="Jane Q. Public")
    pref = Prompt.ask("Preferred name", default=legal.split()[0])
    email = Prompt.ask("Email", default="jane@example.com")
    phone = Prompt.ask("Phone", default="+1-415-555-0100")
    city = Prompt.ask("City", default="San Francisco")
    region = Prompt.ask("State/Region", default="CA")
    country = Prompt.ask("Country", default="USA")
    postcode = Prompt.ask("Postcode", default="94110")

    li = Prompt.ask("LinkedIn (linkedin.com/in/...)", default="")
    gh = Prompt.ask("GitHub (github.com/...)", default="")
    web = Prompt.ask("Personal site", default="")

    authorized = Confirm.ask("Authorized to work in target country?", default=True)
    sponsor = Confirm.ask("Need sponsorship?", default=False)
    permit = Prompt.ask("Work permit (USC|PR|H1B|OWP|TN|OTHER)", default="USC")

    expect = IntPrompt.ask("Salary expectation (annual)", default=165000)
    pay_min = IntPrompt.ask("Salary range min", default=int(expect * 0.9))
    pay_max = IntPrompt.ask("Salary range max", default=int(expect * 1.2))
    currency = Prompt.ask("Currency", default="USD")

    years = IntPrompt.ask("Years of experience", default=7)
    edu = Prompt.ask("Education (degree)", default="BSc Computer Science")
    current_title = Prompt.ask("Current title", default="Senior Software Engineer")
    target_titles = _split_csv(
        Prompt.ask("Target titles (comma-separated)", default="Staff Engineer, Senior Backend Engineer")
    )

    languages = _split_csv(Prompt.ask("Languages (comma-separated)", default="Python, TypeScript, Go, SQL"))
    frameworks = _split_csv(Prompt.ask("Frameworks", default="FastAPI, React, Django"))
    infra = _split_csv(Prompt.ask("Infra", default="Docker, Kubernetes, AWS, Terraform"))
    data = _split_csv(Prompt.ask("Data", default="Postgres, Redis, Kafka"))
    tools = _split_csv(Prompt.ask("Tools", default="Git, Linux, Vim"))

    companies = _split_csv(Prompt.ask("Past companies", default="Acme Corp, Globex"))
    projects = _split_csv(Prompt.ask("Notable projects", default="Search Indexer, Auth Gateway"))
    school = Prompt.ask("School", default="State University")
    metrics = _split_csv(Prompt.ask("Metrics", default="reduced p99 by 38%, 10M MAU"))

    captcha_provider = Prompt.ask("Captcha provider", default="capsolver")

    profile = Profile(
        meta=Meta(v=1, locale="en_US", updated=date.today()),
        me=Me(
            legal=legal,
            pref=pref,
            email=email,
            phone=phone,
            city=city,
            region=region,
            country=country,
            postcode=postcode,
            links=Links(li=li, gh=gh, web=web),
        ),
        auth=Auth(authorized=authorized, sponsor=sponsor, permit=permit),
        pay=Pay(expect=expect, range=[pay_min, pay_max], currency=currency),
        avail=Avail(),
        exp=Exp(years=years, edu=edu, current_title=current_title, target_titles=target_titles),
        skills=Skills(lang=languages, fw=frameworks, infra=infra, data=data, tools=tools),
        facts=Facts(companies=companies, projects=projects, school=school, metrics=metrics),
        search=SearchConfig(
            queries=[SearchQuery(q=t, tier=1) for t in target_titles[:3]] or [SearchQuery(q=current_title, tier=1)],
            locations=[
                SearchLocation(label="Local", q=f"{city}, {region}", remote=False),
                SearchLocation(label="Remote", q="Remote", remote=True),
            ],
            boards=BoardsCfg(),
        ),
        llm=LLMConfig(),
        captcha=CaptchaConfig(provider=captcha_provider, api_key="${env:CAPTCHA_API_KEY}"),
    )

    profile.save(target)
    c.print(f"[green]Wrote profile to {target}[/green]")
    return target
