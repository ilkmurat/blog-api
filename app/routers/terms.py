from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, Post, Tag, post_tags
from app.schemas import TermWithCount

router = APIRouter(prefix="/api/v1", tags=["taxonomy"])


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
