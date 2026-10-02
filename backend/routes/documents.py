from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

import audit
from blobs import get_blobs
from config import settings
from deps import current_user, require_leadership
from models import VISIBILITIES, VISIBILITY_STAFF, visible_tiers_for_role
from rag import redact
from rag.chunker import chunk_pages
from rag.extract import ExtractionError, extract
from rag.index import index
from repo import get_repo
from repo.base import ChunkRecord, DocumentRecord, UserRecord, utcnow
from schemas import DocumentOut, DocumentUpdate

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def list_documents(
    include_inactive: bool = False,
    user: UserRecord = Depends(current_user),
):
    tiers = visible_tiers_for_role(user.role)
    show_retired = include_inactive and user.role != "staff"
    docs = [
        d
        for d in get_repo().list_documents(include_inactive=show_retired)
        if d.visibility in tiers
    ]
    return [DocumentOut.model_validate(d) for d in docs]


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("General"),
    visibility: str = Form(VISIBILITY_STAFF),
    replaces: str = Form(""),
    user: UserRecord = Depends(require_leadership),
):
    store = get_repo()

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

    duplicate = store.find_active_document_by_checksum(checksum)
    if duplicate and not replaces:
        raise HTTPException(
            status_code=409,
            detail=f"This exact file is already in the library as “{duplicate.title}”.",
        )

    proto_chunks = chunk_pages(pages)
    if not proto_chunks:
        raise HTTPException(status_code=400, detail="Could not find any readable text in that file.")

    version = 1
    previous = None
    if replaces:
        previous = store.get_document(replaces)
        if previous is None:
            raise HTTPException(status_code=404, detail="The document being replaced no longer exists.")
        version = previous.version + 1

    doc = DocumentRecord(
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

    chunks = [
        ChunkRecord(
            document_id=doc.id,
            ordinal=p.ordinal,
            heading=p.heading[:300],
            page=p.page,
            text=p.text,
            document_title=doc.title,
            category=doc.category,
            visibility=doc.visibility,
            document_active=True,
        )
        for p in proto_chunks
    ]

    # Record before bytes: Postgres keys document_blobs to documents(id).
    store.create_document(doc, chunks)
    try:
        # Original kept so leadership can download exactly what was approved.
        get_blobs().put(doc.id, data)
    except Exception:
        store.delete_document(doc.id)
        raise

    # Retired only once the new version is fully stored, so a failed upload
    # never leaves the policy missing from search.
    if previous is not None:
        previous.is_active = False
        previous.updated_at = utcnow()
        store.update_document(previous)
        audit.log(
            "document_superseded", user=user, target=previous.title,
            detail=f"replaced by v{version}", request=request,
        )
    index.rebuild()

    audit.log(
        "document_uploaded", user=user, target=doc.title,
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
    user: UserRecord = Depends(require_leadership),
):
    store = get_repo()
    doc = store.get_document(document_id)
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

    doc.updated_at = utcnow()
    store.update_document(doc)
    index.rebuild()
    audit.log(
        "document_updated", user=user, target=doc.title,
        detail=", ".join(changes), request=request,
    )
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    request: Request,
    user: UserRecord = Depends(require_leadership),
):
    store = get_repo()
    doc = store.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    title = doc.title

    get_blobs().delete(document_id)
    store.delete_document(document_id)
    index.rebuild()
    audit.log("document_deleted", user=user, target=title, request=request)
    return {"ok": True}


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    request: Request,
    user: UserRecord = Depends(current_user),
):
    doc = get_repo().get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.visibility not in visible_tiers_for_role(user.role):
        # Same 404 as a missing document — a 403 would confirm it exists.
        audit.log("document_access_denied", user=user, target=doc.id, request=request)
        raise HTTPException(status_code=404, detail="Document not found.")

    data = get_blobs().get(document_id)
    if data is None:
        raise HTTPException(status_code=410, detail="The original file is no longer stored.")

    audit.log("document_downloaded", user=user, target=doc.title, request=request)
    return Response(
        content=data,
        media_type=doc.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/reindex")
def reindex(request: Request, user: UserRecord = Depends(require_leadership)):
    count = index.rebuild()
    audit.log("reindex", user=user, detail=f"{count} chunks", request=request)
    return {"ok": True, **index.stats()}
