# Cardiologist Clinical Review Agent

Beginner-safe development starter using FastAPI, LangGraph, and Langfuse. It uses synthetic data only and is read-only.

## 1. Create the environment

In PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Leave `LANGFUSE_TRACING_ENABLED=false` until your hospital has approved telemetry. This code deliberately sets `capture_input=False` and `capture_output=False` on Langfuse observations, because prompts and outputs can contain patient data.

## Configuration

Copy `.env.example` to `.env` and fill in values only when the matching service is ready. `.env` is ignored by Git—never commit API keys. See the configuration guidance in `project spec.md` before using patient-identifiable data or sending telemetry outside the hospital environment.

## 2. Run and test

```powershell
uvicorn app.main:app --reload
pytest
```

Before you create or push a GitHub repository, follow [CONTRIBUTING.md](CONTRIBUTING.md). It installs a pre-push test gate and explains the required GitHub Actions branch-protection check.

Open `http://127.0.0.1:8000/docs` and use `POST /v1/reviews` with:

```json
{"patient_id":"P1005","requesting_user_id":"clinician-demo","question":"Review cardiovascular history, current medication, labs, and approved policy."}
```

## 3. What LangGraph does here

The compiled graph executes four auditable nodes in order: retrieve patient data, retrieve approved RAG knowledge, retrieve medication facts, and synthesize a schema-validated review. It currently uses deterministic synthesis, intentionally: connect an evaluated, approved open-source model only after the retrieval and safety tests are dependable.

## 4. What Langfuse does here

Langfuse creates traces for the review and tool nodes. Do not send patient identifiers, prompts, retrieved records, or generated clinical output to a hosted observability service unless your hospital has formally approved the data flow and retention. For production, configure self-hosting or an approved regional deployment, identity controls, retention, and a data-processing agreement as required.

## 5. Next implementation tasks

1. Replace the synthetic `get_patient_clinical_context` function with authorization plus DynamoDB access.
2. Index only approved policy documents in OpenSearch, then replace `search_approved_clinical_knowledge`.
3. Add an approved medication API adapter.
4. Add the open-source inference node behind a structured-output validator and clinical evaluation suite.
5. Put configuration/secrets in AWS Secrets Manager and deploy the container to a development ECS environment.
