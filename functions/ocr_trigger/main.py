from __future__ import annotations

"""
Cloud Functions (Gen2) / Functions Framework エントリポイント。

このファイルを実処理本体として使用する。
（python310 デプロイ要件: source 直下に main.py が必要）
"""

import logging
import importlib
import os
import sys
import time
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# ローカルパッケージを動的ロードし、import順序変更の影響を受けにくくする。
config = importlib.import_module("ocr_trigger.config")
gcp_services = importlib.import_module("ocr_trigger.gcp_services")


logger = logging.getLogger(__name__)


def setup_logging(settings: config.Settings) -> None:
    # 設定値に応じてログレベルを決定する。
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    # ローカル実行/Cloud Functions の両方で重複初期化を避けつつ logger を設定する。
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        root.setLevel(level)

    logger.info("Logging configured: level=%s app_env=%s",
                level_name, settings.app_env)

    # GCP 実行時のみ Cloud Logging 連携を有効化する。
    if settings.is_gcp:
        try:
            import google.cloud.logging as cloud_logging

            cloud_logging.Client().setup_logging()
            logger.info("Cloud Logging initialized")
        except Exception:
            logger.exception("Failed to initialize Cloud Logging")


# アプリ起動時に設定・ログ・外部サービスクライアントを初期化する。
settings = config.get_settings()
setup_logging(settings)
services = gcp_services.build_services(settings)
docai_service = services.docai_service


@functions_framework.cloud_event
def start_ocr(cloud_event: CloudEvent) -> tuple[str, int]:
    try:
        # 1) イベント基本情報を取得する（ログ/トレース用）。
        event_id = cloud_event.get("id")
        event_type = cloud_event.get("type")
        # 2) Cloud Storage イベントペイロードから対象オブジェクトを取り出す。
        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]
        generation = data.get("generation")

        logger.info(
            "OCR trigger received: event_id=%s type=%s bucket=%s name=%s generation=%s",
            event_id,
            event_type,
            bucket,
            name,
            generation,
        )

        # 3) PDF 以外は処理対象外としてスキップする。
        if not name.lower().endswith(".pdf"):
            logger.info(
                "Skipped non-PDF object: event_id=%s bucket=%s name=%s",
                event_id,
                bucket,
                name,
            )
            return ("PDF以外のためスキップしました。", 200)

        # 4) Document AI の非同期バッチ処理を起動する。
        started_at = time.perf_counter()
        op_name = docai_service.start_ocr_batch_job(bucket, name)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        output_prefix = f"{settings.temp_bucket_uri()}{name}_json/"

        logger.info(
            "OCR batch submitted: event_id=%s operation=%s output_prefix=%s elapsed_ms=%d",
            event_id,
            op_name,
            output_prefix,
            elapsed_ms,
        )
        return ("OCR処理を開始しました。", 200)

    except KeyError as e:
        # 必須キー不足は 400 として呼び出し元へ返す。
        logger.error(
            "Invalid CloudEvent payload: missing_key=%s payload_keys=%s",
            e,
            sorted((cloud_event.data or {}).keys()),
        )
        return (f"不正なリクエスト: CloudEventのデータが不足しています: {e}", 400)

    except Exception:
        # 想定外の失敗は 500 として扱う。
        logger.exception("Unexpected error while submitting OCR batch")
        return ("サーバー内部エラー", 500)


__all__ = ["start_ocr"]
