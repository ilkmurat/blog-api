from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=220)]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Term(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    slug: str


class TermWithCount(Term):
    post_count: int


class PostCreate(BaseModel):
    title: Annotated[NonEmpty, StringConstraints(max_length=200)]
    slug: Slug | None = None
    excerpt: Annotated[str, StringConstraints(max_length=500)] | None = None
    content: NonEmpty
    author: str = "Anonymous"
    category: Annotated[NonEmpty, StringConstraints(max_length=100)]
    tags: list[Annotated[NonEmpty, StringConstraints(max_length=60)]] = []
    published_at: datetime | None = None


class PostUpdate(BaseModel):
    title: Annotated[NonEmpty, StringConstraints(max_length=200)] | None = None
    slug: Slug | None = None
    excerpt: Annotated[str, StringConstraints(max_length=500)] | None = None
    content: NonEmpty | None = None
    author: str | None = None
    category: Annotated[NonEmpty, StringConstraints(max_length=100)] | None = None
    tags: list[Annotated[NonEmpty, StringConstraints(max_length=60)]] | None = None
    published_at: datetime | None = None


class PostSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    title: str
    excerpt: str
    author: str
    category: Term
    tags: list[Term]
    published_at: datetime
    reading_time: int
    like_count: int


class PostOut(PostSummary):
    content: str
    created_at: datetime
    updated_at: datetime
    liked_by_me: bool = False


class PostPage(BaseModel):
    items: list[PostSummary]
    total: int
    page: int
    page_size: int
    pages: int


class SearchHit(BaseModel):
    score: float
    post: PostSummary


class SearchResults(BaseModel):
    items: list[SearchHit]


class TermCreate(BaseModel):
    name: Annotated[NonEmpty, StringConstraints(max_length=100)]


class LikeResult(BaseModel):
    like_count: int
    liked_by_me: bool


# No format validation on user fields by design; only username/email uniqueness is enforced.
class UserCreate(BaseModel):
    username: str
    email: str
    first_name: str
    last_name: str
    password: str


class AdminUserCreate(UserCreate):
    is_admin: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    is_admin: bool
    created_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: Literal["ok", "error"]
    qdrant: Literal["ok", "error"]


class Error(BaseModel):
    detail: str
