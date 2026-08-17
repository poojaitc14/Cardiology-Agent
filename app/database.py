"""DynamoDB persistence for the restricted admin workflow.

One DynamoDB table is used. It contains a PROFILE item and sparse clinical-record
items for each patient, rather than a single giant, mostly empty record.
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

from boto3 import resource
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.schemas import ClinicalRecordCreate, PatientProfileUpsert


def _table():
    table_name = os.getenv("DYNAMODB_TABLE_NAME")
    if not table_name:
        raise HTTPException(status_code=503, detail="DynamoDB is not configured. Set DYNAMODB_TABLE_NAME.")
    return resource("dynamodb", region_name=os.getenv("AWS_REGION", "eu-west-2")).Table(table_name)


def _ensure_admin(admin_user_id: str) -> None:
    # Replace with hospital SSO role/permission validation before production.
    if not admin_user_id.startswith("admin-"):
        raise HTTPException(status_code=403, detail="Administrator permission is required.")


def _put_item(item: dict) -> dict:
    try:
        _table().put_item(Item={key: value for key, value in item.items() if value is not None})
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Clinical data store is unavailable.") from error
    return item


def save_patient_profile(profile: PatientProfileUpsert) -> dict:
    _ensure_admin(profile.admin_user_id)
    now = datetime.now(UTC).isoformat()
    return _put_item({
        "PK": f"PATIENT#{profile.patient_id}",
        "SK": "PROFILE",
        "record_id": f"PROFILE#{profile.patient_id}",
        "record_type": "PROFILE",
        "created_at": now,
        "updated_at": now,
        **profile.model_dump(exclude={"admin_user_id"}),
    })


def save_clinical_record(record: ClinicalRecordCreate) -> dict:
    _ensure_admin(record.admin_user_id)
    now = datetime.now(UTC).isoformat()
    record_id = str(uuid4())
    return _put_item({
        "PK": f"PATIENT#{record.patient_id}",
        "SK": f"{record.record_type}#{now}#{record_id}",
        "record_id": record_id,
        "created_at": now,
        "updated_at": now,
        **record.model_dump(exclude={"admin_user_id"}),
    })


def get_patient_timeline(patient_id: str) -> list[dict]:
    """Read all timeline items for one patient from the configured table."""
    try:
        table = _table()
        response = table.query(KeyConditionExpression=Key("PK").eq(f"PATIENT#{patient_id}"))
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = table.query(
                KeyConditionExpression=Key("PK").eq(f"PATIENT#{patient_id}"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        return items
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError("Clinical data store is unavailable.") from error
