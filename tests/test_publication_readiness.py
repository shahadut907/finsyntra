from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_publication_readiness.py"
SPEC = importlib.util.spec_from_file_location("check_publication_readiness", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "publication-test@example.invalid")
    git(tmp_path, "config", "user.name", "Publication Test")
    return tmp_path


def track(repository: Path, relative_path: str, content: str = "safe\n") -> None:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repository, "add", relative_path)


def test_safe_source_and_env_example_pass(repository: Path) -> None:
    track(repository, "src/app.py", "print('safe')\n")
    track(repository, ".env.example", "SECRET_KEY=MUST_BE_SET_VIA_ENV\n")
    assert checker.find_violations(repository) == []


@pytest.mark.parametrize(
    "path, reason",
    [
        (".env.backup", "local environment file"),
        ("data/finsolve.db", "runtime database"),
        ("src/data/embeddings/chroma_db/chroma.sqlite3", "runtime database"),
        ("src/data/raw/private.pdf", "runtime upload"),
        ("venv/Lib/site-packages/example.py", "virtual environment"),
        ("frontend/node_modules/pkg/index.js", "frontend dependency"),
    ],
)
def test_prohibited_tracked_paths_fail(repository: Path, path: str, reason: str) -> None:
    track(repository, path)
    violations = checker.find_violations(repository)
    assert any(item.path == path and reason in item.reason for item in violations)


def test_secret_value_is_not_printed(repository: Path) -> None:
    secret = "do-not-print-this-secret-value"
    track(repository, "config/runtime.env.template", f"SECRET_KEY={secret}\n")
    violations = checker.find_violations(repository)
    rendered = "\n".join(f"{item.path}: {item.reason}" for item in violations)
    assert "non-placeholder secret-like assignment" in rendered
    assert secret not in rendered


def test_undeclared_gitlink_fails(repository: Path) -> None:
    track(repository, "README.md")
    git(repository, "commit", "-m", "base")
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git(repository, "update-index", "--add", "--cacheinfo", f"160000,{commit},frontend")
    violations = checker.find_violations(repository)
    assert checker.Violation("frontend", "undeclared mode 160000 gitlink") in violations


def test_nested_git_metadata_fails(repository: Path) -> None:
    track(repository, "frontend/package.json", "{}\n")
    (repository / "frontend" / ".git").mkdir()
    violations = checker.find_violations(repository)
    assert checker.Violation("frontend/.git", "nested Git metadata") in violations
