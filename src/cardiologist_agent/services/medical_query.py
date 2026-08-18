from __future__ import annotations

from cardiologist_agent.domain.patient import Patient
from cardiologist_agent.domain.response import Citation
from cardiologist_agent.providers.openfda import OpenFDAClient
from cardiologist_agent.services.question_router import extract_drug_names


def _active_drug_names(patient: Patient | None) -> list[str]:
    if patient is None:
        return []
    return [
        med.drug_name
        for med in patient.medications
        if med.medication_status.lower() == "active" and med.drug_name
    ]


async def answer_medical_question(
    question: str,
    openfda_client: OpenFDAClient,
    patient: Patient | None = None,
) -> tuple[str, list[Citation]]:
    drugs = extract_drug_names(question) or _active_drug_names(patient)[:3]
    if not drugs:
        return (
            "Please name the medicine you want information about, "
            "or ask about a patient who has medicines on their record.",
            [],
        )

    citations: list[Citation] = []
    sections: list[str] = []

    for drug in drugs[:3]:
        result = await openfda_client.lookup_drug_label(drug)
        if result.found and result.label_excerpt:
            citations.append(
                Citation(
                    source_type="openfda",
                    document_id=drug,
                    url=result.source_url,
                    retrieved_at=result.retrieved_at,
                )
            )
            excerpt = " ".join(result.label_excerpt.split())
            sections.append(
                f"For {drug}, the drug label notes: {excerpt[:400].rstrip()}…"
                if len(excerpt) > 400
                else f"For {drug}, the drug label notes: {excerpt}"
            )
        elif result.error:
            sections.append(
                f"I could not retrieve a current openFDA label for {drug} ({result.error}). "
                "Please check with the cardiology pharmacist instead."
            )
        else:
            sections.append(
                f"No openFDA label excerpt was returned for {drug}. "
                "Please check with the cardiology pharmacist for verified information."
            )

    intro = (
        "This answer comes from the openFDA drug label service only — "
        "not from the patient's hospital record."
    )
    return (intro + " " + " ".join(sections), citations)
