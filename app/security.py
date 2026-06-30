"""Authentication: email magic links + opaque session tokens stored in a cookie."""

import secrets
import uuid
from datetime import timedelta

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from .config import get_settings
from .database import get_db
from .models import Bucket, LoginToken, Session, User, utcnow

DEFAULT_BUCKETS = ("Work", "Private")

settings = get_settings()
SESSION_COOKIE = "todo_session"


def new_id() -> str:
    return str(uuid.uuid4())


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_api_token() -> str:
    """Secret for the external create-task API. URL-safe, ~32 chars (fits VARCHAR(64))."""
    return secrets.token_urlsafe(24)


def get_user_by_api_token(db: DBSession, token: str | None) -> User | None:
    if not token:
        return None
    return db.query(User).filter(User.api_token == token).one_or_none()


def get_or_create_user(db: DBSession, email: str) -> User:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(id=new_id(), email=email)
        db.add(user)
        db.flush()
        # Seed a brand-new account with its default buckets.
        for position, name in enumerate(DEFAULT_BUCKETS):
            db.add(Bucket(id=new_id(), owner_id=user.id, name=name, position=position))
        db.flush()
    return user


def create_login_token(db: DBSession, email: str, redirect_todo_id: str | None = None) -> str:
    token = new_token()
    db.add(
        LoginToken(
            token=token,
            email=email.strip().lower(),
            expires_at=utcnow() + timedelta(minutes=settings.login_token_ttl_minutes),
            redirect_todo_id=redirect_todo_id,
        )
    )
    db.commit()
    return token


def consume_login_token(db: DBSession, token: str) -> tuple[User, str | None]:
    lt = db.query(LoginToken).filter(LoginToken.token == token).one_or_none()
    if lt is None or lt.expires_at < utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired login link")
    user = get_or_create_user(db, lt.email)
    db.commit()
    return user, lt.redirect_todo_id


def create_session(db: DBSession, user: User) -> str:
    token = new_token()
    db.add(
        Session(
            token=token,
            user_id=user.id,
            expires_at=utcnow() + timedelta(minutes=settings.session_ttl_minutes),
        )
    )
    db.commit()
    return token


def get_current_user(
    db: DBSession = Depends(get_db),
    todo_session: str | None = Cookie(default=None),
) -> User:
    user = _user_from_session(db, todo_session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user


def get_optional_user(
    db: DBSession = Depends(get_db),
    todo_session: str | None = Cookie(default=None),
) -> User | None:
    return _user_from_session(db, todo_session)


def _user_from_session(db: DBSession, token: str | None) -> User | None:
    if not token:
        return None
    sess = db.query(Session).filter(Session.token == token).one_or_none()
    if sess is None or sess.expires_at < utcnow():
        return None
    return db.get(User, sess.user_id)
