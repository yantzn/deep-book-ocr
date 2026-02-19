"""md_generator の CloudEvent シミュレーション用ローカルランナー。

目的:
- 本番関数と同じ entrypoint をローカルから直接呼び出し
- イベント形状と環境変数の最小セットを再現
"""

from google.cloud import storage
from google.auth.credentials import AnonymousCredentials
from cloudevents.http import CloudEvent
import json
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
    """entrypoint import前に必要な環境変数の既定値を設定する。"""
    os.environ.setdefault("APP_ENV", "local")
    os.environ.setdefault("STORAGE_MODE", "emulator")
    os.environ.setdefault("GCP_PROJECT_ID", "deep-book-ocr")
    os.environ.setdefault("GCP_LOCATION", "us-central1")
    os.environ.setdefault("MODEL_NAME", "gemini-1.5-pro")
    os.environ.setdefault("CHUNK_SIZE", "10")
    os.environ.setdefault("GCS_EMULATOR_HOST", "http://localhost:4443")
    os.environ.setdefault("EMULATOR_INPUT_BUCKET", "temp-local")
    os.environ.setdefault("EMULATOR_OUTPUT_BUCKET", "output-local")
    os.environ.setdefault("OUTPUT_BUCKET", "deep-book-ocr-output")


# src ディレクトリを Python path に追加
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "src")))

_bootstrap_env()

from md_generator.entrypoint import generate_markdown  # noqa: E402


def _seed_emulator_input() -> None:
    """エミュレータ用の入力JSONが無い場合に最小サンプルを投入する。"""
    if os.environ.get("STORAGE_MODE", "emulator").lower() != "emulator":
        return

    bucket = os.environ.get("EMULATOR_INPUT_BUCKET", "temp-local")
    object_name = "processed/sample_pdf/0.json"
    emulator_host = os.environ.get(
        "GCS_EMULATOR_HOST", "http://localhost:4443")

    client = storage.Client(
        project="local",
        client_options={"api_endpoint": emulator_host},
        credentials=AnonymousCredentials(),
    )

    bucket_ref = client.bucket(bucket)
    if not bucket_ref.exists():
        bucket_ref.create()

    blob = bucket_ref.blob(object_name)
    if blob.exists():
        return

    sample_docai = {
        "text": "hello world",
        "pages": [
            {"layout": {"textAnchor": {"textSegments": [
                {"startIndex": 0, "endIndex": 5}]}}},
            {"layout": {"textAnchor": {"textSegments": [
                {"startIndex": 6, "endIndex": 11}]}}},
        ],
    }
    blob.upload_from_string(json.dumps(sample_docai),
                            content_type="application/json")


def run_local():
    """
    CloudEvent を疑似生成し、関数ハンドラを呼び出す。

    実行ステップ:
    1. ローカル向けデフォルト環境変数を設定
    2. GCS finalize 相当の CloudEvent を構築
    3. generate_markdown() を呼び出し結果を返却

     推奨するローカルデバッグモード:
    1) STORAGE_MODE=emulator:
         - JSONを fake-gcs-server のバケット（EMULATOR_INPUT_BUCKET）へ配置
         - 出力は EMULATOR_OUTPUT_BUCKET へ保存
         - Gemini は ADC を使って実GCPへ接続

    2) STORAGE_MODE=gcp:
         - 実GCSからJSONを読み込み、実GCSへ書き込む
    """
    # import前に既定値を適用済み（必要なら実行時に上書き可能）

    _seed_emulator_input()

    event = CloudEvent(
        attributes={
            "type": "google.cloud.storage.object.v1.finalized",
            "source": "//storage.googleapis.com/projects/_/buckets/example",
            "id": "local-test-id",
            "specversion": "1.0",
        },
        data={
            # STORAGE_MODE=emulator の場合、bucketは entrypoint 内で EMULATOR_INPUT_BUCKET に差し替えられる
            "bucket": "ignored-in-emulator",
            "name": "processed/sample_pdf/0.json",
        },
    )
    return generate_markdown(event)


if __name__ == "__main__":
    print(run_local())
