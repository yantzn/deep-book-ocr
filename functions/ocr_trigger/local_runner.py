"""
ocr_trigger の CloudEvent シミュレーション用ローカルランナー。

目的:
- 本番と同じ start_ocr エントリポイントをローカルで検証
- GCS finalize イベント相当の入力を手元で再現

NOTE:
- Document AI の input は実GCS (gs://) が必要
- ローカル検証でも、PDFは実バケットに置いて bucket/name を指定する想定
"""

from __future__ import annotations

import os
import sys


def _ensure_venv_python() -> None:
    """システムPython実行時は .venv のPythonで再実行する。"""
    base_dir = os.path.dirname(__file__)
    venv_python = os.path.join(base_dir, ".venv", "bin", "python")
    if not os.path.exists(venv_python):
        return

    in_venv = (sys.prefix != getattr(sys, "base_prefix", sys.prefix)) or bool(
        os.environ.get("VIRTUAL_ENV")
    )
    if in_venv:
        return

    os.execv(venv_python, [venv_python, __file__, *sys.argv[1:]])


_ensure_venv_python()


def _bootstrap_env() -> None:
    """.env を読み込み、必須キーの存在を検証する。"""
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except ModuleNotFoundError:
        pass

    required_keys = [
        "APP_ENV",
        "GCP_PROJECT_ID",
        "PROCESSOR_LOCATION",
        "PROCESSOR_ID",
        "TEMP_BUCKET",
        # ローカル実行用の入力指定
        "LOCAL_INPUT_BUCKET",
        "LOCAL_INPUT_OBJECT",
    ]
    missing = [key for key in required_keys if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f".env に必須キーが不足しています: {', '.join(missing)}")

    # src ディレクトリを Python path に追加
    sys.path.insert(0, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "src")))


_bootstrap_env()

from cloudevents.http import CloudEvent  # noqa: E402
from main import start_ocr  # noqa: E402


def run_local() -> dict:
    """
    1) CloudEvent を疑似生成
    2) start_ocr() を呼び出す
    """
    input_bucket = os.environ["LOCAL_INPUT_BUCKET"].strip()
    input_object = os.environ["LOCAL_INPUT_OBJECT"].strip()

    if ":" in input_object or "\\" in input_object or input_object.startswith("/"):
        raise RuntimeError(
            "LOCAL_INPUT_OBJECT にはローカルファイルパスではなく、"
            "GCS上のオブジェクト名（例: uploads/test.pdf）を指定してください。"
        )

    event = CloudEvent(
        attributes={
            "type": "google.cloud.storage.object.v1.finalized",
            "source": f"//storage.googleapis.com/projects/_/buckets/{input_bucket}",
            "id": "local-test-id",
            "specversion": "1.0",
        },
        data={
            "bucket": input_bucket,
            "name": input_object,
            "contentType": "application/pdf",
        },
    )

    return start_ocr(event)


if __name__ == "__main__":
    print(run_local())
