"""Hermetic defaults for the backend regression suite."""

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def deterministic_quality_gate_default(monkeypatch):
    """Do not let a developer's .env silently change quality-gate assertions.

    Tests that exercise the disabled mode still patch this setting explicitly
    inside their own scope.
    """
    monkeypatch.setattr(settings, "QUALITY_GATE_ENABLED", True)
