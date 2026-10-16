"""Auth endpoints. Session token is an httpOnly cookie; CSRF token is returned to the client."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from nexscout.api.deps import CurrentActor, DbSession, SettingsDep, client_ip
from nexscout.api.schemas import LoginRequest, RegisterRequest, SessionOut, UserOut
from nexscout.application import auth
from nexscout.config import Settings
from nexscout.domain.errors import AuthenticationFailed
from nexscout.infrastructure.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(
    response: Response, settings: Settings, issued: auth.IssuedSession
) -> None:
    max_age = settings.session_absolute_days * 86400
    response.set_cookie(
        settings.session_cookie_name,
        issued.token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    # Readable by JS so the client can echo it in the CSRF header (double-submit).
    response.set_cookie(
        settings.csrf_cookie_name,
        issued.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=SessionOut)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
) -> SessionOut:
    ip = client_ip(request)
    user = await auth.register_user(
        db, email=body.email, password=body.password, display_name=body.display_name, ip=ip
    )
    issued = await auth.login(
        db,
        settings,
        email=user.email,
        password=body.password,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(response, settings, issued)
    return SessionOut(
        user=UserOut.model_validate(user),
        csrf_token=issued.csrf_token,
        expires_at=issued.expires_at,
    )


@router.post("/login", response_model=SessionOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
) -> SessionOut:
    try:
        issued = await auth.login(
            db,
            settings,
            email=body.email,
            password=body.password,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthenticationFailed:
        # Persist the failed-attempt record (rate limiting + audit) before returning 401.
        await db.commit()
        raise
    user = await db.get(User, issued.user_id)
    _set_session_cookies(response, settings, issued)
    return SessionOut(
        user=UserOut.model_validate(user),
        csrf_token=issued.csrf_token,
        expires_at=issued.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(actor: CurrentActor, db: DbSession, settings: SettingsDep) -> Response:
    await auth.logout(db, actor)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return response


@router.get("/me", response_model=UserOut)
async def me(actor: CurrentActor, db: DbSession) -> UserOut:
    return UserOut.model_validate(await auth.get_user(db, actor))
