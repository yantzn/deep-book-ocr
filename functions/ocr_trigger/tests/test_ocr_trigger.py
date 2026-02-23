"""ocr_trigger のエントリポイントに対する単体テスト。

確認ポイント:
- PDF入力で OCR ジョブ開始が呼ばれる
- 非PDF入力はスキップされる
- CloudEvent欠損データ時に 400 を返す
"""

from cloudevents.http import CloudEvent

from main import start_ocr


def test_start_ocr_success(mock_docai_service):
    """正常系: PDFアップロードイベントで OCR バッチジョブが開始される。"""
    event = CloudEvent(
        attributes={
            "type": "google.cloud.storage.object.v1.finalized",
            "source": "//storage.googleapis.com/projects/_/buckets/example",
            "id": "test-id",
            "specversion": "1.0",
        },
        data={"bucket": "input-bucket", "name": "file.pdf"},
    )

    msg, code = start_ocr(event)
    assert code == 200
    mock_docai_service.start_ocr_batch_job.assert_called_once_with(
        "input-bucket", "file.pdf")


def test_start_ocr_skip_non_pdf(mock_docai_service):
    """非PDFオブジェクトが安全に無視されること。"""
    event = CloudEvent(
        attributes={"type": "t", "source": "s",
                    "id": "i", "specversion": "1.0"},
        data={"bucket": "input-bucket", "name": "file.txt"},
    )

    msg, code = start_ocr(event)
    assert code == 200
    mock_docai_service.start_ocr_batch_job.assert_not_called()


def test_start_ocr_bad_event_data(mock_docai_service):
    """イベント必須フィールド欠損時に 400 を返すこと。"""
    event = CloudEvent(
        attributes={"type": "t", "source": "s",
                    "id": "i", "specversion": "1.0"},
        data={"bucket": "input-bucket"},  # name が欠損
    )

    msg, code = start_ocr(event)
    assert code == 400
