from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from .config import Settings


class FirestoreJobStore:
    # OCR/Markdown 処理のジョブ状態を Firestore に保存・取得する薄いラッパ。
    # ここではデータ構造の厳密バリデーションは行わず、読み書き責務に限定する。
    def __init__(self, settings: Settings):
        self.settings = settings
        # Cloud Functions 実行プロジェクトに紐づく Firestore クライアントを初期化。
        self.client = firestore.Client(project=settings.gcp_project_id)
        # ステータス管理に使うコレクション名（例: ocr_jobs）。
        self.collection_name = settings.firestore_jobs_collection

    def _collection(self):
        # 呼び出し元で collection 名を意識しなくてよいように集約する。
        return self.client.collection(self.collection_name)

    @staticmethod
    def now_iso() -> str:
        # 監査・追跡しやすいよう UTC の ISO 8601 文字列で時刻を統一する。
        return datetime.now(timezone.utc).isoformat()

    def get_job(self, job_id: str) -> dict[str, Any]:
        # 指定 job_id のドキュメントを取得する。
        # 存在しない場合は呼び出し側で 404/失敗処理へ分岐できるよう KeyError を投げる。
        doc = self._collection().document(job_id).get()
        if not doc.exists:
            raise KeyError(f"job not found: {job_id}")
        return doc.to_dict() or {}

    def update_fields(self, job_id: str, fields: dict[str, Any]) -> None:
        # 部分更新（merge=True）で既存フィールドを保持しつつ状態を上書きする。
        # すべての更新に updated_at を付与し、最終更新時刻を一元管理する。
        payload = dict(fields)
        payload["updated_at"] = self.now_iso()
        self._collection().document(job_id).set(payload, merge=True)
