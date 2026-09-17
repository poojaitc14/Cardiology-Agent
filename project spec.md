# Project Specification: Cardiologist Clinical Patient Review & Decision-Support Agent

## 1. Product summary

The product is a secure, read-only clinical decision-support application for cardiologists. Given an authorized patient-review request, it gathers information from hospital patient records, approved RAG documents, and a medication-information API. It synthesizes an evidence-linked review for clinician verification.

**Primary user:** Cardiologist.

**MVP user story:** As an authorized cardiologist, I can request a review for patient P1005 and see cardiovascular history, active medication, recorded allergies, recent relevant labs, and applicable approved policy/guideline excerpts, so that I can focus my own clinical assessment.

## 2. MVP scope

### Included

- Read-only retrieval of synthetic patient data.
- History, medication, allergy, and laboratory review.
- RAG over approved hospital medication policy and cardiology-guidance documents.
- Medication fact lookup using an approved external API.
- Evidence citations and timestamps in every generated review.
- Authentication, authorization, audit logging, encryption, observability, and clinician-review warnings.

### Excluded from MVP

- Diagnosis, treatment recommendations, dose calculations, prescribing, orders, referrals, or automatic EHR updates.
- Unapproved web search as a clinical source.
- Image/ECG interpretation.
- Emergency triage or use as the only source of care.
- Patient-facing advice.

## 3. Functional requirements

| ID | Requirement |
|---|---|
| FR-01 | The system shall accept an authenticated patient-review request containing a patient ID and clinical question. |
| FR-02 | The system shall verify that the user is authorized to access that patient before any retrieval. |
| FR-03 | The database tool shall retrieve only required record types: cardiovascular history, current medication, allergies, and recent labs. |
| FR-04 | The RAG tool shall retrieve only approved, versioned documents and return their source metadata. |
| FR-05 | The medication tool shall obtain facts from the configured medication API and identify the data source/time. |
| FR-06 | The agent shall present a structured, concise review with citations tied to source records or document sections. |
| FR-07 | The agent shall state missing, conflicting, or stale data rather than silently filling gaps. |
| FR-08 | The application shall be read-only; no tool may update patient records, medication lists, or orders. |
| FR-09 | Each request shall create an audit event with user ID, patient pseudonymous ID, action, result, and timestamp. |
| FR-10 | The UI/API shall display that the output requires clinician verification. |

## 4. Non-functional requirements

- **Security:** TLS in transit; encryption at rest with AWS KMS; secrets in Secrets Manager; least-privilege IAM task roles; private subnets for services/data stores.
- **Privacy:** minimum necessary data; do not place PHI in prompts/logs unless formally approved; use synthetic data before production approval; configurable retention.
- **Reliability:** graceful partial results if a non-critical tool is unavailable; clear source-unavailable labels; health checks and alarms.
- **Performance target:** initial MVP p95 response below 15 seconds for a routine review under test load, excluding a configured async fallback.
- **Traceability:** source record timestamp, document version/section, model version, tool results, and request ID must be traceable.
- **Accessibility/usability:** information must be scannable, citation-linked, and visibly distinguish confirmed facts from generated synthesis.

## 5. System design

### Components

| Component | Responsibility | AWS target |
|---|---|---|
| Web/API service | Authentication, request validation, response rendering | ECS Fargate service |
| Agent orchestrator | Applies guardrails and calls tools | ECS Fargate service (may start combined with API) |
| LangGraph workflow | Explicit, testable state machine for tool orchestration | Application dependency in orchestrator |
| Langfuse observability | Trace operational metadata and evaluated workflow behavior | Approved self-hosted or governed service; no PHI capture by default |
| Open-source inference | Serves selected open-source LLM | Separate ECS service on suitable CPU/GPU capacity; evaluate managed/container hosting after benchmark |
| Patient repository | Read-only DynamoDB access and schema validation | ECS library/service + DynamoDB |
| RAG service | Embed/query approved documents and return citations | ECS service + Amazon OpenSearch Service |
| Medication adapter | Calls approved medication information provider | ECS library/service |
| Secrets/audit/monitoring | Credentials, logs, alarms, traces | Secrets Manager, CloudWatch, CloudTrail |

### Request sequence

```text
1. Authenticate cardiologist and authorize patient access.
2. Validate request and generate a request ID.
3. Retrieve minimal patient context from DynamoDB.
4. Search OpenSearch using the clinical question and retrieved medication context.
5. Look up relevant medicines through the approved medication API.
6. Give the model only validated tool results and citation metadata.
7. Validate output schema, attach citations/disclaimer, log audit metadata, return review.
```

## 6. Data design

### DynamoDB single-table starter model

Table: `ClinicalPatientData`

