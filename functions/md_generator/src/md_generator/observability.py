from __future__ import annotations

import json
import logging
import os
from typing import Any


def parse_trace_id(trace_header: str | None) -> str | None:
    # Cloud Run/Functions で付与される `X-Cloud-Trace-Context` から
    # 先頭の trace id 部分だけを取り出す。
    # 形式: TRACE_ID/SPAN_ID;o=TRACE_TRUE のため `/` 手前を採用する。
    if not trace_header:
        return None
    return trace_header.split("/", 1)[0] or None


def log_pipeline_event(
    logger: logging.Logger,
    *,
    level: int,
    event: str,
    stage: str,
    request_id: str | None = None,
    job_id: str | None = None,
    trace_id: str | None = None,
    **fields: Any,
) -> None:
    # Cloud Logging で検索しやすい最小共通キーを組み立てる。
    # - event: 処理の大分類（例: generate_markdown, start_ocr）
    # - stage: 現在の処理段階（例: request_received, failed）
    # - request_id/job_id/trace_id: 相関ID
    payload: dict[str, Any] = {
        "event": event,
        "stage": stage,
        "request_id": request_id,
        "job_id": job_id,
        "trace_id": trace_id,
        # 実行中リビジョンを付与し、デプロイ差分による挙動差の追跡を容易にする。
        "service": os.getenv("K_SERVICE", ""),
        "revision": os.getenv("K_REVISION", ""),
    }
    # 呼び出し側の追加情報（elapsed_ms, output_uri など）をマージする。
    payload.update(fields)
    # ノイズを減らすため、空値(None/"")は出力しない。
    compact = {k: v for k, v in payload.items() if v not in (None, "")}
    # JSON文字列として1行出力し、Cloud Loggingでのフィルタ・集計をしやすくする。
    logger.log(level, json.dumps(compact, ensure_ascii=False, default=str))
