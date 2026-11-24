#!/usr/bin/env python3
"""Fail when the Git index contains material that must not be published."""

from __future__ import annotations

import argparse
import configparser
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


MAX_SCANNED_TEXT_BYTES = 1_000_000
MAX_BINARY_BYTES = 5 * 1024 * 1024

SAFE_EXACT_PATHS = {
    ".env.example",
}

SAFE_SECRET_PLACEHOLDERS = {
    "",
    "change_me",
    "changeme",
    "must_be_set_via_env",
    "not_set",
    "placeholder",
}

SECRET_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:export[ \t]+)?(?:secret_key|jwt_secret(?:_key)?|refresh_token_secret|"
    r"api_key|password|database_url|redis_url)[ \t]*=[ \t]*([^#\r\n]*)",
    re.IGNORECASE | re.MULTILINE,
)

HIGH_CONFIDENCE_SECRET_PATTERNS: Sequence[tuple[str, re.Pattern[str]]] = (
    ("private key material", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("JWT-like token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
)


@dataclass(frozen=True)
class TrackedEntry:
    mode: str
    path: str


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str


def run_git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def tracked_entries(repo: Path) -> list[TrackedEntry]:
    raw = run_git(repo, "ls-files", "--stage", "-z")
    entries: list[TrackedEntry] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        path = raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        entries.append(TrackedEntry(mode=mode, path=path))
    return entries


def declared_submodule_paths(repo: Path) -> set[str]:
    gitmodules = repo / ".gitmodules"
    if not gitmodules.is_file():
        return set()
    parser = configparser.ConfigParser()
    parser.read(gitmodules, encoding="utf-8")
    return {
        parser.get(section, "path").replace("\\", "/").strip("/")
        for section in parser.sections()
        if section.startswith("submodule ") and parser.has_option(section, "path")
    }


def prohibited_path_reason(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    lower = normalized.lower()
    name = PurePosixPath(lower).name
    parts = PurePosixPath(lower).parts

    if normalized in SAFE_EXACT_PATHS:
        return None
    if name == ".env" or name.startswith(".env."):
        return "local environment file"
    if name in {"jwt_key.txt", "secret_key.txt", "cookies.txt"}:
        return "secret, signing-key, or session dump"
    if name.endswith((".pem", ".key", ".p12", ".pfx", ".jks")):
        return "key or certificate material"
    if name.endswith((".db", ".sqlite", ".sqlite3")):
        return "runtime database"
    if "venv" in parts or ".venv" in parts or (parts and parts[0] in {"env", "env"}):
        return "virtual environment"
    if "__pycache__" in parts or name.endswith((".pyc", ".pyo")):
        return "Python cache"
    if any(part in {".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox"} for part in parts):
        return "test, lint, or type-check cache"
    if name == ".coverage" or name.startswith(".coverage.") or "htmlcov" in parts or name == "coverage.xml":
        return "coverage output"
    if lower.startswith("src/data/embeddings/") or "chroma_db" in parts or "chroma" in parts:
        return "Chroma or embedding persistence"
    if lower.startswith("src/data/raw/") or any(part in {"uploads", "upload"} for part in parts):
        return "runtime upload or unreviewed raw document"
    if parts and parts[0] in {"logs", "diagnostics"}:
        return "log or diagnostic dump"
    if name.startswith(("server_log", "server_stdout", "server_stderr", "uvicorn_out", "uvicorn_err")):
        return "server output dump"
    if "node_modules" in parts:
        return "frontend dependency directory"
    if lower.startswith("frontend/build/") or lower.startswith("frontend/dist/"):
        return "frontend build output"
    if parts and parts[0] in {"exports", "generated_exports", "output"}:
        return "generated export"
    if parts and parts[0] in {".vscode", ".idea"}:
        return "local IDE configuration"
    if name in {".ds_store", "thumbs.db", "desktop.ini", "nul"}:
        return "operating-system metadata"
    if name.startswith("_patch_") or name.endswith((".tmp", ".temp", ".bak", ".orig", ".rej")):
        return "temporary or patch artifact"
    if len(parts) == 1 and (name.startswith("debug_") or name.startswith("diagnostic_")):
        return "local debug artifact"
    return None


def looks_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def is_safe_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    return (
        normalized in SAFE_SECRET_PLACEHOLDERS
        or "placeholder" in normalized
        or "change_me" in normalized
        or "must_be_set" in normalized
        or "redacted" in normalized
        or normalized.startswith("new_secret")
        or normalized.startswith("${")
        or normalized.startswith(("{", "$(", "os.getenv(", "config.get(", "f\"", "f'", "sqlite:///"))
        or normalized.startswith(("login_data.", "st.text_input("))
        or normalized in {"database_url", "redis_url", "secret_key", "password"}
        or normalized.endswith("...")
        or "localhost" in normalized
        or "127.0.0.1" in normalized
    )


def scan_tracked_file(repo: Path, entry: TrackedEntry) -> Iterable[Violation]:
    file_path = repo / Path(entry.path)
    if not file_path.is_file():
        return ()
    size = file_path.stat().st_size
    data = file_path.read_bytes() if size <= MAX_SCANNED_TEXT_BYTES else file_path.read_bytes()[:8192]
    binary = looks_binary(data)
    violations: list[Violation] = []
    if size > MAX_BINARY_BYTES and binary:
        violations.append(Violation(entry.path, f"oversized binary ({size} bytes)"))
    if binary or size > MAX_SCANNED_TEXT_BYTES:
        return violations
    text = data.decode("utf-8", errors="replace")
    for label, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS:
        if pattern.search(text):
            violations.append(Violation(entry.path, f"high-confidence {label} pattern"))
            break
    if entry.path not in SAFE_EXACT_PATHS:
        for match in SECRET_ASSIGNMENT.finditer(text):
            if not is_safe_placeholder(match.group(1)):
                violations.append(Violation(entry.path, "non-placeholder secret-like assignment"))
                break
    return violations


def find_violations(repo: Path, entries: Sequence[TrackedEntry] | None = None) -> list[Violation]:
    repo = repo.resolve()
    entries = list(entries) if entries is not None else tracked_entries(repo)
    declared_submodules = declared_submodule_paths(repo)
    violations: list[Violation] = []

    for entry in entries:
        reason = prohibited_path_reason(entry.path)
        if reason:
            violations.append(Violation(entry.path, reason))
        if entry.mode == "160000" and entry.path not in declared_submodules:
            violations.append(Violation(entry.path, "undeclared mode 160000 gitlink"))
        violations.extend(scan_tracked_file(repo, entry))

    skipped_trees = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "build",
        "dist",
        "coverage",
        "htmlcov",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    for current, directories, _files in os.walk(repo):
        current_path = Path(current)
        if current_path != repo and ".git" in directories:
            relative = (current_path / ".git").relative_to(repo).as_posix()
            violations.append(Violation(relative, "nested Git metadata"))
        directories[:] = [directory for directory in directories if directory not in skipped_trees]

    return sorted(set(violations), key=lambda item: (item.path.lower(), item.reason))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)
    try:
        violations = find_violations(args.repo)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"publication check failed to run: {exc}", file=sys.stderr)
        return 2
    if violations:
        print(f"publication readiness: FAIL ({len(violations)} violation(s))")
        for violation in violations:
            print(f"- {violation.path}: {violation.reason}")
        return 1
    print("publication readiness: PASS (tracked tree containment checks only)")
    print("Git history and application-level security still require separate approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
