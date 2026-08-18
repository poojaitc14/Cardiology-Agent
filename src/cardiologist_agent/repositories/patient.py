from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import ValidationError

from cardiologist_agent.domain.patient import Patient


class PatientAlreadyExistsError(Exception):
    pass


class PatientRepository(ABC):
    @abstractmethod
    async def get_patient(self, patient_id: str) -> Patient | None: ...

    @abstractmethod
    async def list_patient_ids(self) -> list[str]: ...

    @abstractmethod
    async def create_patient(self, patient: Patient) -> Patient: ...


class LocalJsonPatientRepository(PatientRepository):
    def __init__(self, json_path: Path, custom_path: Path | None = None) -> None:
        self._path = json_path
        self._custom_path = custom_path
        self._patients: dict[str, Patient] | None = None

    def _read_base_raw(self) -> list[dict]:
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _read_custom_raw(self) -> list[dict]:
        if self._custom_path is None or not self._custom_path.exists():
            return []
        return json.loads(self._custom_path.read_text(encoding="utf-8"))

    def _write_custom_raw(self, items: list[dict]) -> None:
        if self._custom_path is None:
            raise RuntimeError("Custom patient storage is not configured.")
        self._custom_path.parent.mkdir(parents=True, exist_ok=True)
        self._custom_path.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")

    def _load(self) -> dict[str, Patient]:
        if self._patients is None:
            patients: dict[str, Patient] = {}
            for item in self._read_base_raw() + self._read_custom_raw():
                patient = Patient.model_validate(item)
                patients[patient.patient_id] = patient
            self._patients = patients
        return self._patients

    def _invalidate(self) -> None:
        self._patients = None

    async def get_patient(self, patient_id: str) -> Patient | None:
        return self._load().get(patient_id.upper())

    async def list_patient_ids(self) -> list[str]:
        return sorted(self._load().keys())

    async def create_patient(self, patient: Patient) -> Patient:
        patient_id = patient.patient_id.upper()
        if patient_id in self._load():
            raise PatientAlreadyExistsError(patient_id)
        custom = self._read_custom_raw()
        payload = patient.model_dump(mode="json")
        custom.append(payload)
        self._write_custom_raw(custom)
        self._invalidate()
        return patient

    def validate_all(self) -> list[str]:
        errors: list[str] = []
        raw = self._read_base_raw()
        if len(raw) < 100:
            errors.append(f"Expected at least 100 base patients, found {len(raw)}")
        ids = [p["patient_id"] for p in raw + self._read_custom_raw()]
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

    async def create_patient(self, patient: Patient) -> Patient:
        raise NotImplementedError("Patient creation is only supported for local_json in training mode.")
