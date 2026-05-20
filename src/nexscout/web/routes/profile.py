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

    raw = yaml_mod.safe_load(yaml_text) or {}
    profile = Profile.model_validate(raw)
    profile.save()
    return RedirectResponse(url="/profile", status_code=303)


__all__ = ["router"]
