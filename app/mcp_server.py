"""MCP server exposing read-only blog tools (see contract/mcp-tools.md), mounted at /mcp."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.types import Receive, Scope, Send

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuthSession, Category, Post, PostLike, Tag, User, post_tags
from app.security import hash_token
from app.text import slugify
from app.vectors import get_vector_store

mcp = FastMCP(
    "inkwell-blog",
    instructions=(
        "Read-only tools for the Inkwell blog: posts, categories, tags, likes and aggregate user statistics. "
        "Tools prefixed with admin_ require an admin bearer token."
    ),
)


@dataclass(frozen=True)
class Caller:
    user_id: int | None = None
    username: str | None = None
    is_admin: bool = False


ANONYMOUS = Caller()


def _caller(ctx: Context) -> Caller:
    request = ctx.request_context.request
    header = request.headers.get("authorization", "") if request is not None else ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return ANONYMOUS
    with SessionLocal() as db:
        session = db.get(AuthSession, hash_token(token))
        if session is None or session.expires_at < datetime.now(timezone.utc):
            return ANONYMOUS
        return Caller(session.user.id, session.user.username, session.user.is_admin)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _post(p: Post) -> dict[str, Any]:
    return {
        "title": p.title,
        "slug": p.slug,
        "url": f"/post/{p.slug}",
        "category": p.category.name,
        "tags": [t.name for t in p.tags],
        "author": p.author,
        "published_at": p.published_at.date().isoformat(),
        "like_count": p.like_count,
        "excerpt": p.excerpt,
    }


def _find_term(db: Session, model: type[Category] | type[Tag], value: str) -> Category | Tag | None:
    return db.scalar(select(model).where(model.slug == slugify(value)))


def _available(db: Session, model: type[Category] | type[Tag]) -> list[str]:
    return list(db.scalars(select(model.name).order_by(model.name)))


async def _run(fn, *args):
    # Tools touch the database synchronously; keep the event loop free.
    return await anyio.to_thread.run_sync(fn, *args)


# --- public tools ---------------------------------------------------------------------------


def _list_posts(category: str | None, tag: str | None, limit: int) -> dict[str, Any]:
    with SessionLocal() as db:
        query = select(Post)
        if category:
            cat = _find_term(db, Category, category)
            if cat is None:
                return {"total": 0, "posts": [], "note": f"No category '{category}'.", "available": _available(db, Category)}
            query = query.where(Post.category_id == cat.id)
        if tag:
            t = _find_term(db, Tag, tag)
            if t is None:
                return {"total": 0, "posts": [], "note": f"No tag '{tag}'.", "available": _available(db, Tag)}
            query = query.where(Post.tags.any(Tag.id == t.id))
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        posts = db.scalars(query.order_by(Post.published_at.desc()).limit(_clamp(limit, 1, 50))).all()
        return {"total": total, "posts": [_post(p) for p in posts]}


@mcp.tool()
async def list_posts(category: str | None = None, tag: str | None = None, limit: int = 10) -> dict[str, Any]:
    """List blog posts, newest first. Filter by category and/or tag (name or slug). Returns the total match count."""
    return await _run(_list_posts, category, tag, limit)


def _top_liked(limit: int, category: str | None) -> dict[str, Any]:
    with SessionLocal() as db:
        query = select(Post)
        if category:
            cat = _find_term(db, Category, category)
            if cat is None:
                return {"posts": [], "note": f"No category '{category}'.", "available": _available(db, Category)}
            query = query.where(Post.category_id == cat.id)
        posts = db.scalars(query.order_by(Post.like_count.desc(), Post.published_at.desc()).limit(_clamp(limit, 1, 50)))
        return {"posts": [_post(p) for p in posts]}


@mcp.tool()
async def top_liked_posts(limit: int = 5, category: str | None = None) -> dict[str, Any]:
    """Most liked posts (highest like_count first), optionally within one category."""
    return await _run(_top_liked, limit, category)


def _search(query: str, limit: int) -> dict[str, Any]:
    hits = get_vector_store().search(query, _clamp(limit, 1, 20))
    with SessionLocal() as db:
        posts = {p.id: p for p in db.scalars(select(Post).where(Post.id.in_([pid for pid, _ in hits])))}
        return {"posts": [{**_post(posts[pid]), "score": round(score, 3)} for pid, score in hits if pid in posts]}


@mcp.tool()
async def search_posts(query: str, limit: int = 5) -> dict[str, Any]:
    """Semantic search: find posts about a topic even without exact keyword matches."""
    return await _run(_search, query, limit)


def _get_post(slug: str) -> dict[str, Any]:
    with SessionLocal() as db:
        post = db.scalar(select(Post).where(Post.slug == slug))
        if post is None:
            raise ValueError(f"No post with slug '{slug}'")
        content = post.content if len(post.content) <= 4000 else post.content[:4000] + "\n…(truncated)"
        return {**_post(post), "content": content}


@mcp.tool()
async def get_post(slug: str) -> dict[str, Any]:
    """Full post (Markdown content) by slug. Use list_posts or search_posts to find slugs."""
    return await _run(_get_post, slug)


def _terms(model: type[Category] | type[Tag]) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        if model is Category:
            count = func.count(Post.id)
            rows = db.execute(
                select(Category.name, Category.slug, count).outerjoin(Post).group_by(Category.id).order_by(count.desc())
            )
        else:
            count = func.count(post_tags.c.post_id)
            rows = db.execute(
                select(Tag.name, Tag.slug, count).outerjoin(post_tags).group_by(Tag.id).order_by(count.desc())
            )
        return [{"name": n, "slug": s, "post_count": c} for n, s, c in rows]


@mcp.tool()
async def list_categories() -> list[dict[str, Any]]:
    """All categories with their post counts."""
    return await _run(_terms, Category)


@mcp.tool()
async def list_tags() -> list[dict[str, Any]]:
    """All tags with their post counts."""
    return await _run(_terms, Tag)


def _site_stats() -> dict[str, Any]:
    with SessionLocal() as db:
        latest = db.scalar(select(Post).order_by(Post.published_at.desc()).limit(1))
        return {
            "posts": db.scalar(select(func.count(Post.id))),
            "categories": db.scalar(select(func.count(Category.id))),
            "tags": db.scalar(select(func.count(Tag.id))),
            "total_likes": db.scalar(select(func.coalesce(func.sum(Post.like_count), 0))),
            "users": db.scalar(select(func.count(User.id))),
            "latest_post": _post(latest) if latest else None,
        }


@mcp.tool()
async def site_stats() -> dict[str, Any]:
    """Overall numbers: posts, categories, tags, total likes, registered users, and the latest post."""
    return await _run(_site_stats)


def _user_stats(days: int) -> dict[str, Any]:
    days = _clamp(days, 1, 3650)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with SessionLocal() as db:
        return {
            "total_users": db.scalar(select(func.count(User.id))),
            "new_signups": db.scalar(select(func.count(User.id)).where(User.created_at >= since)),
            "users_logged_in": db.scalar(
                select(func.count(func.distinct(AuthSession.user_id))).where(AuthSession.created_at >= since)
            ),
            "period_days": days,
        }


@mcp.tool()
async def user_stats(days: int = 7) -> dict[str, Any]:
    """Aggregate user counts: total registered users, sign-ups and distinct users who logged in during the last N days.
    Counts only; never personal data."""
    return await _run(_user_stats, days)


# --- admin tools ----------------------------------------------------------------------------


def _admin_list_users(limit: int, days: int | None) -> dict[str, Any]:
    with SessionLocal() as db:
        likes = select(PostLike.user_id, func.count().label("n")).group_by(PostLike.user_id).subquery()
        last_login = (
            select(AuthSession.user_id, func.max(AuthSession.created_at).label("at"))
            .group_by(AuthSession.user_id)
            .subquery()
        )
        query = (
            select(User, func.coalesce(likes.c.n, 0), last_login.c.at)
            .outerjoin(likes, likes.c.user_id == User.id)
            .outerjoin(last_login, last_login.c.user_id == User.id)
            .order_by(User.created_at.desc())
        )
        if days:
            query = query.where(User.created_at >= datetime.now(timezone.utc) - timedelta(days=_clamp(days, 1, 3650)))
        rows = db.execute(query.limit(_clamp(limit, 1, 200))).all()
        return {
            "users": [
                {
                    "username": u.username,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "email": u.email,
                    "is_admin": u.is_admin,
                    "created_at": u.created_at.isoformat(timespec="minutes"),
                    "likes_given": n,
                    "last_login": at.isoformat(timespec="minutes") if at else None,
                }
                for u, n, at in rows
            ]
        }


@mcp.tool()
async def admin_list_users(ctx: Context, limit: int = 20, days: int | None = None) -> dict[str, Any]:
    """ADMIN ONLY. Registered users with name, email, role, sign-up date, likes given and last login.
    `days` limits to users who signed up in the last N days."""
    if not (await _run(_caller, ctx)).is_admin:
        raise PermissionError("admin_list_users requires an admin login")
    return await _run(_admin_list_users, limit, days)


# --- ASGI wiring ----------------------------------------------------------------------------


class MCPEndpoint:
    """ASGI app for /mcp. A fresh session manager per app lifespan (a manager can only run once)."""

    def __init__(self) -> None:
        self.manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def lifespan(self):
        settings = get_settings()
        self.manager = StreamableHTTPSessionManager(
            app=mcp._mcp_server,
            json_response=True,
            stateless=True,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=settings.mcp_allowed_hosts,
                allowed_origins=[],
            ),
        )
        async with self.manager.run():
            yield

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert self.manager is not None, "MCP endpoint used outside the app lifespan"
        await self.manager.handle_request(scope, receive, send)


mcp_endpoint = MCPEndpoint()
