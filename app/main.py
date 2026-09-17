from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load local development configuration. ECS will inject the same names from
# Secrets Manager/task configuration instead; no .env file belongs in a container image.
load_dotenv()

from fastapi import FastAPI, HTTPException
from langfuse import get_client, observe

from app.database import save_clinical_record, save_patient_profile
from app.graph import review_graph
from app.schemas import ClinicalRecordCreate, PatientProfileUpsert, ReviewRequest, ReviewResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    # Flushes telemetry before an ECS task stops. No PHI is captured by decorators.
    get_client().flush()


app = FastAPI(title="Cardiologist Clinical Review Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/reviews", response_model=ReviewResponse)
@observe(name="clinical_patient_review", as_type="agent", capture_input=False, capture_output=False)
def create_review(request: ReviewRequest) -> ReviewResponse:
    try:
        result = review_graph.invoke(request.model_dump())
        return ReviewResponse.model_validate(result["response"])
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.post("/v1/admin/patient-profiles", status_code=201)
def create_or_update_patient_profile(profile: PatientProfileUpsert) -> dict:
    return save_patient_profile(profile)


@app.post("/v1/admin/clinical-records", status_code=201)
def create_clinical_record(record: ClinicalRecordCreate) -> dict:
    return save_clinical_record(record)
