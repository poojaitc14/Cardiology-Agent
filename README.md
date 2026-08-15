# Cardiologist Clinical Patient Review Agent

This project is clinical decision support for qualified healthcare professionals. It does not diagnose, prescribe, alter medication doses, or make final treatment decisions.

## DynamoDB patient data layer

The patient database uses the `PatientClinicalRecords` single-table design. Every item is partitioned with `PK=PATIENT#<patient_id>` and has an entity-specific `SK` such as `PROFILE`, `MEDICATION#<date>#<id>`, or `LAB#<timestamp>#<id>`. The agent-facing `PatientRepository` only supports exact patient-ID reads; it does not scan, write, or query across patient partitions.

The repository is configured using `AWS_REGION` and `DYNAMODB_PATIENT_TABLE`. AWS authentication is deliberately left to boto3's standard credential provider chain, such as an ECS IAM role or an AWS profile. No credentials are accepted or stored in source code.

Copy `.env.example` to an uncommitted `.env` only if your local configuration loader needs it. Do not commit `.env`.

## Synthetic data

The generator creates 100 deterministic synthetic patient partitions (`P1001`-`P1100`) with seven records each: profile, condition, medication, allergy, lab, vital sign, and cardiology test. It is labelled `Synthetic training dataset` on every record.

After creating the DynamoDB table and supplying an IAM identity that has write access for this administrative task, run:

```powershell
$env:AWS_REGION = "eu-west-2"
$env:DYNAMODB_PATIENT_TABLE = "PatientClinicalRecords"
python -m database.seed_synthetic_patients --count 100
```

The seed command is operator-only. It is separate from the agent runtime, which must use read-only IAM permissions.

## OpenFDA drug-label service

`OpenFDAService` performs read-only generic-name or brand-name searches against OpenFDA drug labels and normalizes factual label fields (names, manufacturer, purpose, warnings, contraindications, adverse reactions, and dosage-and-administration text). It does not make clinical recommendations.

Configure the public endpoint and timeout through the environment:

```powershell
$env:OPENFDA_BASE_URL = "https://api.fda.gov/drug/label.json"
$env:OPENFDA_TIMEOUT_SECONDS = "10"
```

OpenFDA requires no credential. Timeouts, HTTP errors, and malformed provider responses are logged internally and returned as a generic unavailable state; provider error details are never exposed in a user-facing result.

## Cardiology RAG pipeline

The RAG layer performs `documents → extraction → chunking → embeddings → OpenSearch`. Its retrieval interface accepts a query and returns document, section, content, metadata, and similarity score. The [15-document synthetic list](rag/documents/dummy_cardiology_documents.json) is loaded by `index_dummy_documents()` and indexed through the same pipeline. It contains no clinical guidance and must be replaced with licensed, approved source documents before use.

## Tests

```powershell
python -m pytest
```
