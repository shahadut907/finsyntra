#!/usr/bin/env python3
"""Rotate the JWT signing key in an env file and revoke all refresh tokens.

    sudo python3 scripts/rotate_secret_key.py /etc/finsolve/finsolve.env
    sudo systemctl restart finsolve

Generates a fresh key with ``secrets.token_urlsafe(48)`` inside this process
and writes it into the env file (replacing any SECRET_KEY line) via an atomic
rename that keeps the file's mode and ownership. Neither the old nor the new
key is ever printed, logged, or passed on a command line.

After the restart every access and refresh token signed with the previous key
fails signature verification. The refresh-token table is also marked revoked
(defence in depth, and so a database restored from an older backup cannot
re-activate rows that had been revoked after that backup).

Uses only the standard library so it can run before the application's venv
exists. Exit code 0 on success.
"""
import os
import re
import secrets
import sqlite3
import stat
import sys
import tempfile
from datetime import datetime, timezone


def _read_env(path: str) -> dict:
    values = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m:
                values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return values


def _write_key(path: str, key: str) -> None:
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out, replaced = [], False
    for line in lines:
        if re.match(r"^\s*SECRET_KEY\s*=", line):
            if not replaced:
                out.append(f"SECRET_KEY={key}")
                replaced = True
            continue  # drop duplicate SECRET_KEY lines
        out.append(line)
    if not replaced:
        out.append(f"SECRET_KEY={key}")
    st = os.stat(path)
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".finsolve-env-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out) + "\n")
        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        if hasattr(os, "chown"):
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except PermissionError:
                pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _revoke_refresh_tokens(database_url: str) -> int:
    if not database_url.startswith("sqlite:///"):
        raise SystemExit("Only the SQLite deployment database is supported by this script")
    db_path = database_url[len("sqlite:///"):]
    if not os.path.exists(db_path):
        return 0
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE revoked_at IS NULL",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.split("\n\n")[1])
    env_path = sys.argv[1]
    env = _read_env(env_path)
    new_key = secrets.token_urlsafe(48)
    _write_key(env_path, new_key)
    if _read_env(env_path).get("SECRET_KEY") != new_key:
        raise SystemExit("FATAL: env file did not contain the new key after writing")
    revoked = _revoke_refresh_tokens(env.get("DATABASE_URL", ""))
    print(f"SECRET_KEY rotated in {env_path} (new key not displayed); "
          f"{revoked} refresh token(s) revoked. Restart the service now.")


if __name__ == "__main__":
    main()
