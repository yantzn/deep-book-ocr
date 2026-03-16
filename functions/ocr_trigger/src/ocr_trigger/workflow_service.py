from __future__ import annotations

import json

from google.cloud.workflows.executions_v1 import ExecutionsClient
from google.cloud.workflows.executions_v1.types import Execution


class WorkflowExecutionService:
    def __init__(self, settings):
        self.settings = settings
        self.client = ExecutionsClient()

    def start_docai_monitor(self, job_id: str, operation_name: str) -> str:
        workflow_path = self.client.workflow_path(
            self.settings.gcp_project_id,
            self.settings.workflow_region,
            self.settings.docai_monitor_workflow_name,
        )

        payload = {
            "job_id": job_id,
            "operation_name": operation_name,
        }

        execution = Execution(argument=json.dumps(payload, ensure_ascii=False))
        response = self.client.create_execution(
            parent=workflow_path, execution=execution)
        return response.name
