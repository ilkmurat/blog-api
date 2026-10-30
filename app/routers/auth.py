from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import bearer, create_user, require_admin, require_user, start_session
from app.db import get_db
from app.models import AuthSession, User
from app.schemas import AdminUserCreate, AuthResponse, Error, LoginRequest, UserCreate, UserOut
from app.security import hash_token, verify_password

router = APIRouter(prefix="/api/v1", tags=["auth & users"])

UNAUTHORIZED = {401: {"model": Error}}
ADMIN = {401: {"model": Error}, 403: {"model": Error}}
CONFLICT = {409: {"model": Error}}


@router.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED, responses=CONFLICT)
def register(body: UserCreate, db: Session = Depends(get_db)):
    user = create_user(db, body)
    return AuthResponse(token=start_session(db, user), user=user)


@router.post("/auth/login", response_model=AuthResponse, responses=UNAUTHORIZED)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return AuthResponse(token=start_session(db, user), user=user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, responses=UNAUTHORIZED)
def logout(
    _: User = Depends(require_user),
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(creds.credentials)))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=UserOut, responses=UNAUTHORIZED)
def me(user: User = Depends(require_user)):
    return user


@router.get("/users", response_model=list[UserOut], responses=ADMIN, dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())).all()


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={**ADMIN, **CONFLICT},
    dependencies=[Depends(require_admin)],
)
def admin_create_user(body: AdminUserCreate, db: Session = Depends(get_db)):
    return create_user(db, body, is_admin=body.is_admin)
