#!/usr/bin/env python3
"""Create, reset, or deactivate a private FinSyntra account.

    python scripts/manage_user.py create --email ops@acme.example --tenant tenant_acme \
        --role admin --name "Ops Admin" [--department IT]
    python scripts/manage_user.py reset-password --email ops@acme.example
    python scripts/manage_user.py deactivate --email admin@finsolve.com
    python scripts/manage_user.py audit-committed

This is the supported way to provision the first administrator in production:
production startup never seeds the sample private accounts (their committed
password hashes are publicly known) and refuses to start while any active
private account still carries one — see assert_no_committed_credentials().

The password is read from the FINSOLVE_NEW_PASSWORD environment variable if
set, otherwise prompted for twice without echo. It is never printed or logged.
Refresh tokens are revoked on reset-password and deactivate.
"""
import argparse
import getpass
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.backend.auth.authentication import get_password_hash  # noqa: E402
from src.backend.database.database import (  # noqa: E402
    RefreshToken, SessionLocal, User, _committed_seed_hashes,
)
from src.config.roles import Role  # noqa: E402

MIN_PASSWORD_LENGTH = 12


def _read_password() -> str:
    password = os.environ.get("FINSOLVE_NEW_PASSWORD")
    if password is None:
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return password


def _revoke_refresh_tokens(db, user_id: str) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)


def _find(db, email: str) -> User:
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if user is None:
        sys.exit("No such user")
    if user.is_public_demo:
        sys.exit("Public-demo identities are managed by the seed, not this tool")
    return user


def create(args) -> None:
    email = args.email.strip().lower()
    if "@" not in email:
        sys.exit("Invalid email address")
    role = args.role.lower()
    if role not in {item.value for item in Role}:
        sys.exit("Invalid role")
    if not args.tenant.strip():
        sys.exit("--tenant is required")
    password = _read_password()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            sys.exit("User already exists")
        db.add(User(
            id=email, username=email, email=email,
            hashed_password=get_password_hash(password),
            full_name=args.name.strip() or "User", role=role,
            tenant_id=args.tenant.strip(), department=args.department,
            is_active=True, is_public_demo=False,
        ))
        db.commit()
    finally:
        db.close()
    print(f"Created {role} account {email} in {args.tenant.strip()}")


def reset_password(args) -> None:
    password = _read_password()
    db = SessionLocal()
    try:
        user = _find(db, args.email)
        user.hashed_password = get_password_hash(password)
        _revoke_refresh_tokens(db, user.id)
        db.commit()
    finally:
        db.close()
    print(f"Password reset for {args.email.strip().lower()}; sessions revoked")


def deactivate(args) -> None:
    db = SessionLocal()
    try:
        user = _find(db, args.email)
        user.is_active = False
        _revoke_refresh_tokens(db, user.id)
        db.commit()
    finally:
        db.close()
    print(f"Deactivated {args.email.strip().lower()}; sessions revoked")


def audit_committed(args) -> None:
    known = _committed_seed_hashes()
    db = SessionLocal()
    try:
        exposed = [u.email for u in db.query(User).filter(
            User.is_active.is_(True), User.is_public_demo.is_(False)).all()
            if u.hashed_password in known]
    finally:
        db.close()
    for email in exposed:
        print(f"COMMITTED-CREDENTIAL {email}")
    print(f"{len(exposed)} active private account(s) use a committed password hash")
    sys.exit(1 if exposed else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create")
    p.add_argument("--email", required=True)
    p.add_argument("--tenant", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--department", default="General")
    p.set_defaults(func=create)
    p = sub.add_parser("reset-password")
    p.add_argument("--email", required=True)
    p.set_defaults(func=reset_password)
    p = sub.add_parser("deactivate")
    p.add_argument("--email", required=True)
    p.set_defaults(func=deactivate)
    sub.add_parser("audit-committed").set_defaults(func=audit_committed)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
