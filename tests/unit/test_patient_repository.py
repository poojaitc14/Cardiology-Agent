from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from backend.models.patient import PatientRecordScope
from backend.services.patient_repository import PatientAlreadyExistsError, PatientRepository


class FakeTable:
    def __init__(self, get_response=None, query_response=None, existing_pks=None):
        self.get_response = get_response or {}
        self.query_response = query_response or {}
        self.existing_pks = existing_pks or set()
        self.put_items = []
        self.last_call = None

    def get_item(self, **kwargs):
        self.last_call = ("get_item", kwargs)
        return self.get_response

    def query(self, **kwargs):
        self.last_call = ("query", kwargs)
        return self.query_response

    def put_item(self, **kwargs):
        self.last_call = ("put_item", kwargs)
        item = kwargs["Item"]
        if item["PK"] in self.existing_pks:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
                "PutItem",
            )
        self.existing_pks.add(item["PK"])
        self.put_items.append(item)
        return {}


def test_profile_lookup_is_scoped_to_exact_patient():
    item = {"PK": "PATIENT#P1005", "SK": "PROFILE", "patient_id": "P1005"}
    table = FakeTable(get_response={"Item": item})
    result = PatientRepository(table).get_records("P1005", PatientRecordScope.PROFILE)
    assert result.records == [item]
    assert result.source == "DynamoDB / Patient P1005"
    assert table.last_call[1]["Key"] == {"PK": "PATIENT#P1005", "SK": "PROFILE"}


def test_missing_record_uses_required_missing_data_message():
    result = PatientRepository(FakeTable()).get_records("P1005", PatientRecordScope.PROFILE)
    assert not result.found
    assert result.no_record_message == "No corresponding information was found in the available patient record."


def test_rejects_malformed_patient_identifier():
    with pytest.raises(ValueError, match="format"):
        PatientRepository(FakeTable()).get_records("P1005 OR P1006", PatientRecordScope.LABS)


def test_rejects_cross_patient_database_response():
    table = FakeTable(query_response={"Items": [{"PK": "PATIENT#P1006", "patient_id": "P1006"}]})
    with pytest.raises(RuntimeError, match="mismatched"):
        PatientRepository(table).get_records("P1005", PatientRecordScope.FULL_REVIEW)


def test_create_patient_writes_a_profile_item():
    table = FakeTable()
    patient_id = PatientRepository(table).create_patient(
        {"patient_id": "P200481", "first_name": "Jordan", "last_name": "Reed"}
    )
    assert patient_id == "P200481"
    assert table.put_items[0]["PK"] == "PATIENT#P200481"
    assert table.put_items[0]["SK"] == "PROFILE"
    assert table.put_items[0]["entity_type"] == "PATIENT_PROFILE"
    assert table.last_call[1]["ConditionExpression"] == "attribute_not_exists(PK)"


def test_create_patient_rejects_duplicate_id():
    table = FakeTable(existing_pks={"PATIENT#P200481"})
    with pytest.raises(PatientAlreadyExistsError, match="already exists"):
        PatientRepository(table).create_patient({"patient_id": "P200481", "first_name": "Jordan"})


def test_create_patient_rejects_malformed_id():
    with pytest.raises(ValueError, match="format"):
        PatientRepository(FakeTable()).create_patient({"patient_id": "not-an-id", "first_name": "Jordan"})
