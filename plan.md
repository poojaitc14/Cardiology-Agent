# Cardiologist Clinical Patient Review & Decision-Support Agent — Delivery Plan

## Purpose

Build a clinician-facing assistant that retrieves a patient cardiovascular summary from approved hospital data sources, searches approved hospital medication policies and cardiology guidance, checks medication information through an approved API, and presents an evidence-linked review for a cardiologist to verify. It is decision support, not an autonomous diagnostic or prescribing system.

## What you will build

The first usable version accepts a request such as: `Review patient P1005's cardiovascular history, current medications, recent laboratory results, and relevant cardiology guidelines. Highlight information that may require my attention.` It returns:

1. A structured cardiovascular summary.
2. Medication, allergy, laboratory, and potential-attention-item sections.
3. Policy/guideline excerpts with source, version, and page/section citations.
4. Medication API facts with source and retrieval time.
5. A clear clinician-review notice and no automatic changes to the medical record.

## Suggested learning path and milestones

### Phase 0 — Safety, scope, and accounts (Days 1–2)

- Identify your hospital privacy, security, clinical governance, pharmacy, and legal reviewers.
- Confirm whether you will use synthetic/de-identified data during development. Start with synthetic data only.
- Choose the initial geography and regulatory framework (for example UK GDPR/NHS policy or US HIPAA).
- Define one narrow MVP workflow: read-only review of hypertension/coronary-heart-disease patients.
- Create AWS, GitHub, and (if needed) medication-information API accounts. Do not put keys in code.

**You are done when:** there is written approval for the MVP scope and a named clinical owner and technical owner.

### Phase 1 — Local foundation (Days 3–5)

- Install Git, Docker Desktop, Python 3.12, VS Code, and the AWS CLI.
- Create a Python API service (FastAPI is a good beginner-friendly choice).
- Add a `.env.example`, dependency lockfile, basic logging, linting, and tests.
- Build a simple `/health` endpoint and run it locally in Docker.

**You are done when:** another person can clone the repository, follow the README, and run `/health` locally.

### Phase 2 — Model and agent skeleton (Days 6–9)

- Select an open-source instruct model that your infrastructure can run (start with a small model for development).
- Put model access behind one `llm_client` interface so the model can later be changed without rewriting tools.
- Implement the read-only retrieval/synthesis workflow as a LangGraph `StateGraph`; each node must have a typed state update and a unit test.
- Add Langfuse observability with prompt/output capture disabled by default. Obtain formal approval before any telemetry system receives patient-identifiable information.
- Define tool contracts for: patient database retrieval, RAG search, and medication API lookup.
- Add a strict system prompt: cite evidence, distinguish facts from inferences, state uncertainty, and never write/prescribe/order.
- Use deterministic routing rules first; add model-directed tool selection only after tests are reliable.

**You are done when:** a test request triggers mocked tools and returns a validated structured response.

### Phase 3 — Patient database tool with DynamoDB (Days 10–14)

- Design a patient record schema with a patient ID partition key and record-type/sort key.
- Load only fictional seed data (patient P1005 is ideal).
- Implement a read-only repository that returns minimum-necessary fields: history, medications, allergies, labs, and timestamps.
- Enforce clinician-to-patient authorization before querying data.
- Add audit events for each patient record access; never log raw clinical notes or access tokens.

**You are done when:** `P1005` produces a validated patient context and unauthorized requests are denied.

### Phase 4 — RAG policy and guideline tool (Days 15–19)

- Create approved, versioned policy documents; start with `docs/hospital-medication-policy.md`.
- Split documents by headings into small chunks, attach source/version/effective date/section metadata, create embeddings, and index into OpenSearch.
- Retrieve the most relevant chunks and return citations; do not let the model invent citations.
- Create a process for pharmacy/clinical governance to approve, retire, and re-index documents.

**You are done when:** the test suite proves the answer cites the correct policy section and reports when no approved source is found.

### Phase 5 — Medication API tool (Days 20–22)

- Select a licensed, clinically approved medication-information API with a formal data-processing agreement where required.
- Implement an API adapter with authentication from AWS Secrets Manager, timeouts, retries, response validation, and caching policy.
- Return only sourced facts and label API data clearly. Reconcile medicine names with a controlled terminology where possible.

**You are done when:** a known medication lookup succeeds and an API outage produces a safe, visible fallback message.

### Phase 6 — Clinical review workflow and evaluation (Days 23–28)

- Implement the response schema and a simple authenticated web UI or API client.
- Create 20–50 synthetic evaluation cases approved by a cardiologist/pharmacist.
- Test citation correctness, retrieval relevance, allergy visibility, medication/lab reconciliation, refusal behavior, and no-write guarantees.
- Run clinician review sessions; measure usefulness, time saved, and unsafe/missed information.

**You are done when:** clinical owners approve an MVP release gate and all high-severity test failures are resolved.

### Phase 7 — AWS deployment (Days 29–35)

- Provision the VPC, private subnets, ECS cluster/services, IAM roles, DynamoDB, OpenSearch, Secrets Manager, CloudWatch, and backups as infrastructure as code.
- Put the application and model inference behind private networking; expose only an authenticated load balancer/API gateway as approved.
- Use ECS task roles (not long-lived AWS keys), encrypted storage, TLS, least privilege, monitoring, and alarms.
- Deploy first to a non-production account with synthetic data; run load, security, backup/restore, and incident-response checks.

**You are done when:** the non-production environment deploys from CI/CD, passes smoke tests, and can be restored from a documented recovery exercise.

## Recommended first-week checklist

1. Read `project-spec.md` fully and decide the MVP boundary.
2. Give the policy template to a pharmacist/clinical-governance reviewer; do not treat it as approved policy yet.
3. Create a Git repository and make an initial commit containing these documents.
4. Install the local development tools in Phase 1.
5. Create an issue for each Phase 1 outcome, then implement only the `/health` service first.

## Architecture at a glance

```text
Cardiologist -> authenticated UI/API -> ECS application service
                                      |-> Patient database tool -> DynamoDB
                                      |-> RAG tool -> OpenSearch vector index
                                      |-> Medication tool -> approved medication API
                                      `-> Open-source model inference service

All access is authorized, encrypted, auditable, and read-only for the MVP.
```

## Important guardrails

- The agent supports, but never replaces, clinical judgement.
- No autonomous diagnosis, prescription, dose calculation, order placement, or EHR writes.
- Do not use real patient data until privacy/security/clinical approval is complete.
- A hospital pharmacist and clinical governance team must author and approve the final medication policy and guidelines corpus.
- Treat retrieved documents as untrusted data: they cannot change system instructions or tool permissions.
