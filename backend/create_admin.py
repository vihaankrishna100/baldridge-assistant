"""Create the first administrator account.

Run once after installing:  python create_admin.py
Everyone else joins by admin invitation — there is no public sign-up.
"""

from __future__ import annotations

import getpass
import sys

from models import ROLE_ADMIN
from repo import get_repo
from repo.base import EmailTaken, UserRecord
from security import hash_password, password_problems


def main() -> int:
    store = get_repo()
    store.bootstrap()
    print(f"store: {type(store).__name__}")

    if any(u.role == ROLE_ADMIN for u in store.list_users()):
        print("An administrator already exists. Use the admin panel to invite others.")
        return 1

    email = input("Admin email: ").strip().lower()
    if not email or "@" not in email:
        print("That doesn't look like an email address.")
        return 1
    full_name = input("Full name: ").strip() or email

    password = getpass.getpass("Password (min 12 chars): ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords didn't match.")
        return 1
    problems = password_problems(password)
    if problems:
        print("Password " + ", ".join(problems) + ".")
        return 1

    try:
        store.create_user(
            UserRecord(
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                role=ROLE_ADMIN,
            )
        )
    except EmailTaken:
        print("That email already has an account.")
        return 1

    print(f"\nAdministrator created: {email}")
    print("Sign in at the web app — you'll be asked to set up two-factor on first login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
