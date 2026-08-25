"""Offline checks for the retrieval + guardrail layer. No API key needed.

Run with:  python selftest.py
Uses a throwaway in-memory database and a small fake policy corpus, so it never
touches the real library.
"""

from __future__ import annotations

import sys

import database
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Point everything at an isolated file DB before importing anything that binds.
test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
database.engine = test_engine
database.SessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

from config import settings  # noqa: E402
from llm import NO_ANSWER, build_user_turn, validate_citations  # noqa: E402
from models import (  # noqa: E402
    VISIBILITY_LEADERSHIP,
    VISIBILITY_STAFF,
    visible_tiers_for_role,
)
from repo.base import ChunkRecord, DocumentRecord  # noqa: E402
from repo.sqlite_repo import SqliteRepo  # noqa: E402
from rag.chunker import chunk_pages  # noqa: E402
from rag.index import HybridIndex  # noqa: E402
from rag.redact import scan  # noqa: E402

database.Base.metadata.create_all(bind=test_engine)

CORPUS = [
    (
        "Volunteer Handbook",
        VISIBILITY_STAFF,
        """VOLUNTEER CHECK-IN PROCEDURE
Every volunteer must sign in at the front desk before entering the residence
hall. Present a photo ID and receive a visitor badge. Badges are returned at
sign-out. Volunteers who have not completed a background check may not be
alone with a resident at any time.

TRANSPORTATION
Volunteers are not permitted to transport residents in personal vehicles.
All transportation is arranged through the program coordinator using agency
vehicles only.""",
    ),
    (
        "Incident Reporting Policy",
        VISIBILITY_STAFF,
        """REPORTING TIMELINE
Any incident involving injury, property damage, or a resident leaving the
premises without permission must be documented on Form IR-2 within 24 hours
of the event. The shift supervisor reviews and signs every incident report
before it is filed.

ESCALATION
Incidents involving suspected abuse or neglect are reported immediately to the
program director and to the state hotline. Do not wait for the 24 hour window.""",
    ),
    (
        "Board Compensation Memo",
        VISIBILITY_LEADERSHIP,
        """EXECUTIVE COMPENSATION REVIEW
The compensation committee reviews executive director salary annually each
November using comparable data from similar sized nonprofits in the region.""",
    ),
]


def build_index():
    """Exercises the real repository, so the store interface is under test too."""
    store = SqliteRepo()
    store.bootstrap()
    for title, visibility, text in CORPUS:
        doc = DocumentRecord(
            title=title,
            filename=f"{title}.txt",
            category="Policies",
            visibility=visibility,
            uploaded_by="test",
        )
        chunks = [
            ChunkRecord(
                document_id=doc.id,
                ordinal=proto.ordinal,
                heading=proto.heading,
                page=proto.page,
                text=proto.text,
                document_title=doc.title,
                category=doc.category,
                visibility=doc.visibility,
                document_active=True,
            )
            for proto in chunk_pages([(None, text)])
        ]
        doc.chunk_count = len(chunks)
        store.create_document(doc, chunks)

    idx = HybridIndex()
    n = idx.rebuild(store)
    return idx, n


passed = failed = 0


def check(name: str, ok: bool, note: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f" — {note}" if note else ""))


def main() -> int:
    idx, n_chunks = build_index()
    print(f"\nIndex built: {n_chunks} chunks, {idx.stats()}\n")

    print("Retrieval")
    hits = idx.search("how long do I have to file an incident report?", [VISIBILITY_STAFF])
    check(
        "finds the incident-reporting policy",
        bool(hits) and "Incident" in hits[0].document_title,
        f"got {hits[0].document_title if hits else 'nothing'}",
    )
    check(
        "top hit clears the refusal threshold",
        bool(hits) and hits[0].score >= settings.retrieval_min_score,
        f"score={hits[0].score if hits else 0} threshold={settings.retrieval_min_score}",
    )

    hits = idx.search("can volunteers drive residents in their own car", [VISIBILITY_STAFF])
    check(
        "finds the transportation rule",
        bool(hits) and "Volunteer" in hits[0].document_title,
        f"got {hits[0].document_title if hits else 'nothing'}",
    )

    print("\nRefusal gate")
    hits = idx.search("what is the wifi password for the guest network", [VISIBILITY_STAFF])
    top = hits[0].score if hits else 0.0
    check(
        "off-corpus question falls below threshold",
        top < settings.retrieval_min_score,
        f"score={top} threshold={settings.retrieval_min_score}",
    )

    print("\nVisibility isolation")
    staff_hits = idx.search("executive director salary review", visible_tiers_for_role("staff"))
    check(
        "staff never see the leadership-only memo",
        all(h.visibility == VISIBILITY_STAFF for h in staff_hits),
        f"leaked: {[h.document_title for h in staff_hits if h.visibility != VISIBILITY_STAFF]}",
    )
    lead_hits = idx.search("executive director salary review", visible_tiers_for_role("leadership"))
    check(
        "leadership do see it",
        any(h.visibility == VISIBILITY_LEADERSHIP for h in lead_hits),
    )

    print("\nCitation validation")
    hits = idx.search("incident report timeline", [VISIBILITY_STAFF])[:2]
    text, cites = validate_citations(
        "Reports are due within 24 hours [1]. The board approves it annually [9].", hits
    )
    check("keeps a real citation", any(c["n"] == 1 for c in cites))
    check("strips an invented citation", "[9]" not in text, text)

    _, empty = validate_citations("An answer with no sources at all.", hits)
    check("uncited answer yields zero citations (triggers escalation)", empty == [])

    print("\nPrompt assembly")
    turn = build_user_turn("test question", hits)
    check("sources are fenced as untrusted data", "<sources>" in turn and "UNTRUSTED" in turn)
    check("refusal sentinel is stated in the turn", NO_ANSWER in turn)

    print("\nPII scan")
    check("flags an SSN", "Social Security number" in scan("Resident SSN 123-45-6789 on file"))
    check("flags a stored password", "API key or password" in scan("password: hunter2hunter2"))
    check("clean text is not flagged", scan("Volunteers sign in at the front desk.") == [])

    print("\nResponse schemas accept uuid ids")
    # The sqlite backend hands out integer audit ids and Firestore hands out
    # uuid strings, so a schema typed for one silently 500s on the other. This
    # exercises the uuid shape, which is what production actually stores.
    from repo.base import AuditEntry, DocumentRecord, InviteRecord, UserRecord, new_id
    from schemas import AuditOut, DocumentOut, UserOut

    ok = True
    for schema, record in (
        (AuditOut, AuditEntry(id=new_id(), user_email="a@b.c", action="login_success")),
        (UserOut, UserRecord(id=new_id(), email="a@b.c")),
        (DocumentOut, DocumentRecord(id=new_id(), title="t")),
    ):
        try:
            schema.model_validate(record)
        except Exception as exc:  # noqa: BLE001
            ok = False
            check(f"{schema.__name__} accepts a uuid id", False, str(exc)[:90])
    if ok:
        check("every response schema accepts a uuid id", True)

    print("\nEscalation copy")
    check(
        "never invents a phone number when unconfigured",
        "administrator still needs to add" in settings.escalation_text()
        if not (settings.org_phone or settings.org_email)
        else True,
    )

    print(f"\n{passed} passed, {failed} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
