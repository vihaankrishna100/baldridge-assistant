from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

import audit
from config import settings
from database import get_db
from deps import current_user, require_leadership
from models import (
    VISIBILITIES,
    VISIBILITY_STAFF,
    Chunk,
    Document,
    User,
    visible_tiers_for_role,
)
from rag import redact
from rag.chunker import chunk_pages
from rag.extract import ExtractionError, extract
from rag.index import index
from schemas import DocumentOut, DocumentUpdate

router = APIRouter(prefix="/documents", tags=["documents"])


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    include_inactive: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tiers = visible_tiers_for_role(user.role)
    q = db.query(Document).filter(Document.visibility.in_(tiers))
    if not include_inactive or user.role == "staff":
        q = q.filter(Document.is_active.is_(True))
    docs = q.order_by(Document.category, Document.title).all()
    return [DocumentOut.model_validate(d) for d in docs]


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("General"),
    visibility: str = Form(VISIBILITY_STAFF),
    replaces: str = Form(""),
    user: User = Depends(require_leadership),
    db: Session = Depends(get_db),
):
    if visibility not in VISIBILITIES:
        raise HTTPException(status_code=400, detail="Unknown visibility level.")
    if visibility != VISIBILITY_STAFF and user.role not in ("leadership", "admin"):
        raise HTTPException(status_code=403, detail="You cannot publish leadership-only documents.")

    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"File is larger than the {settings.max_upload_mb} MB limit."
        )
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")

    try:
        pages = extract(data, file.filename or "upload", file.content_type or "")
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    full_text = "\n\n".join(text for _, text in pages)
    checksum = hashlib.sha256(data).hexdigest()

    duplicate = (
        db.query(Document)
        .filter(Document.checksum == checksum, Document.is_active.is_(True))
        .one_or_none()
    )
    if duplicate and not replaces:
        raise HTTPException(
            status_code=409,
            detail=f"This exact file is already in the library as “{duplicate.title}”.",
        )

    proto_chunks = chunk_pages(pages)
    if not proto_chunks:
        raise HTTPException(status_code=400, detail="Could not find any readable text in that file.")

    version = 1
    if replaces:
        previous = db.get(Document, replaces)
        if previous is None:
            raise HTTPException(status_code=404, detail="The document being replaced no longer exists.")
        previous.is_active = False
        previous.updated_at = _now()
        version = previous.version + 1
        audit.log(
            db, "document_superseded", user=user, target=previous.title,
            detail=f"replaced by v{version}", request=request, commit=False,
        )

    doc = Document(
        title=(title.strip() or (file.filename or "Untitled")),
        filename=file.filename or "upload",
        content_type=file.content_type or "",
        category=category.strip() or "General",
        visibility=visibility,
        version=version,
        checksum=checksum,
        size_bytes=len(data),
        char_count=len(full_text),
        chunk_count=len(proto_chunks),
        pii_flags=", ".join(redact.scan(full_text)),
        uploaded_by=user.id,
    )
    db.add(doc)
    db.flush()

    for proto in proto_chunks:
        db.add(
            Chunk(
                document_id=doc.id,
                ordinal=proto.ordinal,
                heading=proto.heading[:300],
                page=proto.page,
                text=proto.text,
            )
        )

    # Original file kept so leadership can download exactly what was approved.
    (settings.storage_path / f"{doc.id}").write_bytes(data)

    db.commit()
    index.rebuild(db)

    audit.log(
        db, "document_uploaded", user=user, target=doc.title,
        detail=f"{doc.chunk_count} chunks, visibility={doc.visibility}"
        + (f", PII review: {doc.pii_flags}" if doc.pii_flags else ""),
        request=request,
    )
    return DocumentOut.model_validate(doc)


@router.patch("/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: str,
    payload: DocumentUpdate,
    request: Request,
    user: User = Depends(require_leadership),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    changes = []
    if payload.title is not None and payload.title.strip():
        doc.title = payload.title.strip()
        changes.append("title")
    if payload.category is not None:
        doc.category = payload.category.strip() or "General"
        changes.append("category")
    if payload.visibility is not None:
        if payload.visibility not in VISIBILITIES:
            raise HTTPException(status_code=400, detail="Unknown visibility level.")
        doc.visibility = payload.visibility
        changes.append(f"visibility={payload.visibility}")
    if payload.is_active is not None:
        doc.is_active = payload.is_active
        changes.append("active" if payload.is_active else "retired")

    doc.updated_at = _now()
    db.commit()
    index.rebuild(db)
    audit.log(
        db, "document_updated", user=user, target=doc.title,
        detail=", ".join(changes), request=request,
    )
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    request: Request,
    user: User = Depends(require_leadership),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    title = doc.title

    stored = settings.storage_path / document_id
    if stored.exists():
        stored.unlink()

    db.delete(doc)  # chunks cascade
    db.commit()
    index.rebuild(db)
    audit.log(db, "document_deleted", user=user, target=title, request=request)
    return {"ok": True}


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.visibility not in visible_tiers_for_role(user.role):
        # Same 404 as a missing document — a 403 would confirm it exists.
        audit.log(db, "document_access_denied", user=user, target=doc.id, request=request)
        raise HTTPException(status_code=404, detail="Document not found.")

    path = settings.storage_path / document_id
    if not path.exists():
        raise HTTPException(status_code=410, detail="The original file is no longer stored.")

    audit.log(db, "document_downloaded", user=user, target=doc.title, request=request)
    return Response(
        content=path.read_bytes(),
        media_type=doc.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/reindex")
def reindex(
    request: Request,
    user: User = Depends(require_leadership),
    db: Session = Depends(get_db),
):
    count = index.rebuild(db)
    audit.log(db, "reindex", user=user, detail=f"{count} chunks", request=request)
    return {"ok": True, **index.stats()}
