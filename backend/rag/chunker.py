from __future__ import annotations

import re
from dataclasses import dataclass

from config import settings

# Rough token estimate: English prose averages ~4 characters per token. Used
# only to size chunks, never for billing — token counts come from the API.
CHARS_PER_TOKEN = 4

HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+.+"  # markdown heading
    r"|\d+(?:\.\d+)*[.)]?\s+[A-Z].{0,80}"  # 3.2 Numbered Policy
    r"|[A-Z][A-Z0-9 &'/(),.-]{6,80})$"  # ALL CAPS SECTION TITLE
)

# Title Case headings — "CCI Staffing Standards", "Child Care Workers". Word
# processors mark these with bold or centering, neither of which survives text
# extraction, so they have to be recognised by shape.
_SMALL = r"(?:and|or|of|the|for|to|with|in|a|an|on|per)"
_WORD = r"(?:[A-Z][A-Za-z0-9'’\-\.]*|\(?[A-Z]{2,}\)?|[0-9]+)"
TITLE_CASE_RE = re.compile(rf"^{_WORD}(?:\s+(?:{_WORD}|{_SMALL})){{0,7}}:?$")

# A heading ending in one of these reads as a section that governs the headings
# beneath it, so it becomes the breadcrumb's first level. Without this, a
# regulation covering several provider types yields citations that just say
# "Director" — with no way to tell whose Director.
_MAJOR_TAIL = re.compile(
    r"\b(standards?|requirements?|program|programs|policy|policies|matters|"
    r"support|institutions?|homes?|agencies|appendix|section|introduction|"
    r"overview|definitions?|placements?|designations?)\:?$",
    re.I,
)


@dataclass
class ProtoChunk:
    ordinal: int
    heading: str
    page: int | None
    text: str


def _is_title_case_heading(stripped: str) -> bool:
    if not (4 <= len(stripped) <= 62):
        return False
    if stripped.endswith((".", ",", ";")):
        return False
    return bool(TITLE_CASE_RE.match(stripped))


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    return bool(HEADING_RE.match(stripped)) or _is_title_case_heading(stripped)


# "1.2 Staff and caregivers must ..." — a numbered clause, never a section.
NUMBERED_RE = re.compile(r"^\d+(?:\.\d+)+")

# Long enough to identify a standard, short enough to sit in a citation line.
MAX_CRUMB_PART = 68


def _is_major(stripped: str) -> bool:
    """Section-level heading: ALL CAPS, or ending in a section-ish noun."""
    # A numbered clause can end in a section-ish word by accident ("...or
    # policy"), which would otherwise promote it over the real section.
    if NUMBERED_RE.match(stripped):
        return False
    if stripped.isupper() and len(stripped) > 6:
        return True
    return bool(_MAJOR_TAIL.search(stripped))


def _tidy(title: str) -> str:
    title = " ".join(title.split())
    if len(title) <= MAX_CRUMB_PART:
        return title
    return title[:MAX_CRUMB_PART].rstrip(" ,;:-") + "…"


def _split_paragraphs(
    text: str, state: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """Returns [(breadcrumb, paragraph)] preserving section context.

    The breadcrumb is "Section › Subsection" so a citation can say which
    provider type or programme a standard sits under, not just its local title
    — "CCI Staffing Standards › Director" rather than a bare "Director" that
    could equally be the CPA one.

    `state` carries the section across calls. Chunking runs page by page, and
    without it every page break would drop the section heading — which is
    exactly where a long regulation's applicability information lives.
    """
    if state is None:
        state = {"major": "", "minor": ""}
    out: list[tuple[str, str]] = []
    buffer: list[str] = []

    def crumb() -> str:
        major, minor = state["major"], state["minor"]
        if major and minor and major != minor:
            return f"{major} › {minor}"
        return major or minor

    def flush():
        if buffer:
            para = "\n".join(buffer).strip()
            if para:
                out.append((crumb(), para))
            buffer.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if _is_heading(line):
            flush()
            title = _tidy(stripped.lstrip("#").strip())
            if _is_major(title):
                # An ALL-CAPS banner appearing inside an already-titled section
                # ("ADMINISTRATION AND ORGANIZATION" under "CCI Staffing
                # Standards") is a subsection of it, not a replacement for it.
                nested_banner = (
                    title.isupper()
                    and state["major"]
                    and _MAJOR_TAIL.search(state["major"])
                )
                if nested_banner:
                    state["minor"] = title
                else:
                    state["major"], state["minor"] = title, ""
            else:
                state["minor"] = title
            continue
        if not stripped:
            flush()
            continue
        buffer.append(line)
    flush()
    return out


def chunk_pages(pages: list[tuple[int | None, str]]) -> list[ProtoChunk]:
    """Section-aware chunking with overlap, never crossing a page boundary.

    A chunk never spans two headings. That costs a little packing efficiency on
    short documents, but it is what makes "search only the TRANSPORTATION
    section" mean anything: if sections were merged, every heading after the
    first would silently disappear from the corpus, and a citation would name a
    section the quoted text didn't come from.

    Staying inside one page likewise means a citation can always name an exact
    page, which is what makes an answer checkable by a staff member.
    """
    max_chars = settings.chunk_tokens * CHARS_PER_TOKEN
    overlap_chars = settings.chunk_overlap * CHARS_PER_TOKEN

    chunks: list[ProtoChunk] = []
    ordinal = 0
    # Shared so the section heading survives page breaks.
    section = {"major": "", "minor": ""}

    for page, text in pages:
        for heading, paragraphs in _group_by_heading(_split_paragraphs(text, section)):
            current: list[str] = []
            current_len = 0

            def emit():
                nonlocal ordinal, current, current_len
                body = "\n\n".join(current).strip()
                if body:
                    chunks.append(
                        ProtoChunk(
                            ordinal=ordinal, heading=heading, page=page, text=body
                        )
                    )
                    ordinal += 1
                current = []
                current_len = 0

            for para in paragraphs:
                # A single oversized paragraph gets hard-split on sentence bounds.
                if len(para) > max_chars:
                    emit()
                    for piece in _hard_split(para, max_chars):
                        chunks.append(
                            ProtoChunk(
                                ordinal=ordinal, heading=heading, page=page, text=piece
                            )
                        )
                        ordinal += 1
                    continue

                if current_len + len(para) > max_chars and current:
                    tail = current[-1] if overlap_chars else ""
                    emit()
                    if tail and len(tail) <= overlap_chars:
                        current.append(tail)
                        current_len += len(tail)

                current.append(para)
                current_len += len(para)

            emit()

    return chunks


def _group_by_heading(
    pairs: list[tuple[str, str]],
) -> list[tuple[str, list[str]]]:
    """Collapse [(heading, para)] into [(heading, [paras])], preserving order."""
    grouped: list[tuple[str, list[str]]] = []
    for heading, para in pairs:
        if grouped and grouped[-1][0] == heading:
            grouped[-1][1].append(para)
        else:
            grouped.append((heading, [para]))
    return grouped


def _hard_split(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    buf = ""
    for sentence in sentences:
        if len(buf) + len(sentence) + 1 > max_chars and buf:
            out.append(buf.strip())
            buf = ""
        if len(sentence) > max_chars:
            for i in range(0, len(sentence), max_chars):
                out.append(sentence[i : i + max_chars].strip())
            continue
        buf = f"{buf} {sentence}".strip()
    if buf:
        out.append(buf.strip())
    return [c for c in out if c]
