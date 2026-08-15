# Running the Cardiology Clinical Decision Support Agent Locally

This guide covers running the FastAPI backend and Streamlit frontend on your
own machine, both directly (Python venv) and via Docker Compose.

## 1. Prerequisites

- Python 3.11 or 3.12 (`pyproject.toml` requires `>=3.11,<3.13`)
- Either [`uv`](https://docs.astral.sh/uv/) (recommended — this repo ships a
  `uv.lock`) or plain `pip` + `venv`
- Docker Desktop, only if you want to run via `docker-compose.yml`
- AWS credentials with read access to a DynamoDB table (`PatientClinicalRecords`
  by default), configured through the standard AWS credential provider chain
  (an AWS profile, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, or an IAM role).
  The app never reads AWS keys from `.env`.

The following external services are optional; the app degrades gracefully if
they are not configured:

| Service | Used for | If not configured |
|---|---|---|
| OpenFDA | drug-label lookups | requires no credentials; works out of the box |
| Azure OpenAI | synthesizing the final `/query` answer from retrieved patient/drug/RAG facts | agent falls back to a plain templated summary of the retrieved facts instead of an LLM-written answer |
| OpenSearch Serverless | cardiology guideline/policy RAG retrieval | RAG tool falls back to a "temporarily unavailable" message |
| Langfuse | observability tracing | tracing becomes a no-op |

## 2. Clone and install dependencies

From the `Cardiology-Agent` project folder:

**Using `uv` (recommended):**

```powershell
uv sync
```

**Using `pip` + `venv`:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. Configure environment variables

Copy the example file and fill in your own values:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set at minimum:

```
AWS_REGION=eu-west-2
DYNAMODB_PATIENT_TABLE=PatientClinicalRecords
```

Leave `OPENFDA_*`, `AZURE_OPENAI_*`, `OPENSEARCH_*`, and `LANGFUSE_*` blank/default
if you don't have those services set up — the app will run with those features
degraded rather than failing to start (except Langfuse: if you set
`LANGFUSE_ENABLED=true` you must also supply valid `LANGFUSE_PUBLIC_KEY` /
`LANGFUSE_SECRET_KEY`, otherwise it auto-disables itself).

`.env` is loaded automatically by the backend at startup (via `python-dotenv`),
so you do not need to manually export these variables in your shell for local
(non-Docker) runs. **Never commit `.env`** — it's already covered by `.gitignore`.

## 4. Set up the DynamoDB patient table

The backend expects a DynamoDB table (`PK`/`SK` single-table design) to already
exist and contain data — it never creates the table or writes to it.

1. Create a DynamoDB table named to match `DYNAMODB_PATIENT_TABLE` (default
   `PatientClinicalRecords`) with partition key `PK` (String) and sort key `SK`
   (String), in the region set by `AWS_REGION`.
2. Seed it with the 100 synthetic patients (`P1001`-`P1100`) using an AWS
   identity that has write access (this is an operator-only command, separate
   from the read-only runtime):

```powershell
$env:AWS_REGION = "eu-west-2"
$env:DYNAMODB_PATIENT_TABLE = "PatientClinicalRecords"
python -m database.seed_synthetic_patients --count 100
```

## 5. Run the backend (FastAPI)

From the `Cardiology-Agent` folder, with your venv activated:

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify it's up:

```powershell
curl http://localhost:8000/health
```

Interactive API docs are available at `http://localhost:8000/docs`.

## 6. Run the frontend (Streamlit)

In a second terminal (venv activated), from the `Cardiology-Agent` folder:

```powershell
streamlit run frontend/streamlit_app.py
```

This opens the UI at `http://localhost:8501`. By default it talks to the
backend at `http://localhost:8000` (`FASTAPI_URL` env var, default set in
`frontend/config.py`) — override it if your backend runs elsewhere:

```powershell
$env:FASTAPI_URL = "http://localhost:8000"
streamlit run frontend/streamlit_app.py
```

Enter a patient ID (e.g. `P1005`) in the sidebar and ask a clinical question,
e.g. "Review patient medications" or "What are the side effects of Warfarin?".

