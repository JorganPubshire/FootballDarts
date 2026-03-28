from pathlib import Path

import pytest

from dart_football.rules import load_rules_path


@pytest.fixture
def rules_path() -> Path:
    return Path(__file__).resolve().parent.parent / "rules" / "standard.toml"


@pytest.fixture
def rules(rules_path: Path):
    return load_rules_path(rules_path)
