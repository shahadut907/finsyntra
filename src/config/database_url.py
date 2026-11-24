"""Pure PostgreSQL/SQLite URL-selection helpers.

Importing this module has ZERO side effects: no SQLAlchemy import, no
``settings`` import, no engine construction, no connection attempt. That is
the entire point of its existence — both the runtime engine
(``src/backend/database/database.py``) and Alembic (``alembic/env.py``) need
the same "explicit PostgreSQL must succeed or fail loudly" rule, and neither
should have to import the other's module-level state (which, for
``database.py``, includes constructing the real application database engine
at import time) just to reuse it.
"""


def is_postgres_url(database_url: str) -> bool:
    """True for any postgres/postgresql(+driver) SQLAlchemy URL scheme."""
    return database_url.split("://", 1)[0].split("+", 1)[0].lower() in (
        "postgres", "postgresql",
    )


def require_postgres_driver() -> None:
    """Verify the synchronous PostgreSQL DBAPI driver is importable.

    Raises a clear, credential-free error instead of letting an explicitly
    requested PostgreSQL configuration silently fall back to SQLite when the
    driver is missing. Applies regardless of dev/staging/production — if
    PostgreSQL was explicitly requested, it must be used or the failure must
    be loud.
    """
    try:
        import psycopg2  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "FATAL: DATABASE_URL is configured for PostgreSQL, but the "
            "psycopg2 driver is not installed. Install psycopg2-binary "
            "(see requirements.txt) or correct DATABASE_URL. Refusing to "
            "silently fall back to SQLite."
        ) from exc
