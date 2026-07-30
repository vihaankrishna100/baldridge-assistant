"""Create the first administrator account.

Run once after installing:  python create_admin.py
Everyone else joins by admin invitation — there is no public sign-up.
"""

from __future__ import annotations

import getpass
import sys

from database import Base, SessionLocal, engine, run_migrations
from models import ROLE_ADMIN, User
from security import hash_password, password_problems


def main() -> int:
    Base.metadata.create_all(bind=engine)
    run_migrations()

    db = SessionLocal()
    try:
        if db.query(User).filter(User.role == ROLE_ADMIN).count():
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

        db.add(
            User(
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                role=ROLE_ADMIN,
            )
        )
        db.commit()
        print(f"\nAdministrator created: {email}")
        print("Sign in at the web app — you'll be asked to set up two-factor on first login.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
