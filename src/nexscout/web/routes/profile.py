"""Profile edit form."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...core.errors import ConfigError
from ...core.profile import CURRENT_SCHEMA_VERSION, Profile

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
async def show_profile(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    try:
        profile = Profile.from_path()
        yaml_text = profile.to_yaml()
        meta_v = profile.meta.v
        error = None
    except ConfigError as e:
        yaml_text = ""
        meta_v = 0
        error = str(e)
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "yaml_text": yaml_text,
            "meta_v": meta_v,
            "current_v": CURRENT_SCHEMA_VERSION,
            "error": error,
        },
    )


@router.post("/profile")
async def save_profile(yaml_text: str = Form(...)) -> RedirectResponse:
    import yaml as yaml_mod

    from ...core.config import credentials_path, settings_path

    raw = yaml_mod.safe_load(yaml_text) or {}
    profile = Profile.model_validate(raw)
    # Preserve the on-disk layout: if the user has split sidecars, re-split on
    # save (so edits don't get shadowed by a stale settings/credentials file);
    # otherwise keep the single monolithic profile.yaml.
    if settings_path().exists() or credentials_path().exists():
        profile.save_split()
    else:
        profile.save()
    return RedirectResponse(url="/profile", status_code=303)


@router.get("/profile/migrate")
async def migrate_profile() -> RedirectResponse:
    """Bump the profile's ``meta.v`` to the current schema version.

    The template surfaces a "Migrate" button when ``meta.v`` is older
    than :data:`CURRENT_SCHEMA_VERSION`. The actual migration logic
    lives in :func:`nexscout.core.profile._migrate`; loading + saving
    here re-runs it.
    """
    try:
        profile = Profile.from_path()
    except ConfigError:
        return RedirectResponse(url="/profile", status_code=303)
    profile.meta.v = CURRENT_SCHEMA_VERSION
    profile.save()
    return RedirectResponse(url="/profile", status_code=303)


__all__ = ["router"]
