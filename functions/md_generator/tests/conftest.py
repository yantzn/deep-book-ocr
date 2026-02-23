"""md_generator 用の共通テストfixture。

entrypoint が参照する services を monkeypatch し、
外部依存（GCS/Gemini）を持たない単体テストを実現する。
"""

import pytest
import sys
import importlib
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock

# tests/ 直下実行でも main.py を import できるように関数ルートを追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

entrypoint = importlib.import_module("main")


def _rebind_services(*, storage=None, gemini=None):
    current = entrypoint.services
    rebound = SimpleNamespace(
        storage=storage if storage is not None else current.storage,
        gemini=gemini if gemini is not None else current.gemini,
    )
    entrypoint.services = rebound


@pytest.fixture
def mock_storage(monkeypatch):
    """entrypoint が使う storage クライアントを差し替えてモックを返す。"""
    mock = MagicMock()
    _rebind_services(storage=mock)
    return mock


@pytest.fixture
def mock_gemini(monkeypatch):
    """entrypoint が使う gemini クライアントを差し替えてモックを返す。"""
    mock = MagicMock()
    _rebind_services(gemini=mock)
    return mock
