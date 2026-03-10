from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse

from google.cloud import storage
from vertexai import init as vertexai_init
from vertexai.generative_models import GenerativeModel

from .config import Settings


def _parse_gs_uri(gs_uri: str) -> tuple[str, str]:
    # `gs://bucket/prefix...` を (bucket, prefix) へ分解する共通ヘルパ。
    # Storage API 呼び出し前に形式不正を早期検知する。
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"Invalid gs:// URI: {gs_uri}")
    parsed = urlparse(gs_uri)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")
    return bucket, prefix


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        # すべての GCS 操作を同一 project コンテキストで実行する。
        self.client = storage.Client(project=settings.gcp_project_id)

    def list_object_names(self, bucket_name: str, prefix: str) -> list[str]:
        # OCR 出力 JSON はページ順の処理が重要なため、呼び出し側で
        # 安定して扱えるよう名前順ソートで返す。
        blobs = self.client.list_blobs(
            bucket_or_name=bucket_name, prefix=prefix)
        return sorted(blob.name for blob in blobs)

    def list_object_names_from_gs_uri(self, gs_uri_prefix: str) -> list[str]:
        bucket, prefix = _parse_gs_uri(gs_uri_prefix)
        return self.list_object_names(bucket_name=bucket, prefix=prefix)

    def download_json_documents_from_gs_uri_prefix(self, gs_uri_prefix: str) -> list[dict]:
        # DocAI の出力プレフィックス配下から JSON のみを読み込む。
        # メタファイル等が混在しても `.json` 以外は無視する。
        bucket_name, prefix = _parse_gs_uri(gs_uri_prefix)
        bucket = self.client.bucket(bucket_name)
        object_names = self.list_object_names(bucket_name, prefix)

        docs: list[dict] = []
        for object_name in object_names:
            if not object_name.endswith(".json"):
                continue
            blob = bucket.blob(object_name)
            raw = blob.download_as_text(encoding="utf-8")
            docs.append(json.loads(raw))
        return docs

    def write_markdown(self, bucket_name: str, object_name: str, markdown: str) -> str:
        # 最終成果物を UTF-8 Markdown として保存し、追跡用に gs:// URI を返す。
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(
            markdown, content_type="text/markdown; charset=utf-8")
        return f"gs://{bucket_name}/{object_name}"


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Vertex AI 初期化はプロセス単位で一度行い、以後同モデルを再利用する。
        vertexai_init(project=settings.gcp_project_id,
                      location=settings.gcp_location)
        self.model = GenerativeModel(settings.gemini_model_name)

    def polish_markdown(self, draft_markdown: str) -> str:
        # OCR 生テキストの体裁のみを整える用途。
        # 事実追加や要約を抑止するため、プロンプトで明示的に制約する。
        prompt = f"""
あなたはOCR後テキストをMarkdownへ整形する編集者です。
以下のルールを守ってください。

ルール:
- 事実を追加しない
- 原文を勝手に要約しない
- 見出しらしい行は #, ##, ### に整形してよい
- 箇条書きらしい行は Markdown リストに整形してよい
- ページ番号、ヘッダ、フッタ、重複行、明らかなOCRノイズは除去してよい
- 段落は自然な単位でまとめる
- 文章順は原則維持
- 表は完全再構築できない場合、無理に表にせずテキストとして崩さず残す
- 日本語の不自然な改行は修正してよい
- 出力はMarkdown本文のみ
- コードフェンスは使わない

入力テキスト:
{draft_markdown[: self.settings.gemini_max_input_chars]}
"""
        response = self.model.generate_content(prompt)
        text = getattr(response, "text", "") or ""
        return text.strip()


@dataclass(frozen=True)
class Services:
    # エントリーポイント側が依存を1つの束として受け取れるようにする。
    storage_service: StorageService
    llm_service: LLMService


def build_services(settings: Settings) -> Services:
    # 外部サービス依存の生成を1箇所に集約し、テスト時の差し替えを容易にする。
    return Services(
        storage_service=StorageService(settings),
        llm_service=LLMService(settings),
    )
