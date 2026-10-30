from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import Category, Post, Tag, post_tags
from app.schemas import Error, TermCreate, TermWithCount
from app.text import slugify

router = APIRouter(prefix="/api/v1", tags=["taxonomy"])

ADMIN_WRITE = {401: {"model": Error}, 403: {"model": Error}, 409: {"model": Error}}


def _create_term(db: Session, model: type[Category] | type[Tag], name: str) -> TermWithCount:
    slug = slugify(name)
    if not slug:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cannot derive a slug from the name")
    if db.scalar(select(model.id).where(model.slug == slug)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{name}' already exists")
    db.add(model(name=name, slug=slug))
    db.commit()
    return TermWithCount(name=name, slug=slug, post_count=0)


@router.get("/categories", response_model=list[TermWithCount])
def list_categories(db: Session = Depends(get_db)):
    count = func.count(Post.id)
    rows = db.execute(
        select(Category.name, Category.slug, count.label("post_count"))
        .outerjoin(Post, Post.category_id == Category.id)
        .group_by(Category.id)
        .order_by(count.desc(), Category.name)
    )
    return [TermWithCount(**row._mapping) for row in rows]


@router.get("/tags", response_model=list[TermWithCount])
def list_tags(db: Session = Depends(get_db)):
    count = func.count(post_tags.c.post_id)
    rows = db.execute(
        select(Tag.name, Tag.slug, count.label("post_count"))
        .outerjoin(post_tags, post_tags.c.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(count.desc(), Tag.name)
    )
    return [TermWithCount(**row._mapping) for row in rows]


@router.post(
    "/categories",
    response_model=TermWithCount,
    status_code=status.HTTP_201_CREATED,
    responses=ADMIN_WRITE,
    dependencies=[Depends(require_admin)],
)
def create_category(body: TermCreate, db: Session = Depends(get_db)):
    return _create_term(db, Category, body.name)


@router.post(
    "/tags",
    response_model=TermWithCount,
    status_code=status.HTTP_201_CREATED,
    responses=ADMIN_WRITE,
    dependencies=[Depends(require_admin)],
)
def create_tag(body: TermCreate, db: Session = Depends(get_db)):
    return _create_term(db, Tag, body.name)
