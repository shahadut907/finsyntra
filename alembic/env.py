"""Alembic environment for FinSyntra.

The database URL is resolved from the application's own settings so that a
migration can never silently target a different database than the running app.

Resolution order:
  1. ``alembic -x db_url=...``      explicit override (used by the test suite)
  2. ``DATABASE_URL`` env var       same variable the app reads
  3. ``settings.database_url``      .env / pydantic-settings
  4. the SQLite development default that database.py falls back to

SQLite needs ``render_as_batch`` for ALTER TABLE: it has no native
ADD/DROP COLUMN for most cases, so Alembic emulates it by copying the table.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the project importable regardless of where alembic is invoked from.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Pure, side-effect-free URL validation — safe to import before anything
# that constructs the runtime database engine.
from src.config.database_url import is_postgres_url, require_postgres_driver  # noqa: E402

# Import the models so autogenerate and the drift test can see the real schema.
# NOTE: this import does construct the application's module-level runtime
# engine as a pre-existing side effect of src/backend/database/database.py
# (needed for Base.metadata); that coupling predates this file's URL
# resolution logic and is out of scope for this fix — only the URL/driver
# helpers above were moved out to avoid *adding* a second such dependency.
from src.backend.database.database import Base  # noqa: E402

target_metadata = Base.metadata


def _default_sqlite_url() -> str:
    """Mirror database.py's fallback so migrations hit the same file."""
    return "sqlite:///%s" % os.path.join(PROJECT_ROOT, "data", "finsolve.db").replace("\\", "/")


def _validated(url: str) -> str:
    """Apply the same deterministic PostgreSQL-or-fail rule as database.py:
    an explicitly requested PostgreSQL URL must be usable, never silently
    replaced by SQLite."""
    if is_postgres_url(url):
        require_postgres_driver()
    return url


def get_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("db_url"):
        return _validated(x_args["db_url"])

    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return _validated(env_url)

    try:
        from src.config.settings import settings
        if settings.database_url:
            return _validated(settings.database_url)
    except Exception:
        pass

    return _default_sqlite_url()


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Required for SQLite ALTER TABLE support.
            render_as_batch=connection.dialect.name == "sqlite",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
