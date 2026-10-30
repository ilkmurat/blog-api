from pathlib import PurePath

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.db import get_db
from app.hr import get_hr_store, process_document
from app.models import HrDocument, User
from app.schemas import Error, HrDocumentOut

router = APIRouter(prefix="/api/v1/hr/documents", tags=["hr"], dependencies=[Depends(require_admin)])

ADMIN = {401: {"model": Error}, 403: {"model": Error}}


def _get(db: Session, document_id: int) -> HrDocument:
    doc = db.get(HrDocument, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"HR document {document_id} not found")
    return doc


@router.get("", response_model=list[HrDocumentOut], responses=ADMIN)
def list_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(HrDocument).order_by(HrDocument.created_at.desc(), HrDocument.id.desc()))
    return [HrDocumentOut.of(d) for d in docs]


@router.post(
    "",
    response_model=HrDocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**ADMIN, 413: {"model": Error}, 415: {"model": Error}},
)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None, max_length=200),
    topic: str | None = Form(None, max_length=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    limit = get_settings().hr_max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File is larger than {limit // 1024 // 1024} MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are supported")

    filename = PurePath(file.filename or "document.pdf").name
    doc = HrDocument(
        title=(title or "").strip() or PurePath(filename).stem,
        topic=(topic or "").strip() or "Genel",
        filename=filename,
        size_bytes=len(data),
        uploaded_by_id=admin.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    background.add_task(process_document, doc.id, data)
    return HrDocumentOut.of(doc)


@router.get("/{document_id}", response_model=HrDocumentOut, responses={**ADMIN, 404: {"model": Error}})
def get_document(document_id: int, db: Session = Depends(get_db)):
    return HrDocumentOut.of(_get(db, document_id))


@router.delete(
    "/{document_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ADMIN, 404: {"model": Error}}
)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = _get(db, document_id)
    get_hr_store().delete_document(doc.id)  # vectors first: a failure here leaves the row for a retry
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
