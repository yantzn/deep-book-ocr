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
import uuid
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent
from google.api_core.exceptions import NotFound

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
derive_json_group_prefix = markdown_logic_module.derive_json_group_prefix
derive_output_markdown_name = markdown_logic_module.derive_output_markdown_name
extract_text_from_page_range = markdown_logic_module.extract_text_from_page_range
sort_json_object_names = markdown_logic_module.sort_json_object_names


logger = logging.getLogger(__name__)

# cold start 判定
_COLD_START = True


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


def _safe_event_context(event: CloudEvent) -> dict[str, Any]:
    data = event.data or {}
    return {
        "id": getattr(event, "get", lambda *_: None)("id"),
        "source": getattr(event, "get", lambda *_: None)("source"),
        "type": getattr(event, "get", lambda *_: None)("type"),
        "subject": getattr(event, "get", lambda *_: None)("subject"),
        "bucket": data.get("bucket"),
        "name": data.get("name"),
        "contentType": data.get("contentType"),
        "metageneration": data.get("metageneration"),
        "generation": data.get("generation"),
        "timeCreated": data.get("timeCreated"),
        "updated": data.get("updated"),
    }


def _download_json_with_retry(
    services: Any,
    bucket: str,
    object_name: str,
    request_id: str,
    max_attempts: int = 3,
    base_sleep_sec: float = 1.0,
) -> bytes:
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "[%s] download_attempt_started object=%s attempt=%d/%d",
                request_id,
                object_name,
                attempt,
                max_attempts,
            )
            data = services.storage.download_bytes(bucket, object_name)
            logger.info(
                "[%s] download_attempt_succeeded object=%s attempt=%d/%d bytes=%d",
                request_id,
                object_name,
                attempt,
                max_attempts,
                len(data),
            )
            return data
        except NotFound:
            if attempt >= max_attempts:
                logger.exception(
                    "[%s] download_attempt_failed_not_found object=%s attempt=%d/%d (giving up)",
                    request_id,
                    object_name,
                    attempt,
                    max_attempts,
                )
                raise

            sleep_sec = base_sleep_sec * attempt
            logger.warning(
                "[%s] download_attempt_not_found_retrying object=%s attempt=%d/%d sleep_sec=%.1f",
                request_id,
                object_name,
                attempt,
                max_attempts,
                sleep_sec,
            )
            time.sleep(sleep_sec)


