"""Read-only DynamoDB repository for one patient's clinical records."""

from __future__ import annotations

import os
import re
from typing import Any, Protocol

import boto3
from boto3.dynamodb.conditions import Key

from backend.models.patient import PatientDataResult, PatientRecordScope, SCOPE_PREFIXES

PATIENT_ID_PATTERN = re.compile(r"^P[0-9]{4,12}$")


class DynamoTable(Protocol):
    """Small DynamoDB table surface needed by this read-only repository."""

    def get_item(self, **kwargs: Any) -> dict[str, Any]: ...

    def query(self, **kwargs: Any) -> dict[str, Any]: ...


class PatientRepository:
    """Retrieves only records under an explicitly supplied patient partition."""

    def __init__(self, table: DynamoTable) -> None:
        self._table = table

    @classmethod
    def from_environment(cls) -> "PatientRepository":
        """Create a repository using IAM roles or the standard AWS provider chain."""
        table_name = os.environ.get("DYNAMODB_PATIENT_TABLE")
        region_name = os.environ.get("AWS_REGION")
        if not table_name:
            raise ValueError("DYNAMODB_PATIENT_TABLE must be configured.")
        if not region_name:
            raise ValueError("AWS_REGION must be configured.")
        resource = boto3.resource("dynamodb", region_name=region_name)
        return cls(resource.Table(table_name))

    def get_records(self, patient_id: str, scope: PatientRecordScope) -> PatientDataResult:
        """Get a profile, category, or full review without scanning or cross-patient access."""
        self._validate_patient_id(patient_id)
        if scope is PatientRecordScope.PROFILE:
            response = self._table.get_item(Key={"PK": self._patient_pk(patient_id), "SK": "PROFILE"})
            records = [response["Item"]] if "Item" in response else []
        elif scope is PatientRecordScope.FULL_REVIEW:
            response = self._table.query(
                KeyConditionExpression=Key("PK").eq(self._patient_pk(patient_id))
            )
            records = response.get("Items", [])
        else:
            prefix = SCOPE_PREFIXES[scope]
            response = self._table.query(
                KeyConditionExpression=Key("PK").eq(self._patient_pk(patient_id)) & Key("SK").begins_with(prefix)
            )
            records = response.get("Items", [])

        self._assert_patient_isolation(records, patient_id)
        return PatientDataResult(
            patient_id=patient_id,
            scope=scope,
            records=records,
            source=f"DynamoDB / Patient {patient_id}",
            found=bool(records),
        )

    @staticmethod
    def _validate_patient_id(patient_id: str) -> None:
        if not PATIENT_ID_PATTERN.fullmatch(patient_id):
            raise ValueError("patient_id must use the format P followed by 4 to 12 digits.")

    @staticmethod
    def _patient_pk(patient_id: str) -> str:
        return f"PATIENT#{patient_id}"

    @staticmethod
    def _assert_patient_isolation(records: list[dict[str, Any]], patient_id: str) -> None:
        expected_pk = f"PATIENT#{patient_id}"
        for record in records:
            if record.get("PK") != expected_pk or record.get("patient_id") != patient_id:
                raise RuntimeError("Rejected database response with mismatched patient identity.")
