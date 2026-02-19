# src/ocr_trigger/main.py
import logging
import functions_framework
from cloudevents.http import CloudEvent

from . import config
from . import gcp_services

# Initialize services with cached settings
settings = config.get_settings()
docai_service = gcp_services.DocumentAIService(settings)

logging.basicConfig(level=logging.INFO)


@functions_framework.cloud_event
def start_ocr(cloud_event: CloudEvent):
    """
    Cloud Function entry point that triggers the OCR process.

    This function is triggered by a CloudEvent (e.g., a file upload to GCS).
    """
    try:
        data = cloud_event.data
        bucket = data["bucket"]
        name = data["name"]

        if not name.lower().endswith(".pdf"):
            logging.info(f"Skipping non-PDF file: {name}")
            return "Skipped non-PDF file.", 200

        docai_service.start_ocr_batch_job(bucket, name)

        return "OCR process started successfully.", 200

    except KeyError as e:
        logging.error(f"Invalid CloudEvent data. Missing key: {e}")
        return f"Bad Request: Missing data in CloudEvent: {e}", 400
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return "Internal Server Error", 500
