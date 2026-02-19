# local_runner.py
import os
import sys
from unittest.mock import MagicMock
from cloudevents.http import CloudEvent

# Add the src directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from ocr_trigger.main import start_ocr


def run_local():
    """
    Simulates a CloudEvent and calls the main function handler.
    This is for local testing purposes.
    """
    # --- Configuration for the local run ---
    # Set environment variables for the function to use.
    # In a real scenario, these would be set in your cloud environment.
    os.environ["GCP_PROJECT_ID"] = "your-gcp-project-id"
    os.environ["PROCESSOR_LOCATION"] = "us"  # e.g., 'us' or 'eu'
    os.environ["PROCESSOR_ID"] = "your-processor-id"
    os.environ["TEMP_BUCKET"] = "gs://your-temp-bucket-for-json-output"

    # The "event" payload that the function will receive.
    # This simulates a file being uploaded to GCS.
    bucket_name = "your-source-bucket"
    file_name = "sample.pdf"  # This file should exist in `local_input`

    print("--- Starting local execution of start_ocr function ---")
    print(f"Simulating event for file: {file_name} in bucket: {bucket_name}")
    print("Using environment variables for configuration:")
    print(f"  PROJECT_ID: {os.environ.get('GCP_PROJECT_ID')}")
    print(f"  LOCATION: {os.environ.get('PROCESSOR_LOCATION')}")
    print(f"  PROCESSOR_ID: {os.environ.get('PROCESSOR_ID')}")
    print(f"  TEMP_BUCKET: {os.environ.get('TEMP_BUCKET')}")
    print("-" * 20)

    # Create a mock CloudEvent
    attributes = {
        "type": "google.cloud.storage.object.v1.finalized",
        "source": f"//storage.googleapis.com/projects/_/buckets/{bucket_name}",
        "subject": file_name,
    }
    data = {"bucket": bucket_name, "name": file_name}
    event = CloudEvent(attributes, data)

    # In a local test, you might not want to make real API calls.
    # You can mock the service like in the tests.
    # For a true integration test, you would need to be authenticated to GCP.
    try:
        # For this example, we'll just print the call instead of making it.
        # To run for real, remove the mocking.
        with MagicMock() as mock_docai_service:
            from ocr_trigger.main import docai_service
            docai_service.start_ocr_batch_job = mock_docai_service.start_ocr_batch_job

            result, status_code = start_ocr(event)

            print(f"Function returned: {result} (Status code: {status_code})")

            if mock_docai_service.start_ocr_batch_job.called:
                print("
Successfully called the Document AI service with:")
                print(f"  Bucket: {mock_docai_service.start_ocr_batch_job.call_args.args[0]}")
                print(f"  File Name: {mock_docai_service.start_ocr_batch_job.call_args.args[1]}")
            else:
                print("
Document AI service was not called.")

    except Exception as e:
        print(f"
An error occurred during execution: {e}")

    print("
--- Local execution finished ---")


if __name__ == "__main__":
    run_local()
