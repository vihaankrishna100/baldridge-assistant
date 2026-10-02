"""Guard: the app must import under Vercel's constraints.

Vercel's Python functions cap the unzipped bundle at 250 MB. scikit-learn,
scipy and numpy are 358 MB between them, so production ships without them and
Postgres does the retrieval instead. psycopg2 is absent too — this project
talks to Neon through psycopg 3.

The failure mode this catches is not a test failure, it is a deploy that
imports fine locally and 500s on its first real request. It has already caught
one: database.py built a SQLAlchemy engine at import time, and with a Postgres
DSN that made SQLAlchemy import psycopg2.

Run with:  python check_serverless_imports.py
"""

from __future__ import annotations

import importlib.abc
import os
import sys

# Every top-level package that is NOT in requirements.txt but IS in the
# development environment. If application code reaches for one of these at
# import time, production breaks.
ABSENT_IN_PRODUCTION = {"sklearn", "numpy", "scipy", "google", "psycopg2"}


class _Absent(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in ABSENT_IN_PRODUCTION:
            raise ModuleNotFoundError(
                f"No module named {fullname!r} — not in the Vercel bundle"
            )
        return None


def main() -> int:
    os.environ.setdefault("REPO_BACKEND", "postgres")
    # A DSN that is well formed but never connected to; importing must not
    # open a connection.
    os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")

    sys.meta_path.insert(0, _Absent())
    for name in list(sys.modules):
        if name.split(".")[0] in ABSENT_IN_PRODUCTION:
            del sys.modules[name]

    failures: list[str] = []

    try:
        import main as app_module

        print(f"  ok   application imports      ({type(app_module.app).__name__})")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"importing main failed: {type(exc).__name__}: {exc}")
        print(f"  FAIL application imports      {type(exc).__name__}: {exc}")
        # Nothing below can run without the app.
        print(f"\n{len(failures)} failure(s)")
        return 1

    # No api/index.py: Vercel detects FastAPI and builds a single function
    # from main.py, routing original paths straight to the app. An entry
    # shim plus a rewrite actively broke that — the rewrite prepended
    # /api/index to every path and the app 404'd on all of them.

    from rag.index import SCIENTIFIC_STACK

    if SCIENTIFIC_STACK:
        failures.append("rag.index believes sklearn is available under the production profile")
        print("  FAIL scientific stack absent")
    else:
        print("  ok   scientific stack absent   (retrieval delegates to postgres)")

    routes = {r.path for r in app_module.app.routes}
    for required in ("/health", "/auth/login", "/chat/ask", "/admin/audit", "/documents"):
        if required not in routes:
            failures.append(f"route missing: {required}")
            print(f"  FAIL route registered         {required}")
    else:
        print(f"  ok   routes registered         ({len(routes)} total)")

    print()
    if failures:
        print(f"{len(failures)} failure(s) — this would break the Vercel deploy")
        return 1
    print("production import profile is clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