## 7. Run everything with Docker Compose (alternative to steps 5-6)

```powershell
docker compose up --build
```

This builds and starts two containers:
- Backend: `http://localhost:8000`
- Frontend: `http://localhost:8501`

`OPENSEARCH_HOST` passes straight through from `.env` into the backend
container unchanged — it's a real external OpenSearch Serverless endpoint
(public network access, IAM/SigV4-gated data access), not an in-network Docker
service, so there's no host-vs-container split to worry about and no VPN or
other network prerequisite to reach it. Full resource inventory in
[`infra/opensearch-serverless.md`](infra/opensearch-serverless.md).

Docker Compose only forwards the environment variables explicitly listed under
each service's `environment:` block in `docker-compose.yml` — it does **not**
automatically read your `.env` file into the containers. Either export the
variables in your shell before running `docker compose up`, or use a
`.env` file in the same directory as `docker-compose.yml` (Compose's own
built-in `.env` substitution, which is what `${VAR}` in the compose file reads
from — this is separate from `python-dotenv`).

**AWS credentials for the backend container:** by design, this app never reads
AWS keys from `.env` or any config file — it relies entirely on boto3's
standard credential provider chain (an AWS profile, environment variables, or
an IAM role). `docker-compose.yml` mounts your host's `~/.aws` folder
read-only into the backend container (`${USERPROFILE}/.aws:/root/.aws:ro`) so
it can reuse whatever AWS CLI profile you already have configured on the host
(`aws configure` sets this up if you don't have one). If you're on Linux/macOS,
change `${USERPROFILE}` to `${HOME}` in `docker-compose.yml` first. Without
this mount, every `/patient/*` request and any query mentioning a patient ID
fails with a 500 error (`NoCredentialsError: Unable to locate credentials` in
the backend container logs — check with `docker logs cardiology-backend`).

## 8. Run the tests

```powershell
python -m pytest
```

This runs the full unit + integration suite. Three tests are skipped by
default because they call real external services — opt into them individually
if you have the credentials/services available:

```powershell
$env:RUN_DYNAMODB_INTEGRATION = "1"   # requires a seeded table + AWS creds
$env:RUN_OPENFDA_INTEGRATION = "1"    # calls the public OpenFDA API
$env:RUN_OPENSEARCH_INTEGRATION = "1" # requires OPENSEARCH_HOST/INDEX with the dummy policy doc indexed
python -m pytest tests/integration/test_tools_integration.py
```

## 9. Index the RAG documents into OpenSearch Serverless

The cardiology-guideline RAG tool needs the collection's index to exist and
contain the 15 synthetic documents before it will return anything. This is an
operator-only step, already done once for this project (see
[`infra/opensearch-serverless.md`](infra/opensearch-serverless.md)), but here's
how to redo it:

```powershell
python -m rag.ingestion.index_dummy_documents_cli
```

This creates the k-NN index (if it doesn't already exist) with a vector
dimension matching `RAG_EMBEDDING_DIMENSIONS`, then chunks, embeds, and indexes
all 15 documents. **OpenSearch Serverless has no idempotent upsert** here — the
ingestion pipeline can't specify a custom document ID (Serverless rejects it),
so re-running this script appends duplicate documents rather than replacing
them. If you need a clean re-index, delete and recreate the index first.

## Notes

- When `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT` are configured, the agent
  (`backend/agent/cardiology_agent.py`, `backend/observability/instrumented_agent.py`)
  calls `AzureOpenAILLM.generate_clinical_response()` to synthesize the final
  `/query` answer from the retrieved patient/drug/RAG facts. If Azure OpenAI is
  not configured, or the call fails or times out (30s timeout, no retries), the
  agent falls back to a deterministic templated summary of the same retrieved
  facts — the response is always grounded in tool output either way, never
  fabricated by the LLM alone.
- The patient database, OpenFDA, and cardiology-RAG tools are read-only by
  design; nothing in the agent runtime can write to DynamoDB or the search
  index.
- `POST /query` uses the `patient_id` field from the request directly (falling
  back to extracting one from the question text only if `patient_id` is
  empty) — you don't need to repeat the patient ID inside your question.
