from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

import audit
import llm
from config import settings
from deps import current_user, enforce_rate_limit
from models import visible_tiers_for_role
from rag.index import Hit, index
from repo.base import AuditEntry, UserRecord
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


def _log(action: str, user_id: str, user_email: str, ip: str, detail: str = "", target: str = "") -> None:
    """Audit from inside the response generator.

    The request-scoped `user` object isn't carried into the stream, so the few
    identity fields it needs are passed as plain strings.
    """
    audit.submit(
        AuditEntry(
            user_id=user_id, user_email=user_email, action=action,
            target=target[:300], detail=detail[:2000], ip=ip,
        )
    )


def _finish_escalated(reason: str, user_id: str, user_email: str, ip: str, question: str):
    payload = _escalation_payload(reason)
    body = f"{payload['headline']}\n\n{payload['guidance']}"
    _log("question_escalated", user_id, user_email, ip,
         detail=f"reason={reason}", target=question[:200])
    yield _sse("done", {**payload, "text": body})


@router.post("/ask")
def ask(
    payload: AskRequest,
    request: Request,
    user: UserRecord = Depends(current_user),
):
    enforce_rate_limit(user)
    question = payload.question.strip()
    # Session-only: the browser resends the conversation so far; nothing is
    # stored. Blank turns are escalations, which carry nothing worth replaying.
    history = [t.model_dump() for t in payload.history if t.content.strip()]

    is_meta = bool(META_PATTERNS.search(question))
    if is_meta:
        audit.log("meta_query_blocked", user=user, detail=question[:200], request=request)

    hits: list[Hit] = []
    reason = ""
    if is_meta:
        reason = "meta_query"
    elif not index.wait_ready(timeout=90) or not index.stats()["chunks"]:
        # wait_ready covers the cold-start window: without it a question asked
        # while the index is still warming would look like an empty library.
        reason = "no_documents"
    else:
        hits = index.search(question, visible_tiers_for_role(user.role))
        # No score gate here any more. A weak retrieval score means the corpus
        # doesn't cover the question — but that is exactly the case where the
        # answer might be ordinary world knowledge ("how many ounces in a cup"),
        # which the model can answer and label. Refusing on score alone decided
        # that before the model could look. The model now judges: it emits
        # NO_ANSWER for an uncovered Bald Ridge question and GENERAL for world
        # knowledge, and an uncited non-general answer is still discarded.

    user_id, user_email = user.id, user.email
    ip = audit.client_ip(request)
    top_score = max((h.score for h in hits), default=0.0)

    def event_stream():
        yield _sse("meta", {"sources": _source_summary(hits), "top_score": top_score})

        if reason:
            yield from _finish_escalated(reason, user_id, user_email, ip, question)
            return

        result = None
        try:
            for kind, value in llm.stream_answer(question, hits, history):
                if kind == "delta":
                    yield _sse("delta", {"text": value})
                else:
                    result = value
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace
            _log("ask_error", user_id, user_email, ip, detail=type(exc).__name__)
            yield from _finish_escalated("error", user_id, user_email, ip, question)
            return

        if result is None or result.escalated:
            why = result.escalation_reason if result else "error"
            yield from _finish_escalated(why, user_id, user_email, ip, question)
            return

        _log("question_answered", user_id, user_email, ip,
             detail=("general knowledge" if result.general else
                     f"{len(result.citations)} citations, score={top_score}"),
             target=question[:200])
        yield _sse(
            "done",
            {
                "escalated": False,
                "general": result.general,
                "citations": result.citations,
                "text": result.text,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
