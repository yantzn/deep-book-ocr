from __future__ import annotations

"""
Cloud Functions (Gen2) / Functions Framework エントリポイント。

このファイルを実処理本体として使用する。
（python310 デプロイ要件: source 直下に main.py が必要）
"""

import json
import importlib
import logging
import os
import sys
import time
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# ローカルパッケージを動的ロードし、import順序変更の影響を受けにくくする。
config_module = importlib.import_module("md_generator.config")
gcp_services_module = importlib.import_module("md_generator.gcp_services")
markdown_logic_module = importlib.import_module("md_generator.markdown_logic")

# 以降の処理から参照しやすいように必要シンボルを束縛する。
Settings = config_module.Settings
get_settings = config_module.get_settings
build_services = gcp_services_module.build_services
build_page_chunks = markdown_logic_module.build_page_chunks
derive_output_markdown_name = markdown_logic_module.derive_output_markdown_name
extract_text_from_page_range = markdown_logic_module.extract_text_from_page_range


logger = logging.getLogger(__name__)


def setup_logging(settings: Settings) -> None:
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
            logger.info("Cloud Logging を初期化しました")
        except Exception:
            logger.exception("Cloud Logging の初期化に失敗しました")


def load_json_utf8(raw: bytes) -> dict[str, Any]:
    # OCR結果(JSON)を UTF-8 でデコードして辞書へ変換する。
    text = raw.decode("utf-8")
    return json.loads(text)


# アプリ起動時に設定・ログ・外部サービスクライアントを初期化する。
settings = get_settings()
setup_logging(settings)
services = build_services(settings)


@functions_framework.cloud_event
def generate_markdown(cloud_event: CloudEvent) -> tuple[str, int]:
    try:
        # 1) イベント基本情報を取得する（ログ/トレース用）。
        started_at = time.perf_counter()
        event_id = cloud_event.get("id")
        event_type = cloud_event.get("type")

        # 2) Cloud Storage イベントペイロードから対象オブジェクトを取り出す。
        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]
        generation = data.get("generation")

        logger.info(
            "Markdown trigger received: event_id=%s type=%s bucket=%s name=%s generation=%s",
            event_id,
            event_type,
            bucket,
            name,
            generation,
        )

        # 3) 対象が JSON でなければ処理しない。
        if not name.endswith(".json"):
            logger.info("Skipped non-JSON object: event_id=%s bucket=%s name=%s",
                        event_id, bucket, name)
            return ("JSON以外のためスキップしました。", 200)

        # 4) OCR 生成済み JSON を GCS から取得し、構造化データに変換する。
        raw = services.storage.download_bytes(bucket, name)
        logger.info("Downloaded OCR JSON: bucket=%s name=%s bytes=%d",
                    bucket, name, len(raw))

        doc = load_json_utf8(raw)

        # 5) ページ総数を確認し、チャンク分割計画を作成する。
        total_pages = len((doc.get("pages", []) or []))
        if total_pages <= 0:
            logger.warning("JSONにページが見つかりません: %s", name)
            return ("ページが存在しません。", 200)

        chunks = build_page_chunks(total_pages, settings.chunk_size)
        logger.info("Chunk plan created: total_pages=%d chunk_size=%d chunk_count=%d",
                    total_pages, settings.chunk_size, len(chunks))

        # 6) 各チャンクのテキストを Gemini へ渡して Markdown 化する。
        md_parts: list[str] = []

        for idx, ch in enumerate(chunks, start=1):
            text = extract_text_from_page_range(
                doc, ch.start_page, ch.end_page)
            # 空チャンクは API コールせずにスキップする。
            if not text.strip():
                logger.debug("Chunk empty, skipped: chunk=%d pages=%d-%d",
                             idx, ch.start_page + 1, ch.end_page)
                continue

            logger.info(
                "Gemini chunk start: chunk=%d/%d pages=%d-%d chars=%d",
                idx,
                len(chunks),
                ch.start_page + 1,
                ch.end_page,
                len(text),
            )

            try:
                # チャンク単位で Markdown 変換を実行する。
                chunk_started_at = time.perf_counter()
                md = services.gemini.to_markdown(text)
                md_parts.append(md)
                logger.info("Gemini chunk done: chunk=%d output_chars=%d elapsed_ms=%d",
                            idx, len(md), int((time.perf_counter() - chunk_started_at) * 1000))
            except Exception as e:
                # 1チャンク失敗時も全体処理は継続し、失敗情報を本文に残す。
                logger.exception(
                    "Gemini chunk failed: chunk=%d pages=%d-%d chars=%d",
                    idx,
                    ch.start_page + 1,
                    ch.end_page,
                    len(text),
                )
                md_parts.append(f"\n> [Error processing chunk {idx}: {e}]\n")

        # 7) チャンク結果を結合し、最終 Markdown を組み立てる。
        final_md = "\n\n".join(md_parts).strip()
        if not final_md:
            logger.warning("Markdownが空でした: %s", name)
            return ("Markdownが空でした。", 200)

        # 8) 出力ファイル名を決めて、出力バケットへ保存する。
        out_name = derive_output_markdown_name(name)
        services.storage.upload_text(
            settings.output_bucket, out_name, final_md)

        logger.info(
            "Markdown uploaded: output=gs://%s/%s markdown_chars=%d elapsed_ms=%d",
            settings.output_bucket,
            out_name,
            len(final_md),
            int((time.perf_counter() - started_at) * 1000),
        )
        return ("成功", 200)

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
        logger.exception("Unexpected error while generating markdown")
        return ("サーバー内部エラー", 500)


__all__ = ["generate_markdown"]
