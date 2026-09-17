"""Operator-only command that writes synthetic data to the configured DynamoDB table."""

from __future__ import annotations

import argparse
import os
from typing import Any

import boto3

from database.synthetic_data import generate_patients


def seed_synthetic_patients(table: Any, count: int = 100, seed: int = 20260814) -> int:
    """Batch-write synthetic records. This must never be invoked by the agent runtime."""
    records = generate_patients(count=count, seed=seed)
    with table.batch_writer() as batch:
        for record in records:
            batch.put_item(Item=record)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a DynamoDB table with synthetic patient records.")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260814)
    args = parser.parse_args()
    table_name = os.environ.get("DYNAMODB_PATIENT_TABLE")
    region_name = os.environ.get("AWS_REGION")
    if not table_name or not region_name:
        raise SystemExit("Set DYNAMODB_PATIENT_TABLE and AWS_REGION before seeding.")
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    written = seed_synthetic_patients(table, count=args.count, seed=args.seed)
    print(f"Wrote {written} synthetic records to {table_name}.")


if __name__ == "__main__":
    main()
