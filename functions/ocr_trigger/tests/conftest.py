"""ocr_trigger 用の共通テストfixture。

entrypoint が参照する runtime services を差し替え、
外部APIを呼ばずに分岐と戻り値を検証する。
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_docai_service() -> MagicMock:
    """
    main._get_runtime_services を差し替え、DocAIモックを返す。
    """
    with patch("main._get_runtime_services") as mock_get_runtime_services:
        mock_service = MagicMock()
        mock_job_store = MagicMock()
        mock_workflow_service = MagicMock()

        mock_service.start_ocr_batch_job.return_value = (
            "operations/local-test",
            "gs://temp-bucket/uploads/test.pdf_json/",
        )
        mock_job_store.build_job_id.return_value = "job-local-test"
        mock_job_store.now_iso.return_value = "2026-01-01T00:00:00+00:00"
        mock_workflow_service.start_docai_monitor.return_value = (
            "projects/p/locations/l/workflows/w/executions/e"
        )

        mock_get_runtime_services.return_value = (
            mock_service,
            mock_job_store,
            mock_workflow_service,
        )

        yield mock_service
