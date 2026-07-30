from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import audit
import llm
from config import settings
from database import SessionLocal, get_db
from deps import current_user, enforce_rate_limit
from models import Conversation, Message, User, visible_tiers_for_role
from rag.index import Hit, index
from schemas import AskRequest

router = APIRouter(prefix="/chat", tags=["chat"])

# Questions that are asking the assistant about itself rather than about a
# policy. Logged, and answered with a canned description instead of retrieval.
META_PATTERNS = re.compile(
    r"(system prompt|your instructions|ignore (all |your )?(previous|prior) instructions"
    r"|reveal your|developer mode|jailbreak"
    # "print/repeat/output/show the entire document", "... every document verbatim"
    r"|(print|repeat|output|show|list|recite)\b[^?.]{0,40}\b(entire|full|all|every)\b"
    r"[^?.]{0,40}\b(document|documents|contents|corpus|files?|library)"
    r"|dump (the|all) (documents|database)|list (all )?(users|passwords)"
    r"|api key|admin mode)",
    re.I,
)

REASONS = {
    "no_documents": "There are no documents in the library yet for me to search.",
    "no_match": "I couldn't find anything in {org}'s documents that covers this.",
    "low_confidence": "I found some related material, but nothing that actually answers this.",
    "model_declined": "The documents I found don't clearly answer this.",
    "no_citations": "I couldn't point to a specific passage that supports an answer.",
    "safety_refusal": "I'm not able to answer this one.",
    "meta_query": "I can only answer questions about {org}'s internal documents.",
    "error": "Something went wrong on my end while looking this up.",
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _escalation_payload(reason: str) -> dict:
    headline = REASONS.get(reason, REASONS["error"]).format(org=settings.org_name)
    return {
        "escalated": True,
        "reason": reason,
        "headline": headline,
        "guidance": (
            "I'd rather send you to a person than give you something that might be "
            "wrong. " + settings.escalation_text()
        ),
        "org_name": settings.org_name,
        "phone": settings.org_phone,
        "email": settings.org_email,
        "contact_name": settings.org_fallback_contact_name,
    }


def _source_summary(hits: list[Hit]) -> list[dict]:
    return [
        {
            "n": i,
            "document_id": h.document_id,
            "document_title": h.document_title,
            "heading": h.heading,
            "page": h.page,
            "category": h.category,
            "score": h.score,
        }
        for i, h in enumerate(hits, start=1)
    ]


@router.post("/ask")
def ask(
    payload: AskRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(db, user)
    question = payload.question.strip()

    conversation = None
    if payload.conversation_id:
        conversation = db.get(Conversation, payload.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation is None:
        conversation = Conversation(user_id=user.id, title=question[:120])
        db.add(conversation)
        db.flush()

    db.add(Message(conversation_id=conversation.id, role="user", content=question))
    conversation.updated_at = _now()
    db.commit()
    conversation_id = conversation.id

    is_meta = bool(META_PATTERNS.search(question))
    if is_meta:
        audit.log(
            db, "meta_query_blocked", user=user,
            detail=question[:200], request=request,
        )

    hits: list[Hit] = []
    reason = ""
    if is_meta:
        reason = "meta_query"
    elif not index.stats()["chunks"]:
        reason = "no_documents"
    else:
        hits = index.search(question, visible_tiers_for_role(user.role))
        if not hits:
            reason = "no_match"
        elif hits[0].score < settings.retrieval_min_score:
            reason = "low_confidence"

    history = _history_for(db, conversation_id)
    user_id, user_email, user_role = user.id, user.email, user.role
    ip = audit.client_ip(request)
    top_score = hits[0].score if hits else 0.0

    def event_stream():
        # Fresh session: the request-scoped one closes when the response starts
        # streaming, and this generator outlives it.
        session = SessionLocal()
        try:
            yield _sse(
                "meta",
                {
                    "conversation_id": conversation_id,
                    "sources": _source_summary(hits),
                    "top_score": top_score,
                },
            )

            if reason:
                yield from _finish_escalated(
                    session, conversation_id, reason, user_id, user_email, ip, question
                )
                return

            result = None
            try:
                for kind, value in llm.stream_answer(question, hits, history):
                    if kind == "delta":
                        yield _sse("delta", {"text": value})
                    else:
                        result = value
            except Exception as exc:  # noqa: BLE001 - never leak a stack trace
                _log(session, "ask_error", user_id, user_email, ip, detail=type(exc).__name__)
                yield from _finish_escalated(
                    session, conversation_id, "error", user_id, user_email, ip, question
                )
                return

            if result is None or result.escalated:
                why = result.escalation_reason if result else "error"
                yield from _finish_escalated(
                    session, conversation_id, why, user_id, user_email, ip, question,
                    input_tokens=result.input_tokens if result else 0,
                    output_tokens=result.output_tokens if result else 0,
                )
                return

            session.add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=result.text,
                    answered=True,
                    escalated=False,
                    citations_json=json.dumps(result.citations),
                    top_score=top_score,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
            )
            session.commit()
            _log(
                session, "question_answered", user_id, user_email, ip,
                detail=f"{len(result.citations)} citations, score={top_score}",
                target=question[:200],
            )
            yield _sse(
                "done",
                {
                    "escalated": False,
                    "citations": result.citations,
                    "conversation_id": conversation_id,
                    "text": result.text,
                },
            )
        finally:
            session.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _finish_escalated(
    session: Session,
    conversation_id: str,
    reason: str,
    user_id: str,
    user_email: str,
    ip: str,
    question: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
):
    payload = _escalation_payload(reason)
    body = f"{payload['headline']}\n\n{payload['guidance']}"
    session.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=body,
            answered=False,
            escalated=True,
            escalation_reason=reason,
            citations_json="[]",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )
    session.commit()
    _log(
        session, "question_escalated", user_id, user_email, ip,
        detail=f"reason={reason}", target=question[:200],
    )
    yield _sse("done", {**payload, "conversation_id": conversation_id, "text": body})


def _log(session, action, user_id, user_email, ip, detail="", target=""):
    from models import AuditLog

    session.add(
        AuditLog(
            user_id=user_id, user_email=user_email, action=action,
            target=target[:300], detail=detail[:2000], ip=ip,
        )
    )
    session.commit()


def _history_for(db: Session, conversation_id: str) -> list[dict]:
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
    turns = []
    # Drop the question we just stored — it is sent separately with its sources.
    for msg in rows[:-1]:
        if msg.role == "assistant" and msg.escalated:
            continue  # escalations carry no grounded content worth replaying
        turns.append({"role": msg.role, "content": msg.content})
    return turns[-6:]


@router.get("/conversations")
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )
    return [
        {"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in rows
    ]


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "escalated": m.escalated,
                "escalation_reason": m.escalation_reason,
                "citations": json.loads(m.citations_json or "[]"),
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(conversation)
    db.commit()
    audit.log(db, "conversation_deleted", user=user, target=conversation_id, request=request)
    return {"ok": True}
