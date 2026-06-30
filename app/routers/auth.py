from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session as DBSession

from ..config import get_settings
from ..database import get_db
from ..emailer import send_login_link
from ..schemas import LoginRequest, ProfileUpdate, UserOut
from ..security import (
    SESSION_COOKIE,
    consume_login_token,
    create_login_token,
    create_session,
    get_current_user,
    new_api_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/login")
def request_login(payload: LoginRequest, db: DBSession = Depends(get_db)) -> dict:
    """Send a one-time magic sign-in link to the given email.

    The desktop (Electron) app sends ``client="desktop"`` so the link is a
    ``meerato://`` deep link that completes sign-in inside the app window rather
    than the user's web browser (where the session cookie would otherwise land).
    """
    token = create_login_token(db, payload.email)
    if payload.client == "desktop":
        link = f"meerato://login?token={token}"
    else:
        link = f"{settings.base_url}/api/auth/callback?token={token}"
    send_login_link(payload.email, link)
    return {"ok": True, "message": "Check your email for a sign-in link."}


@router.get("/callback")
def login_callback(token: str, db: DBSession = Depends(get_db)) -> Response:
    """Consume a magic link, establish a session cookie, and redirect into the app."""
    user, redirect_todo_id = consume_login_token(db, token)
    session_token = create_session(db, user)

    target = "/"
    if redirect_todo_id:
        target = f"/?todo={redirect_todo_id}"
    resp = RedirectResponse(url=target, status_code=302)
    resp.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.base_url.startswith("https"),
    )
    return resp


@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)) -> UserOut:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: ProfileUpdate, db: DBSession = Depends(get_db), user=Depends(get_current_user)
) -> UserOut:
    data = payload.model_dump(exclude_unset=True)
    if "timezone" in data:
        try:
            ZoneInfo(data["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=422, detail="Unknown timezone")
        user.timezone = data["timezone"]
    if "name" in data:
        user.name = (data["name"] or "").strip() or None
    db.commit()
    db.refresh(user)
    return user


@router.post("/api-token", response_model=UserOut)
def ensure_api_token(
    db: DBSession = Depends(get_db), user=Depends(get_current_user)
) -> UserOut:
    """Create the user's external-API token if they don't have one yet."""
    if not user.api_token:
        user.api_token = new_api_token()
        db.commit()
        db.refresh(user)
    return user


@router.post("/api-token/rotate", response_model=UserOut)
def rotate_api_token(
    db: DBSession = Depends(get_db), user=Depends(get_current_user)
) -> UserOut:
    """Replace the API token (invalidates the old one)."""
    user.api_token = new_api_token()
    db.commit()
    db.refresh(user)
    return user


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}
