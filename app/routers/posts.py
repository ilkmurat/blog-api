import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, Post, Tag
from app.schemas import Error, PostCreate, PostOut, PostPage, PostUpdate, SearchHit, SearchResults
from app.text import make_excerpt, slugify
from app.vectors import VectorStore, get_vector_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/posts", tags=["posts"])

NOT_FOUND = {404: {"model": Error}}
CONFLICT = {409: {"model": Error}}


def _get_post(db: Session, slug: str) -> Post:
    post = db.scalar(select(Post).where(Post.slug == slug))
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Post '{slug}' not found")
    return post


def _ensure_slug_free(db: Session, slug: str, exclude_id: int | None = None) -> None:
    query = select(Post.id).where(Post.slug == slug)
    if exclude_id is not None:
        query = query.where(Post.id != exclude_id)
    if db.scalar(query) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Slug '{slug}' is already in use")


def _get_or_create_category(db: Session, name: str) -> Category:
    slug = slugify(name)
    category = db.scalar(select(Category).where(Category.slug == slug))
    if category is None:
        category = Category(name=name, slug=slug)
        db.add(category)
    return category


def _get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    by_slug = {slugify(n): n for n in names if slugify(n)}
    existing = {t.slug: t for t in db.scalars(select(Tag).where(Tag.slug.in_(by_slug)))}
    tags = []
    for slug, name in by_slug.items():
        tag = existing.get(slug)
        if tag is None:
            tag = Tag(name=name, slug=slug)
            db.add(tag)
        tags.append(tag)
    return tags


def _index(vectors: VectorStore, post: Post) -> None:
    # Postgres is the source of truth; a failed index only makes search stale (fix with `python -m app.reindex`).
    try:
        vectors.upsert(post)
    except Exception:
        log.exception("Failed to index post %s in Qdrant", post.id)


@router.get("", response_model=PostPage)
def list_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    query = select(Post)
    if category:
        query = query.join(Post.category).where(Category.slug == category)
    if tag:
        query = query.where(Post.tags.any(Tag.slug == tag))
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(Post.title.ilike(pattern), Post.excerpt.ilike(pattern), Post.content.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Post.published_at.desc(), Post.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return PostPage(items=items, total=total, page=page, page_size=page_size, pages=max(1, math.ceil(total / page_size)))


@router.get("/search", response_model=SearchResults)
def search_posts(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    vectors: VectorStore = Depends(get_vector_store),
):
    hits = vectors.search(q, limit)
    posts = {p.id: p for p in db.scalars(select(Post).where(Post.id.in_([pid for pid, _ in hits])))}
    return SearchResults(items=[SearchHit(score=score, post=posts[pid]) for pid, score in hits if pid in posts])


@router.post("", response_model=PostOut, status_code=status.HTTP_201_CREATED, responses=CONFLICT)
def create_post(body: PostCreate, db: Session = Depends(get_db), vectors: VectorStore = Depends(get_vector_store)):
    slug = body.slug or slugify(body.title)
    if not slug:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cannot derive a slug from the title")
    _ensure_slug_free(db, slug)

    post = Post(
        slug=slug,
        title=body.title,
        excerpt=body.excerpt if body.excerpt is not None else make_excerpt(body.content),
        content=body.content,
        author=body.author,
        category=_get_or_create_category(db, body.category),
        tags=_get_or_create_tags(db, body.tags),
    )
    if body.published_at:
        post.published_at = body.published_at
    db.add(post)
    db.commit()
    db.refresh(post)
    _index(vectors, post)
    return post


@router.get("/{slug}", response_model=PostOut, responses=NOT_FOUND)
def get_post(slug: str, db: Session = Depends(get_db)):
    return _get_post(db, slug)


@router.patch("/{slug}", response_model=PostOut, responses={**NOT_FOUND, **CONFLICT})
def update_post(
    slug: str, body: PostUpdate, db: Session = Depends(get_db), vectors: VectorStore = Depends(get_vector_store)
):
    post = _get_post(db, slug)
    changes = body.model_dump(exclude_unset=True)

    if changes.get("slug") and changes["slug"] != post.slug:
        _ensure_slug_free(db, changes["slug"], exclude_id=post.id)
    if "category" in changes:
        post.category = _get_or_create_category(db, changes.pop("category"))
    if "tags" in changes:
        post.tags = _get_or_create_tags(db, changes.pop("tags"))
    for field, value in changes.items():
        if value is not None:
            setattr(post, field, value)

    db.commit()
    db.refresh(post)
    _index(vectors, post)
    return post


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
def delete_post(slug: str, db: Session = Depends(get_db), vectors: VectorStore = Depends(get_vector_store)):
    post = _get_post(db, slug)
    post_id = post.id
    db.delete(post)
    db.commit()
    try:
        vectors.delete(post_id)
    except Exception:
        log.exception("Failed to delete vector for post %s", post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
