from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    reference_date: date = date(2026, 8, 17)

    patient_repository_provider: Literal["local_json", "dynamodb"] = "local_json"
    policy_retriever_provider: Literal["local", "opensearch"] = "local"
    medication_order_provider: Literal["unavailable", "json"] = "unavailable"
    llm_provider: Literal["openai", "azure", "fake"] = "openai"
    openfda_provider: Literal["openfda", "fake"] = "openfda"

    enable_dynamodb: bool = False
    enable_opensearch: bool = False
    enable_langfuse: bool = False

    repo_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3])
    patients_json_path: Path = Path("data/patients/runtime/patients.json")
    case_manifest_path: Path = Path("data/patients/evaluation/case_manifest.json")
    corpus_inventory_path: Path = Path("config/corpus_inventory.yaml")
    local_index_path: Path = Path(".local/policy_index.json")
    audit_log_path: Path = Path(".local/audit.log")

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    streamlit_api_url: str = "http://127.0.0.1:8000"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""

    openfda_api_key: str = ""

    aws_region: str = "eu-west-2"
    dynamodb_patients_table: str = "Patients"
    opensearch_endpoint: str = ""
    opensearch_index: str = "cardiology-policies"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    def resolve(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return self.repo_root / path

    @property
    def patients_file(self) -> Path:
        return self.resolve(self.patients_json_path)

    @property
    def manifest_file(self) -> Path:
        return self.resolve(self.case_manifest_path)

    @property
    def inventory_file(self) -> Path:
        return self.resolve(self.corpus_inventory_path)

    @property
    def index_file(self) -> Path:
        return self.resolve(self.local_index_path)

    @property
    def audit_file(self) -> Path:
        return self.resolve(self.audit_log_path)

    def effective_llm_provider(self) -> str:
        if self.llm_provider == "fake":
            return "fake"
        if self.llm_provider == "azure" and self.azure_openai_api_key:
            return "azure"
        if self.openai_api_key:
            return "openai"
        return "fake"

    def effective_openfda_provider(self) -> str:
        if self.openfda_provider == "fake":
            return "fake"
        # openFDA allows unauthenticated access with strict rate limits; treat as live when selected.
        return "openfda"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
