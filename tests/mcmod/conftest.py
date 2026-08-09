from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
