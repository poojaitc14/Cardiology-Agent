from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import ValidationError

from cardiologist_agent.domain.patient import Patient


class PatientRepository(ABC):
    @abstractmethod
    async def get_patient(self, patient_id: str) -> Patient | None: ...

    @abstractmethod
    async def list_patient_ids(self) -> list[str]: ...


class LocalJsonPatientRepository(PatientRepository):
    def __init__(self, json_path: Path) -> None:
        self._path = json_path
        self._patients: dict[str, Patient] | None = None

    def _load(self) -> dict[str, Patient]:
        if self._patients is None:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            patients: dict[str, Patient] = {}
            for item in raw:
                patient = Patient.model_validate(item)
                patients[patient.patient_id] = patient
            self._patients = patients
        return self._patients

    async def get_patient(self, patient_id: str) -> Patient | None:
        return self._load().get(patient_id)

    async def list_patient_ids(self) -> list[str]:
        return sorted(self._load().keys())

    def validate_all(self) -> list[str]:
        errors: list[str] = []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if len(raw) != 100:
            errors.append(f"Expected 100 patients, found {len(raw)}")
        ids = [p["patient_id"] for p in raw]
        if len(set(ids)) != len(ids):
            errors.append("Duplicate patient_id values detected")
        for item in raw:
            try:
                Patient.model_validate(item)
            except ValidationError as exc:
                errors.append(f"{item.get('patient_id')}: {exc}")
        return errors


class DynamoDBPatientRepository(PatientRepository):
    """Configuration-driven adapter — requires ENABLE_DYNAMODB and boto3."""

    def __init__(self, table_name: str, region: str) -> None:
        self._table_name = table_name
        self._region = region
        self._table = None

    def _get_table(self):  # noqa: ANN202
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb", region_name=self._region).Table(
                self._table_name
            )
        return self._table

    async def get_patient(self, patient_id: str) -> Patient | None:
        table = self._get_table()
        resp = table.get_item(Key={"patient_id": patient_id})
        item = resp.get("Item")
        if not item:
            return None
        return Patient.model_validate(item)

    async def list_patient_ids(self) -> list[str]:
        table = self._get_table()
        ids: list[str] = []
        scan_kwargs: dict = {}
        while True:
            resp = table.scan(ProjectionExpression="patient_id", **scan_kwargs)
            ids.extend(item["patient_id"] for item in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return sorted(ids)