| Key/field | Example | Use |
|---|---|---|
| PK | `PATIENT#P1005` | Patient partition key |
| SK | `MEDICATION#2026-08-01#001` | Record type and sortable event date |
| record_type | `MEDICATION`, `ALLERGY`, `LAB`, `HISTORY` | Validation and query filtering |
| status | `ACTIVE` | Identify current medication |
| observed_at | ISO-8601 timestamp | Clinical freshness |
| source_system | `EHR-SANDBOX` | Provenance |
| payload | validated JSON | Minimal record content |
| ttl | epoch seconds, optional | Controlled expiry for sandbox data |

Store medication, allergy, lab, and history records separately. Avoid storing an entire unstructured patient chart in one item. Production key design must be reviewed for access patterns, encryption, backup, point-in-time recovery, and data-retention requirements.

### OpenSearch RAG document metadata

Every chunk needs: `document_id`, `title`, `version`, `effective_date`, `review_date`, `approval_status`, `owner`, `section`, `page_or_anchor`, `text`, `embedding`, `access_scope`, and `superseded_by`. Filter retrieval to `approval_status=APPROVED` and a current effective date.

## 7. Tool contracts

### `get_patient_clinical_context`

**Input:** `patient_id`, `requesting_user_id`, `record_types`, `as_of`.

**Output:** validated history, active medication, allergies, labs, provenance, and missing-data indicators.

**Rules:** authorize first; read-only; return no free-form tool instructions; never return an entire chart by default.

### `search_approved_clinical_knowledge`

**Input:** query, clinical domain, document filters, maximum results.

**Output:** chunks with text, relevance score, and immutable citation metadata.

**Rules:** approved/current documents only; return "no approved source found" when applicable; no fabricated citations.

### `get_medication_information`

**Input:** normalized medicine name/code and intended information category.

**Output:** source facts, provider version, retrieval time, and provider status.

**Rules:** respect licensing; validate payload; do not transform API facts into dosing advice.

## 8. Agent response contract

Return JSON internally, then render it for users:

```json
{
  "patient_id": "P1005",
  "review_generated_at": "ISO-8601",
  "summary": "Clinician-verifiable synthesis only.",
  "cardiovascular_history": [{"fact": "...", "source": "patient-record-id"}],
  "current_medications": [{"name": "...", "status": "active", "source": "patient-record-id"}],
  "allergies": [{"substance": "...", "reaction": "...", "source": "patient-record-id"}],
  "recent_laboratory_results": [{"test": "...", "value": "...", "observed_at": "...", "source": "patient-record-id"}],
  "attention_items": [{"observation": "...", "basis": ["source-id"], "requires_clinician_verification": true}],
  "approved_knowledge": [{"excerpt": "...", "citation": {"document_id": "...", "version": "...", "section": "..."}}],
  "limitations": ["..."],
  "disclaimer": "For clinician review; not an autonomous diagnosis or prescribing system."
}
```

`attention_items` must be factual observations or clearly labelled possible issues, never imperatives such as “prescribe” or “stop”.

## 9. AWS deployment target

Create this with Terraform/CDK/CloudFormation, first in a development account.

```text
Internet / Hospital network
        |
Authenticated ALB or API Gateway (public or private only as hospital policy permits)
        |
VPC: two or more Availability Zones
  private application subnets: ECS API/orchestrator tasks
  private inference subnets: ECS model-inference tasks
  private data subnets/endpoints: DynamoDB gateway endpoint, OpenSearch
        |
Secrets Manager, KMS, CloudWatch, CloudTrail, ECR
```

- Use an ECS cluster with separate services for the application and inference workload.
- Put DynamoDB behind a VPC gateway endpoint and OpenSearch in VPC subnets/security groups.
- Use security groups that permit only required service-to-service paths.
- Store containers in ECR; deploy by immutable image digest.
- Use ECS task IAM roles, autoscaling, health checks, WAF where internet-facing, and backups/restore testing.
- Model hosting may require ECS capacity providers and GPU EC2 instances; benchmark cost, latency, and model licensing before choosing the instance family.

## 10. Acceptance criteria

1. An authorized synthetic P1005 request returns the four core clinical-data categories.
2. All displayed RAG claims point to an approved document/version/section.
3. An allergy record is conspicuous in the response and source-linked.
4. Unauthorized patient access is rejected and audited.
5. Tool failure returns a clear partial-result warning with no invented information.
6. No test can cause a patient-data write, prescription, or order.
7. The ECS development deployment is reproducible from infrastructure code and passes health/smoke tests.

## 11. Governance gate before real-world use

Obtain documented sign-off from clinical safety/governance, information security, privacy/data protection, pharmacy, legal/procurement, and operational owners. Confirm local medical-device/software classification, data-processing agreements, security assessments, monitoring, incident response, and human-factors evaluation. This specification is a technical starting point, not regulatory or clinical approval.
