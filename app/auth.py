from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AuthSession, User
from app.schemas import UserCreate
from app.security import hash_password, hash_token, new_token

bearer = HTTPBearer(auto_error=False)


def current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User | None:
    """The logged-in user, or None for anonymous callers. A token that is present but invalid is a 401."""
    if creds is None:
        return None
    session = db.get(AuthSession, hash_token(creds.credentials))
    if session is None or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return session.user


def require_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def create_user(db: Session, body: UserCreate, is_admin: bool = False) -> User:
    taken = db.scalars(select(User).where(or_(User.username == body.username, User.email == body.email))).all()
    if any(u.username == body.username for u in taken):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Username '{body.username}' is already taken")
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Email '{body.email}' is already registered")
    user = User(
        username=body.username,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        password_hash=hash_password(body.password),
        is_admin=is_admin,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # lost a race with a concurrent signup
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email is already in use")
    db.refresh(user)
    return user


def start_session(db: Session, user: User) -> str:
    token = new_token()
    expires = datetime.now(timezone.utc) + timedelta(days=get_settings().session_days)
    db.add(AuthSession(token_hash=hash_token(token), user_id=user.id, expires_at=expires))
    db.commit()
    return token


def ensure_admin(db: Session) -> None:
    settings = get_settings()
    if db.scalar(select(User).where(User.username == settings.admin_username)) is None:
        db.add(
            User(
                username=settings.admin_username,
                email=f"{settings.admin_username}@admin.local",
                first_name="Admin",
                last_name="",
                password_hash=hash_password(settings.admin_password),
                is_admin=True,
            )
        )
        db.commit()
