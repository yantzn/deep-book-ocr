# tests/conftest.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_docai_service() -> MagicMock:
    """
    Fixture that mocks the DocumentAIService.
    """
    with patch("ocr_trigger.entrypoint.docai_service") as mock_service:
        yield mock_service