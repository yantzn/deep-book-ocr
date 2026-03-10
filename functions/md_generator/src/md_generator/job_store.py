from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from .config import Settings


class FirestoreJobStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = firestore.Client(project=settings.gcp_project_id)
        self.collection_name = settings.firestore_jobs_collection

    def _collection(self):
        return self.client.collection(self.collection_name)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_job(self, job_id: str) -> dict[str, Any]:
        doc = self._collection().document(job_id).get()
        if not doc.exists:
            raise KeyError(f"job not found: {job_id}")
        return doc.to_dict() or {}

    def update_fields(self, job_id: str, fields: dict[str, Any]) -> None:
        payload = dict(fields)
        payload["updated_at"] = self.now_iso()
        self._collection().document(job_id).set(payload, merge=True)
