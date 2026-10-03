from __future__ import annotations

import hashlib
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

import audit
from config import settings
from deps import current_user, require_leadership
from docstore import DocumentMissing, DuplicateDocument, GitHubDocStore, get_docstore
from models import VISIBILITIES, VISIBILITY_STAFF, visible_tiers_for_role
from rag import redact
from rag.chunker import chunk_pages
from rag.extract import ExtractionError, extract
from rag.index import index
from repo import get_repo
from repo.base import ChunkRecord, DocumentRecord, UserRecord, utcnow
from schemas import DocumentOut, DocumentUpdate

router = APIRouter(prefix="/documents", tags=["documents"])


def _attachment(filename: str) -> str:
    """Content-Disposition for any filename. HTTP headers are latin-1, so an
    accented letter or a long dash in the raw name would crash the download;
    the plain fallback is ASCII-only and the real name rides in filename*."""
    fallback = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename) or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _chunks_for(doc: DocumentRecord, proto_chunks) -> list[ChunkRecord]:
    return [
        ChunkRecord(
            document_id=doc.id,
            ordinal=p.ordinal,
            heading=p.heading[:300],
            page=p.page,
            text=p.text,
            document_title=doc.title,
            category=doc.category,
            visibility=doc.visibility,
            document_active=doc.is_active,
        )
        for p in proto_chunks
    ]


@router.get("", response_model=list[DocumentOut])
def list_documents(
    include_inactive: bool = False,
    user: UserRecord = Depends(current_user),
):
    tiers = visible_tiers_for_role(user.role)
    show_retired = include_inactive and user.role != "staff"
    docs = [
        d
        for d in get_docstore().list_documents(include_inactive=show_retired)
        if d.visibility in tiers
    ]
    return [DocumentOut.model_validate(d) for d in docs]


@router.get("/storage")
def storage(_: UserRecord = Depends(require_leadership)):
    """How full the database is, for whoever uploads documents. None when the
    store cannot measure itself (SQLite, Firestore)."""
    store = get_repo()
    if not hasattr(store, "storage_bytes"):
        return None
    return {
        "used_bytes": store.storage_bytes(),
        "limit_bytes": settings.storage_limit_mb * 1024 * 1024,
        "breakdown": store.storage_breakdown(),
        "files_in_github": isinstance(get_docstore(), GitHubDocStore),
    }


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
    docs = get_docstore()

    if visibility not in VISIBILITIES:
        raise HTTPException(status_code=400, detail="Unknown visibility level.")
    if visibility != VISIBILITY_STAFF and user.role not in ("leadership", "admin"):
        raise HTTPException(status_code=403, detail="You cannot publish leadership-only documents.")

    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Files must be under {settings.max_upload_mb:g} MB. Compress the PDF "
                "or split it into parts, then upload again."
            ),
        )
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")

    try:
        pages = extract(data, file.filename or "upload", file.content_type or "")
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    full_text = "\n\n".join(text for _, text in pages)
    checksum = hashlib.sha256(data).hexdigest()

    duplicate = docs.find_active_by_checksum(checksum)
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
        previous = docs.get_document(replaces)
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

    # Original kept so leadership can download exactly what was approved.
    try:
        docs.publish(doc, data, _chunks_for(doc, proto_chunks), previous)
    except DuplicateDocument as exc:
        raise HTTPException(
            status_code=409,
            detail=f"This exact file is already in the library as “{exc.existing.title}”.",
        ) from exc
    except DocumentMissing as exc:
        raise HTTPException(status_code=404, detail="The document being replaced no longer exists.") from exc

    if previous is not None:
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
    docs = get_docstore()
    doc = docs.get_document(document_id)
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
    try:
        docs.update(doc)
    except DocumentMissing as exc:
        raise HTTPException(status_code=404, detail="Document not found.") from exc
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
    docs = get_docstore()
    doc = docs.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    title = doc.title

    docs.delete(doc)
    index.rebuild()
    audit.log("document_deleted", user=user, target=title, request=request)
    return {"ok": True}


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    request: Request,
    user: UserRecord = Depends(current_user),
):
    docs = get_docstore()
    doc = docs.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.visibility not in visible_tiers_for_role(user.role):
        # Same 404 as a missing document — a 403 would confirm it exists.
        audit.log("document_access_denied", user=user, target=doc.id, request=request)
        raise HTTPException(status_code=404, detail="Document not found.")

    data = docs.get_bytes(doc)
    if data is None:
        raise HTTPException(status_code=410, detail="The original file is no longer stored.")

    audit.log("document_downloaded", user=user, target=doc.title, request=request)
    return Response(
        content=data,
        media_type=doc.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": _attachment(doc.filename),
            "Cache-Control": "no-store",
        },
    )


def _resync_search_copy(docs: GitHubDocStore) -> None:
    """Makes the database's passages match GitHub: re-extracts any document
    the search copy is missing, refreshes title/visibility/active on the rest,
    and drops passages for documents GitHub no longer has."""
    store = docs._search_copy()
    indexed = store.chunk_document_ids()
    library = docs.list_documents(include_inactive=True)
    for doc in library:
        if doc.id in indexed:
            store.set_chunks_meta(doc.id, doc.title, doc.category, doc.visibility, doc.is_active)
            continue
        data = docs.get_bytes(doc)
        if data is None:
            continue
        pages = extract(data, doc.filename, doc.content_type)
        store.put_chunks(doc.id, _chunks_for(doc, chunk_pages(pages)))
    for orphan in indexed - {d.id for d in library}:
        store.delete_chunks(orphan)


@router.post("/reindex")
def reindex(request: Request, user: UserRecord = Depends(require_leadership)):
    docs = get_docstore()
    if isinstance(docs, GitHubDocStore):
        _resync_search_copy(docs)
    count = index.rebuild()
    audit.log("reindex", user=user, detail=f"{count} chunks", request=request)
    return {"ok": True, **index.stats()}
