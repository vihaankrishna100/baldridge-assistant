from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

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


_expander = ThreadPoolExecutor(max_workers=4, thread_name_prefix="expand")


def _fuse(result_lists: list[list[Hit]], top_k: int) -> list[Hit]:
    """Reciprocal rank fusion: a passage's place in the merged list comes from
    its rank in each search, not its raw score. Scores are the share of the
    query's words a passage contains, so a 15-word reworded query scores every
    passage lower than the 4-word original did. Merging on score would bury
    exactly the passages the rewording was there to find. Each hit keeps its
    best score, which is what the citations and audit report."""
    k = 60  # the usual RRF constant; damps the gap between rank 1 and rank 2
    fused: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for hits in result_lists:
        for rank, h in enumerate(hits, start=1):
            fused[h.chunk_id] = fused.get(h.chunk_id, 0.0) + 1.0 / (k + rank)
            if h.chunk_id not in best or h.score > best[h.chunk_id].score:
                best[h.chunk_id] = h
    order = sorted(fused, key=lambda cid: fused[cid], reverse=True)
    return [best[cid] for cid in order[:top_k]]


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
        tiers = visible_tiers_for_role(user.role)
        previous = next((t["content"] for t in reversed(history) if t["role"] == "user"), "")
        # Started first so the model call overlaps the searches below.
        expansion = (
            _expander.submit(llm.expand_query, question, previous)
            if settings.query_expansion and settings.anthropic_api_key
            else None
        )
        result_lists = [index.search(question, tiers)]
        # A follow-up like "who do I give it to once it's done?" names nothing
        # searchable — "it" is in the previous question. Searching the two
        # together finds the passages the conversation is actually about.
        if previous:
            result_lists.append(index.search(f"{previous[:500]} {question}", tiers))
        # The question reworded the way the documents word things, so "how
        # young can a child be" also searches "youth" and "minimum age".
        if expansion is not None:
            try:
                terms = expansion.result(timeout=10)
            except Exception:  # noqa: BLE001 - expansion only adds recall
                terms = ""
            if terms:
                result_lists.append(index.search(terms, tiers))
        hits = _fuse(result_lists, settings.retrieval_top_k)
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

        detail = ("general knowledge" if result.general else
                  f"{len(result.citations)} citations, score={top_score}")
        if result.fell_back:
            detail += f" (answered by {result.model} after the main model declined)"
        _log("question_answered", user_id, user_email, ip, detail=detail,
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
