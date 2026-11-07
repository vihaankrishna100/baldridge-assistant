"""What each role may see and do, adjustable by admins on the Admin page.

The defaults reproduce the rules that used to be hard-coded, so nothing
changes until an admin edits them. Admins always hold every permission: the
admin panel and the power to change these rules stay with them, which also
means nobody can lock every administrator out.

The matrix lives in app_settings as JSON and is cached briefly per process,
like the model choice, so a change reaches every server instance within a
minute without a database read on every request.
"""

from __future__ import annotations

import json
import threading
import time

from models import (
    ROLE_ADMIN,
    ROLE_LEADERSHIP,
    ROLE_STAFF,
    ROLE_TEAM,
    VISIBILITY_LEADERSHIP,
    VISIBILITY_STAFF,
)

ASK = "ask"
SEE_LEADERSHIP_DOCS = "see_leadership_docs"
VIEW_DOCUMENTS = "view_documents"
DOWNLOAD = "download"
MANAGE_DOCUMENTS = "manage_documents"

# Order is the order the admin page shows them in.
PERMISSIONS: dict[str, tuple[str, str]] = {
    ASK: ("Ask questions", "Use the Ask page to get answers from the documents."),
    SEE_LEADERSHIP_DOCS: (
        "See leadership-only documents",
        "Answers can draw on them, and they appear in the document list.",
    ),
    VIEW_DOCUMENTS: ("Browse the Documents page", "See the list of documents in the library."),
    DOWNLOAD: ("Download original files", "Open the PDF or file behind a document or citation."),
    MANAGE_DOCUMENTS: (
        "Upload, edit and retire documents",
        "Add new files, change titles or who can see them, retire or delete them, and see storage.",
    ),
}

# Roles an admin can configure. Admin itself is fixed at "everything".
EDITABLE_ROLES: dict[str, str] = {
    ROLE_STAFF: "Staff",
    ROLE_TEAM: "Team login",
    ROLE_LEADERSHIP: "Leadership",
}

DEFAULTS: dict[str, set[str]] = {
    ROLE_STAFF: {ASK, VIEW_DOCUMENTS, DOWNLOAD},
    ROLE_TEAM: {ASK, VIEW_DOCUMENTS, DOWNLOAD},
    ROLE_LEADERSHIP: set(PERMISSIONS),
}

SETTING_KEY = "role_permissions"
_TTL = 60.0
_cache: tuple[float, dict[str, set[str]] | None] = (0.0, None)
_lock = threading.Lock()


def _normalise(raw: dict) -> dict[str, set[str]]:
    """Unknown roles and permissions are dropped; a role missing from the
    stored value keeps its default rather than losing everything."""
    out = {role: set(perms) for role, perms in DEFAULTS.items()}
    for role, perms in (raw or {}).items():
        if role in EDITABLE_ROLES and isinstance(perms, list):
            out[role] = {p for p in perms if p in PERMISSIONS}
    return out


def matrix() -> dict[str, set[str]]:
    global _cache
    with _lock:
        at, value = _cache
        if value is not None and time.monotonic() - at < _TTL:
            return value
    from repo import get_repo

    value = {role: set(perms) for role, perms in DEFAULTS.items()}
    store = get_repo()
    if hasattr(store, "get_setting"):
        try:
            raw = store.get_setting(SETTING_KEY)
            if raw:
                value = _normalise(json.loads(raw))
        except Exception:  # noqa: BLE001 - unreadable rules fall back to the defaults
            pass
    with _lock:
        _cache = (time.monotonic(), value)
    return value


def save(new: dict[str, list[str]]) -> dict[str, set[str]]:
    from repo import get_repo

    value = _normalise(new)
    get_repo().set_setting(
        SETTING_KEY, json.dumps({r: sorted(p) for r, p in value.items()}, sort_keys=True)
    )
    global _cache
    with _lock:
        _cache = (0.0, None)
    return value


def reset() -> dict[str, set[str]]:
    return save({r: sorted(p) for r, p in DEFAULTS.items()})


def for_role(role: str) -> set[str]:
    if role == ROLE_ADMIN:
        return set(PERMISSIONS)
    return set(matrix().get(role, set()))


def can(role: str, permission: str) -> bool:
    return permission in for_role(role)


def visible_tiers(role: str) -> list[str]:
    """Which document visibilities this role's answers and lists may use."""
    if can(role, SEE_LEADERSHIP_DOCS):
        return [VISIBILITY_STAFF, VISIBILITY_LEADERSHIP]
    return [VISIBILITY_STAFF]
