from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]


def declared_settings_fields() -> set[str]:
    tree = ast.parse((ROOT / "src/config/settings.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {
                child.target.id.upper()
                for child in node.body
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
            }
    raise AssertionError("Settings class not found")


def template_keys() -> set[str]:
    pattern = re.compile(r"^([A-Z][A-Z0-9_]*)=")
    keys: set[str] = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            assert match.group(1) not in keys, f"duplicate template key: {match.group(1)}"
            keys.add(match.group(1))
    return keys


def test_env_example_exactly_matches_settings_model() -> None:
    assert template_keys() == declared_settings_fields()


def test_env_example_contains_no_production_secret() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SECRET_KEY=MUST_BE_SET_VIA_ENV" in text
    assert not re.search(r"^BYPASS_AUTH=true$", text, re.MULTILINE | re.IGNORECASE)

