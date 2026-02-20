"""md_generator 用の共通テストfixture。

entrypoint が参照する services を monkeypatch し、
外部依存（GCS/Gemini）を持たない単体テストを実現する。
"""

import pytest
from unittest.mock import MagicMock

import md_generator.entrypoint as entrypoint


@pytest.fixture
def mock_storage(monkeypatch):
    """entrypoint が使う storage クライアントを差し替えてモックを返す。"""
    mock = MagicMock()
    monkeypatch.setattr(entrypoint.services, "storage", mock)
    return mock


@pytest.fixture
def mock_gemini(monkeypatch):
    """entrypoint が使う gemini クライアントを差し替えてモックを返す。"""
    mock = MagicMock()
    monkeypatch.setattr(entrypoint.services, "gemini", mock)
    return mock
