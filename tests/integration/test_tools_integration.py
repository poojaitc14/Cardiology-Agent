"""Live, independently runnable checks for the three external tool integrations.

These tests require explicitly configured services. They never create, update, or
delete records or indexes.
"""
from __future__ import annotations

import os

import pytest

from backend.models.patient import PatientRecordScope
from backend.services.openfda import OpenFDAService
from backend.services.patient_repository import PatientRepository
from rag.retrieval.cardiology_rag import CardiologyRAGService


def test_dynamodb_returns_patient_p1005() -> None:
    if os.environ.get("RUN_DYNAMODB_INTEGRATION") != "1":
        pytest.skip("Set RUN_DYNAMODB_INTEGRATION=1 with AWS credentials and DYNAMODB_PATIENT_TABLE.")
    try:
        result = PatientRepository.from_environment().get_records("P1005", PatientRecordScope.PROFILE)
    except Exception as error:
        pytest.fail(f"DynamoDB integration failed: {type(error).__name__}")
    assert result.found, result.no_record_message
    assert result.records[0]["patient_id"] == "P1005"


def test_openfda_returns_warfarin_information() -> None:
    if os.environ.get("RUN_OPENFDA_INTEGRATION") != "1":
        pytest.skip("Set RUN_OPENFDA_INTEGRATION=1 to call the public OpenFDA API.")
    result = OpenFDAService().search_drug_label("Warfarin")
    assert result.available, result.user_message
    assert result.found, result.user_message
    assert result.label is not None
    assert result.source == "OpenFDA"


def test_opensearch_retrieves_anticoagulation_policy() -> None:
    if os.environ.get("RUN_OPENSEARCH_INTEGRATION") != "1":
        pytest.skip("Set RUN_OPENSEARCH_INTEGRATION=1 after indexing the dummy policy document.")
    host = os.environ.get("OPENSEARCH_HOST")
    index_name = os.environ.get("OPENSEARCH_INDEX")
    if not host or not index_name:
        pytest.skip("OPENSEARCH_HOST and OPENSEARCH_INDEX are required.")
    opensearch = pytest.importorskip("opensearchpy")
    client = opensearch.OpenSearch(hosts=[host])
    result = CardiologyRAGService(client, index_name).retrieve("anticoagulation policy")
    assert result.available, result.user_message
    assert result.results, result.user_message
    assert any("Anticoagulation / Antiplatelet Therapy Protocol" == item.document for item in result.results)
