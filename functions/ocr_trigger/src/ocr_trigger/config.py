# src/ocr_trigger/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuration for the ocr_trigger function.

    Reads settings from environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    gcp_project_id: str = "deep-book-ocr"
    processor_location: str = "us"
    processor_id: str
    temp_bucket: str


def get_settings() -> Settings:
    """Returns a cached instance of the settings."""
    return Settings()
