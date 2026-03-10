from __future__ import annotations

import os
import sys

from flask import Flask, request


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
        from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]

        load_dotenv()
    except ModuleNotFoundError:
        pass

    required = [
        "APP_ENV",
        "GCP_PROJECT_ID",
        "OUTPUT_BUCKET",
        "LOCAL_JOB_ID",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f".env に必須キーが不足しています: {', '.join(missing)}")

    sys.path.insert(0, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "src")))


_ensure_venv_python()
_bootstrap_env()

from main import generate_markdown  # noqa: E402


app = Flask(__name__)


def run_local():
    job_id = os.environ["LOCAL_JOB_ID"].strip()
    if not job_id:
        raise RuntimeError("LOCAL_JOB_ID を指定してください。")

    trace_header = os.environ.get(
        "LOCAL_TRACE_CONTEXT",
        "local-trace-id/0;o=1",
    )

    with app.test_request_context(
        path="/",
        method="POST",
        json={"job_id": job_id},
        headers={"X-Cloud-Trace-Context": trace_header},
    ):
        return generate_markdown(request)


if __name__ == "__main__":
    print(run_local())
