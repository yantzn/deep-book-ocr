from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore


class FirestoreJobStore:
    def __init__(self, settings):
        self.settings = settings
        self.client = firestore.Client(project=settings.gcp_project_id)
        self.collection = self.client.collection(
            settings.firestore_jobs_collection)

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def build_job_id(self, bucket: str, name: str, generation: str) -> str:
        normalized_name = name.replace("/", "__")
        normalized_generation = generation or "unknown"
        return f"{bucket}__{normalized_name}__{normalized_generation}"

    def create_job(self, job_id: str, document: dict[str, Any], merge: bool = True) -> None:
        self.collection.document(job_id).set(document, merge=merge)

    def update_fields(self, job_id: str, fields: dict[str, Any]) -> None:
        payload = dict(fields)
        payload["updated_at"] = self.now_iso()
        self.collection.document(job_id).set(payload, merge=True)
