from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore


class FirestoreJobStore:
    def __init__(self, settings):
        """OCR ジョブ情報を保存する Firestore コレクションを初期化する。"""
        self.settings = settings
        self.client = firestore.Client(project=settings.gcp_project_id)
        self.collection = self.client.collection(
            settings.firestore_jobs_collection)

    def now_iso(self) -> str:
        """現在時刻（UTC）を ISO8601 文字列で返す。"""
        return datetime.now(timezone.utc).isoformat()

    def build_job_id(self, bucket: str, name: str, generation: str) -> str:
        """入力オブジェクトを一意に識別できるジョブIDを生成する。"""
        # Firestore のドキュメントIDとして扱いやすいよう `/` を置換する。
        normalized_name = name.replace("/", "__")
        # generation が未設定なイベントでもID生成できるように既定値を使う。
        normalized_generation = generation or "unknown"
        return f"{bucket}__{normalized_name}__{normalized_generation}"

    def create_job(self, job_id: str, document: dict[str, Any], merge: bool = True) -> None:
        """ジョブドキュメントを作成/更新する（既定はマージ）。"""
        self.collection.document(job_id).set(document, merge=merge)

    def update_fields(self, job_id: str, fields: dict[str, Any]) -> None:
        """指定フィールドを部分更新し、更新時刻を自動付与する。"""
        payload = dict(fields)
        payload["updated_at"] = self.now_iso()
        self.collection.document(job_id).set(payload, merge=True)
