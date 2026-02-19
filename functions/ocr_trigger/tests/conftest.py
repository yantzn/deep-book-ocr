"""ocr_trigger 用の共通テストfixture。

entrypoint が参照する docai_service を差し替え、
外部APIを呼ばずに分岐と戻り値を検証する。
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_docai_service() -> MagicMock:
    """
    entrypoint.docai_service を差し替え、モックを返す。
    """
    with patch("ocr_trigger.entrypoint.docai_service") as mock_service:
        yield mock_service