@functions_framework.cloud_event
def generate_markdown(cloud_event: CloudEvent) -> tuple[str, int]:
    global _COLD_START

    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]
    cold_start = _COLD_START
    _COLD_START = False

    try:
        settings = get_settings()
        setup_logging(settings)
        services = build_services(settings)

        logger.info(
            "[%s] generate_markdown entered cold_start=%s pid=%s service=%s revision=%s",
            request_id,
            cold_start,
            os.getpid(),
            os.getenv("K_SERVICE", ""),
            os.getenv("K_REVISION", ""),
        )

        # 1) イベント基本情報を取得する（ログ/トレース用）。
        event_id = cloud_event.get("id")
        event_type = cloud_event.get("type")

        # 2) Cloud Storage イベントペイロードから対象オブジェクトを取り出す。
        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]
        generation = data.get("generation")

        logger.info(
            "[%s] markdown_trigger_received event_id=%s type=%s bucket=%s name=%s generation=%s",
            request_id,
            event_id,
            event_type,
            bucket,
            name,
            generation,
        )

        logger.info(
            "[%s] event_summary=%s",
            request_id,
            json.dumps(_safe_event_context(cloud_event),
                       ensure_ascii=False, default=str),
        )

        logger.info(
            "[%s] settings_summary project=%s location=%s model=%s chunk_size=%s output_bucket=%s is_gcp=%s",
            request_id,
            settings.gcp_project_id,
            settings.gcp_location,
            settings.model_name,
            settings.chunk_size,
            settings.output_bucket,
            settings.is_gcp,
        )

        # 3) 対象が JSON でなければ処理しない。
        if not name.endswith(".json"):
            logger.info("[%s] skipped_non_json_object event_id=%s bucket=%s name=%s",
                        request_id, event_id, bucket, name)
            return ("JSON以外のためスキップしました。", 200)

        # 4) 同一OCR結果グループ配下のJSONを列挙して処理対象を確定する。
        group_prefix = derive_json_group_prefix(name)

        listing_started = time.perf_counter()
        logger.info(
            "[%s] about_to_list_json_group bucket=%s prefix=%s trigger=%s",
            request_id,
            bucket,
            group_prefix,
            name,
        )
        all_objects = services.storage.list_object_names(bucket, group_prefix)
        json_objects = [obj for obj in all_objects if obj.endswith(".json")]
        if name not in json_objects:
            json_objects.append(name)
        json_objects = sort_json_object_names(json_objects)

        logger.info(
            "[%s] json_group_resolved bucket=%s trigger=%s prefix=%s object_count=%d json_count=%d elapsed_ms=%d",
            request_id,
            bucket,
            name,
            group_prefix,
            len(all_objects),
            len(json_objects),
            int((time.perf_counter() - listing_started) * 1000),
        )

        # 5) すべてのJSONを順次読み込み、チャンク単位で Markdown 化する。
        md_parts: list[str] = []
        chunk_index = 0

        for obj_name in json_objects:
            object_started = time.perf_counter()
            logger.info("[%s] object_processing_started object=%s",
                        request_id, obj_name)

            raw = _download_json_with_retry(
                services=services,
                bucket=bucket,
                object_name=obj_name,
                request_id=request_id,
            )
            logger.info(
                "[%s] downloaded_ocr_json bucket=%s name=%s bytes=%d",
                request_id,
                bucket,
                obj_name,
                len(raw),
            )

            doc = load_json_utf8(raw)
            total_pages = len((doc.get("pages", []) or []))
            if total_pages <= 0:
                logger.warning("[%s] no_pages_found_in_json object=%s",
                               request_id, obj_name)
                continue

            chunks = build_page_chunks(total_pages, settings.chunk_size)
            logger.info(
                "[%s] chunk_plan_created object=%s total_pages=%d chunk_size=%d chunk_count=%d",
                request_id,
                obj_name,
                total_pages,
                settings.chunk_size,
                len(chunks),
            )

            for ch in chunks:
                chunk_index += 1
                text = extract_text_from_page_range(
                    doc, ch.start_page, ch.end_page)
                # 空チャンクは API コールせずにスキップする。
                if not text.strip():
                    logger.debug(
                        "[%s] chunk_empty_skipped object=%s chunk=%d pages=%d-%d",
                        request_id,
                        obj_name,
                        chunk_index,
                        ch.start_page + 1,
                        ch.end_page,
                    )
                    continue

                logger.info(
                    "[%s] gemini_chunk_started object=%s chunk=%d pages=%d-%d chars=%d",
                    request_id,
                    obj_name,
                    chunk_index,
                    ch.start_page + 1,
                    ch.end_page,
                    len(text),
                )

                try:
                    # チャンク単位で Markdown 変換を実行する。
                    chunk_started_at = time.perf_counter()
                    md = services.gemini.to_markdown(text)
                    md_parts.append(md)
                    logger.info(
                        "[%s] gemini_chunk_done object=%s chunk=%d output_chars=%d elapsed_ms=%d",
                        request_id,
                        obj_name,
                        chunk_index,
                        len(md),
                        int((time.perf_counter() - chunk_started_at) * 1000),
                    )
                except Exception as e:
                    # 1チャンク失敗時も全体処理は継続し、失敗情報を本文に残す。
                    logger.exception(
                        "[%s] gemini_chunk_failed object=%s chunk=%d pages=%d-%d chars=%d",
                        request_id,
                        obj_name,
                        chunk_index,
                        ch.start_page + 1,
                        ch.end_page,
                        len(text),
                    )
                    md_parts.append(
                        f"\n> [Error processing chunk {chunk_index} from {obj_name}: {e}]\n"
                    )

            logger.info(
                "[%s] object_processing_finished object=%s elapsed_ms=%d",
                request_id,
                obj_name,
                int((time.perf_counter() - object_started) * 1000),
            )

        # 7) チャンク結果を結合し、最終 Markdown を組み立てる。
        final_md = "\n\n".join(md_parts).strip()
        if not final_md:
            logger.warning("[%s] markdown_empty trigger=%s",
                           request_id, name)
            return ("Markdownが空でした。", 200)

        # 8) 出力ファイル名を決めて、出力バケットへ保存する。
        out_name = derive_output_markdown_name(name)
        upload_started = time.perf_counter()
        services.storage.upload_text(
            settings.output_bucket, out_name, final_md)

        logger.info(
            "[%s] markdown_uploaded output=gs://%s/%s markdown_chars=%d upload_elapsed_ms=%d total_elapsed_ms=%d",
            request_id,
            settings.output_bucket,
            out_name,
            len(final_md),
            int((time.perf_counter() - upload_started) * 1000),
            int((time.perf_counter() - started_at) * 1000),
        )
        return ("成功", 200)

    except KeyError as e:
        # 必須キー不足は 400 として呼び出し元へ返す。
        logger.error(
            "[%s] invalid_cloudevent_payload missing_key=%s payload_keys=%s",
            request_id,
            e,
            sorted((cloud_event.data or {}).keys()),
        )
        return (f"不正なリクエスト: CloudEventのデータが不足しています: {e}", 400)

    except Exception:
        # 想定外の失敗は 500 として扱う。
        logger.exception(
            "[%s] unexpected_error_while_generating_markdown", request_id)
        return ("サーバー内部エラー", 500)

    finally:
        logger.info(
            "[%s] generate_markdown finished total_elapsed_ms=%s",
            request_id,
            int((time.perf_counter() - started_at) * 1000),
        )


__all__ = ["generate_markdown"]
