"""md_generator の CloudEvent シミュレーション用ローカルランナー。

目的:
- 本番関数と同じ entrypoint をローカルから直接呼び出し
- 実GCS の finalize イベント相当入力を手元で再現
"""

import os
import sys

from cloudevents.http import CloudEvent


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
    os.environ.setdefault("GCP_PROJECT_ID", "deep-book-ocr")
    os.environ.setdefault("GCP_LOCATION", "us-central1")
    os.environ.setdefault("MODEL_NAME", "gemini-1.5-pro")
    os.environ.setdefault("CHUNK_SIZE", "10")
    os.environ.setdefault("OUTPUT_BUCKET", "deep-book-ocr-output")


# src ディレクトリを Python path に追加
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "src")))

_bootstrap_env()

from md_generator.entrypoint import generate_markdown  # noqa: E402


def run_local():
    """
    CloudEvent を疑似生成し、関数ハンドラを呼び出す。

    実行ステップ:
    1. ローカル向けデフォルト環境変数を設定
    2. 実GCS finalize 相当の CloudEvent を構築
    3. generate_markdown() を呼び出し結果を返却

    NOTE:
    - LOCAL_INPUT_OBJECT にはローカルパスではなく、
      GCS上のオブジェクト名（例: processed/sample_pdf/0.json）を指定する。
    """
    input_bucket = os.environ.get("LOCAL_INPUT_BUCKET", "").strip()
    input_object = os.environ.get("LOCAL_INPUT_OBJECT", "").strip()

    if not input_bucket or not input_object:
        raise RuntimeError(
            "LOCAL_INPUT_BUCKET と LOCAL_INPUT_OBJECT を .env に設定してください。"
        )

    if ":" in input_object or "\\" in input_object or input_object.startswith("/"):
        raise RuntimeError(
            "LOCAL_INPUT_OBJECT にはローカルファイルパスではなく、"
            "GCS上のオブジェクト名（例: processed/sample_pdf/0.json）を指定してください。"
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
    return generate_markdown(event)


if __name__ == "__main__":
    print(run_local())
