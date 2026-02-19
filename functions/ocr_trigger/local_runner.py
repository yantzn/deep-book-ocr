"""ocr_trigger の CloudEvent シミュレーション用ローカルランナー。

目的:
- 本番と同じ start_ocr エントリポイントをローカルで検証
- GCS finalize イベント相当の入力を手元で再現
"""

import os
import sys
from cloudevents.http import CloudEvent


def _bootstrap_env() -> None:
    """entrypoint import前に必要な環境変数の既定値を設定する。"""
    os.environ.setdefault("APP_ENV", "local")
    os.environ.setdefault("GCP_PROJECT_ID", "deep-book-ocr")
    os.environ.setdefault("PROCESSOR_LOCATION", "us")
    os.environ.setdefault("PROCESSOR_ID", "YOUR_PROCESSOR_ID")
    os.environ.setdefault("TEMP_BUCKET", "gs://deep-book-ocr-temp")


# src ディレクトリを Python path に追加
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "src")))

_bootstrap_env()

# ✅ 正しいエントリポイントに修正
from ocr_trigger.entrypoint import start_ocr  # noqa: E402


def run_local():
    """
    CloudEvent を疑似生成し、関数ハンドラを呼び出す。

    実行ステップ:
    1. OCR実行に必要な環境変数のデフォルトを設定
    2. PDFアップロード相当の CloudEvent を組み立て
    3. start_ocr() を呼び出して結果を返す
    NOTE: Document AI の入出力には実GCS（gs://）が必要。
    ローカル検証時は、PDFを実バケットに配置して bucket/name を指定する。
    """
    # import前に既定値を適用済み（必要なら実行時に上書き可能）

    event = CloudEvent(
        attributes={
            "type": "google.cloud.storage.object.v1.finalized",
            "source": "//storage.googleapis.com/projects/_/buckets/example",
            "id": "local-test-id",
            "specversion": "1.0",
        },
        data={
            "bucket": "YOUR_REAL_INPUT_BUCKET",
            "name": "path/to/your.pdf",
        },
    )

    return start_ocr(event)


if __name__ == "__main__":
    print(run_local())
