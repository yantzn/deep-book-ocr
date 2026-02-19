# tests/test_ocr_trigger.py
import pytest
from unittest.mock import MagicMock
from cloudevents.http import CloudEvent
from ocr_trigger.entrypoint import start_ocr


def make_cloud_event(bucket: str, name: str) -> CloudEvent:
    """Helper function to create a mock CloudEvent."""
    attributes = {
        "type": "google.cloud.storage.object.v1.finalized",
        "source": f"//storage.googleapis.com/projects/_/buckets/{bucket}",
        "subject": name,
    }
    data = {"bucket": bucket, "name": name}
    return CloudEvent(attributes, data)


def test_start_ocr_non_pdf_file(mock_docai_service: MagicMock):
    """
    Test that the function correctly skips non-PDF files.
    """
    event = make_cloud_event("test-bucket", "test-file.txt")
    result, status_code = start_ocr(event)

    assert status_code == 200
    assert "Skipped non-PDF file" in result
    mock_docai_service.start_ocr_batch_job.assert_not_called()


def test_start_ocr_success(mock_docai_service: MagicMock):
    """
    Test the successful invocation of the OCR process for a PDF file.
    """
    event = make_cloud_event("test-bucket", "test-file.pdf")
    result, status_code = start_ocr(event)

    assert status_code == 200
    assert "OCR process started successfully" in result
    mock_docai_service.start_ocr_batch_job.assert_called_once_with(
        "test-bucket", "test-file.pdf"
    )

def test_start_ocr_missing_data(mock_docai_service: MagicMock):
    """
    Test that the function handles missing data in the CloudEvent.
    """
    attributes = {
        "type": "google.cloud.storage.object.v1.finalized",
        "source": "//storage.googleapis.com/projects/_/buckets/test-bucket",
    }
    data = {"bucket": "test-bucket"}
    event = CloudEvent(attributes, data)

    result, status_code = start_ocr(event)

    assert status_code == 400
    assert "Missing data in CloudEvent" in result
    mock_docai_service.start_ocr_batch_job.assert_not_called()
