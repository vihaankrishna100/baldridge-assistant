from __future__ import annotations

import re

# Bald Ridge serves youth, so uploaded material can accidentally carry resident
# identifiers. We do NOT silently rewrite documents — we flag them so a human
# decides. Silent redaction would make the corpus disagree with the source of
# record, which is worse than a visible warning.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Social Security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "date of birth",
        re.compile(r"\b(?:DOB|D\.O\.B\.|date of birth)\b\s*[:\-]?\s*\d", re.I),
    ),
    ("medical record number", re.compile(r"\b(?:MRN|medical record (?:no|number))\b", re.I)),
    ("credit card number", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("bank account number", re.compile(r"\b(?:routing|account)\s*(?:no|number|#)\b", re.I)),
    (
        "API key or password",
        re.compile(r"\b(?:api[_ -]?key|secret[_ -]?key|password)\s*[:=]\s*\S{6,}", re.I),
    ),
]


def scan(text: str) -> list[str]:
    """Returns human-readable labels for anything that warrants review."""
    found: list[str] = []
    for label, pattern in PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found
