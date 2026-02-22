"""ocr_trigger の CloudEvent シミュレーション用ローカルランナー。

目的:
- 本番と同じ start_ocr エントリポイントをローカルで検証
- GCS finalize イベント相当の入力を手元で再現
"""

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
        from dotenv import load_dotenv

        load_dotenv()
    except ModuleNotFoundError:
        pass

    required_keys = [
        "APP_ENV",
        "GCP_PROJECT_ID",
        "PROCESSOR_LOCATION",
        "PROCESSOR_ID",
        "TEMP_BUCKET",
    ]
    missing = [key for key in required_keys if not os.environ.get(key)]
    if missing:
        raise RuntimeError(
            f".env に必須キーが不足しています: {', '.join(missing)}"
        )


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
    from cloudevents.http import CloudEvent

    # import前に既定値を適用済み（必要なら実行時に上書き可能）
    input_bucket = os.environ.get("LOCAL_INPUT_BUCKET", "").strip()
    input_object = os.environ.get("LOCAL_INPUT_OBJECT", "").strip()

    if not input_bucket or not input_object:
        raise RuntimeError(
            "LOCAL_INPUT_BUCKET と LOCAL_INPUT_OBJECT を .env に設定してください。"
        )

    if ":" in input_object or "\\" in input_object or input_object.startswith("/"):
        raise RuntimeError(
            "LOCAL_INPUT_OBJECT にはローカルファイルパスではなく、"
            "GCS上のオブジェクト名（例: uploads/test.pdf）を指定してください。"
        )

    event = CloudEvent(
        attributes={
            "type": "google.cloud.storage.object.v1.finalized",
            "source": "//storage.googleapis.com/projects/_/buckets/example",
            "id": "local-test-id",
            "specversion": "1.0",
        },
        data={
            "bucket": input_bucket,
            "name": input_object,
        },
    )

    return start_ocr(event)


if __name__ == "__main__":
    print(run_local())
