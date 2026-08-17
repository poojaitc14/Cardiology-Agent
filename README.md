# Cardiologist Clinical Review Agent

Fictional training application for cardiologist patient review and decision-support using synthetic patient data and policy PDFs. **Not for real patient care.**

## Features

- FastAPI backend with LangGraph workflow
- Streamlit clinician UI
- Local JSON patient repository (`data/patients/runtime/patients.json`)
- Runtime-only PDF RAG index (17 policy PDFs; evaluation PDFs excluded)
- Deterministic safety gates and review-status selection
- openFDA and OpenAI integrations when configured; safe fakes otherwise
- Case manifest deterministic evaluation (100 scenarios)
- Configuration-driven stubs for DynamoDB, OpenSearch, Azure OpenAI, Langfuse

## Docker Compose (recommended for local training)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine + Compose v2
- Repository cloned locally

### Environment setup

```powershell
copy .env.example .env
```

Edit `.env` if you want live OpenAI or openFDA integrations. **Do not commit `.env`.** Secrets are loaded at runtime via Compose `env_file` and are never copied into the image.

Default local flags (also enforced in Compose):

| Variable | Value |
|----------|-------|
| `ENABLE_DYNAMODB` | `false` |
| `ENABLE_OPENSEARCH` | `false` |
| `ENABLE_LANGFUSE` | `false` |
| `MEDICATION_ORDER_PROVIDER` | `unavailable` |

Inside Docker, the Streamlit UI uses `API_BASE_URL=http://api:8000` (Docker service hostname, not `localhost`).

### Build and start

From the **repository root**:

```powershell
docker compose -f docker/docker-compose.yml up --build
```

Detached mode:

```powershell
docker compose -f docker/docker-compose.yml up --build -d
```

### URLs

| Service | URL |
|---------|-----|
| FastAPI health | http://localhost:8000/health |
| FastAPI ready | http://localhost:8000/ready |
| Streamlit UI | http://localhost:8501 |

### Logs

```powershell
docker compose -f docker/docker-compose.yml logs -f
docker compose -f docker/docker-compose.yml logs -f api
docker compose -f docker/docker-compose.yml logs -f ui
```

### Stop

```powershell
docker compose -f docker/docker-compose.yml stop
```

Remove containers (keeps the `.local` named volume):

```powershell
docker compose -f docker/docker-compose.yml down
```

### Clean rebuild

```powershell
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml build --no-cache
docker compose -f docker/docker-compose.yml up
```

### Run tests in Docker

```powershell
docker compose -f docker/docker-compose.yml --profile test run --rm test
```

### Architecture

```text
Host
├── localhost:8000  -> api (FastAPI + LangGraph)
├── localhost:8501  -> ui  (Streamlit)
├── ../data         -> /app/data (read-only bind mount)
└── named volume    -> /app/.local (policy index, audit log)
```

The UI waits for the API `/health` check before starting.

### Troubleshooting

| Issue | Action |
|-------|--------|
| `env_file ../.env not found` | Run `copy .env.example .env` from repo root |
| UI cannot reach API | Confirm `API_BASE_URL=http://api:8000` in Compose (not `localhost`) |
| `/ready` false | Ensure `data/patients/runtime/patients.json` and runtime PDFs exist on the host |
| Port already in use | Stop local uvicorn/streamlit or change host port mapping |
| Stale index after PDF changes | `docker compose ... down -v` then rebuild to reset `cardiologist_local` volume |
| OpenAI/openFDA errors in review | Expected safe behavior: failures appear under `unavailable_dependencies`; set keys in `.env` or use `LLM_PROVIDER=fake` |

## Quick start (native Python)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env

# Validate artifacts and build local policy index
python -m cardiologist_agent.scripts.validate_artifacts

# Run API
uvicorn cardiologist_agent.api.main:app --host 127.0.0.1 --port 8000

# Run Streamlit (separate terminal)
streamlit run streamlit_app/app.py
```

## Default configuration

| Variable | Default |
|----------|---------|
| `PATIENT_REPOSITORY_PROVIDER` | `local_json` |
| `POLICY_RETRIEVER_PROVIDER` | `local` |
| `MEDICATION_ORDER_PROVIDER` | `unavailable` |
| `ENABLE_DYNAMODB` | `false` |
| `ENABLE_OPENSEARCH` | `false` |
| `ENABLE_LANGFUSE` | `false` |

## API endpoints

- `GET /health` — liveness
- `GET /ready` — artifact readiness
- `POST /api/v1/reviews` — run clinical review

## Authorization limitation

`FINAL_AUTHORIZED` is **blocked** while `MEDICATION_ORDER_PROVIDER=unavailable`. Medication history `prescriber` fields are not treated as signed orders.

## Tests

```powershell
pytest tests/unit tests/safety tests/integration -q
pytest tests/evaluation/test_deterministic_status.py -q -m slow
python -m cardiologist_agent.scripts.run_evaluation
```

## Cloud adapters (not provisioned locally)

- DynamoDB: `infra/dynamodb.template.yaml`, enable with `ENABLE_DYNAMODB=true`
- OpenSearch: configure `OPENSEARCH_ENDPOINT`, enable with `ENABLE_OPENSEARCH=true`
- CI: `infra/buildspec.yml` placeholder for CodeBuild/CodePipeline
