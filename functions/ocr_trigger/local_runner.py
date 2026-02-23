"""
ocr_trigger の CloudEvent シミュレーション用ローカルランナー。

- 本番と同じ start_ocr エントリポイントをローカルで検証
- GCS finalize イベント相当の入力を再現
"""

from __future__ import annotations

import os
import sys

from cloudevents.http import CloudEvent


def _ensure_venv_python() -> None:
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


def _bootstrap_env() -> None:
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
        "LOCAL_INPUT_BUCKET",
        "LOCAL_INPUT_OBJECT",
    ]
    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f".env に必須キーが不足しています: {', '.join(missing)}")

    # src を import できるようにする
    sys.path.insert(0, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "src")))


_ensure_venv_python()
_bootstrap_env()

from main import start_ocr  # noqa: E402


def run_local():
    bucket = os.environ["LOCAL_INPUT_BUCKET"].strip()
    name = os.environ["LOCAL_INPUT_OBJECT"].strip()

    if ":" in name or "\\" in name or name.startswith("/"):
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
        data={"bucket": bucket, "name": name},
    )
    return start_ocr(event)


if __name__ == "__main__":
    print(run_local())
