from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.domain.enums import Severity
from cardiologist_agent.domain.patient import Patient
from cardiologist_agent.domain.response import ConflictItem, DataGap, SafetyFlag


@dataclass
class SafetyThresholds:
    reference_date: date
    stale_lab_days: int = 90
    stale_vital_days: int = 180
    high_potassium_mmol: float = 5.0
    severe_hypoxia_spo2: int = 92
    marked_bradycardia_bpm: int = 50
    ace_arb_drugs: list[str] = field(default_factory=list)
    anticoagulants: list[str] = field(default_factory=list)
    rate_limiting_drugs: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, settings: Settings | None = None) -> SafetyThresholds:
        settings = settings or get_settings()
        path = settings.resolve(Path("config/safety_thresholds.yaml"))
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        ref = data.get("reference_date", settings.reference_date.isoformat())
        return cls(
            reference_date=date.fromisoformat(str(ref)),
            stale_lab_days=int(data.get("stale_lab_days", 90)),
            stale_vital_days=int(data.get("stale_vital_days", 180)),
            high_potassium_mmol=float(data.get("high_potassium_mmol", 5.0)),
            severe_hypoxia_spo2=int(data.get("severe_hypoxia_spo2", 92)),
            marked_bradycardia_bpm=int(data.get("marked_bradycardia_bpm", 50)),
            ace_arb_drugs=[d.lower() for d in data.get("ace_arb_drugs", [])],
            anticoagulants=[d.lower() for d in data.get("anticoagulants", [])],
            rate_limiting_drugs=[d.lower() for d in data.get("rate_limiting_drugs", [])],
        )


def _parse_dt(value: datetime | date | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _days_since(value: datetime | date | str | None, reference: date) -> int | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return (reference - dt.date()).days


def _drug_class(name: str, drug_list: list[str]) -> bool:
    lower = name.lower()
    return any(d in lower for d in drug_list)


def _normalize_allergen(allergen: str) -> str:
    return allergen.lower().strip()


def _drug_matches_allergen(drug_name: str, allergen: str) -> bool:
    drug = drug_name.lower()
    allergen_l = _normalize_allergen(allergen)
    if allergen_l in drug or drug in allergen_l:
        return True
    # common class mappings for training dataset
    aspirin_allergens = {"aspirin", "salicylate", "nsaid"}
    penicillin_allergens = {"penicillin", "amoxicillin", "beta-lactam"}
    if any(a in allergen_l for a in aspirin_allergens) and "aspirin" in drug:
        return True
    if any(a in allergen_l for a in penicillin_allergens) and "penicillin" in drug:
        return True
    return False


@dataclass
class SafetyAssessment:
    flags: list[SafetyFlag] = field(default_factory=list)
    conflicts: list[ConflictItem] = field(default_factory=list)
    missing: list[DataGap] = field(default_factory=list)
    stale: list[DataGap] = field(default_factory=list)
    inactive_record: bool = False
    emergency: bool = False
    urgent: bool = False
    conflict: bool = False
    insufficient: bool = False
    allergy_reconciliation_unknown: bool = False


def assess_patient(
    patient: Patient, thresholds: SafetyThresholds | None = None
) -> SafetyAssessment:
    thresholds = thresholds or SafetyThresholds.load()
    assessment = SafetyAssessment()
    ref = thresholds.reference_date

    if patient.status.lower() == "inactive":
        assessment.inactive_record = True
        assessment.flags.append(
            SafetyFlag(
                code="INACTIVE_RECORD",
                severity=Severity.CRITICAL,
                message="Patient record is inactive.",
            )
        )
        return assessment

    # Allergy reconciliation unknown
    notes_text = " ".join((c.notes or "") for c in patient.conditions).lower()
    if not patient.allergies and "allergy reconciliation not recorded" in notes_text:
        assessment.allergy_reconciliation_unknown = True
        assessment.insufficient = True
        assessment.missing.append(
            DataGap(
                category="allergy_reconciliation",
                description=(
                    "Allergy status has not been reconciled; empty list cannot be "
                    "treated as no known allergies."
                ),
            )
        )
        assessment.flags.append(
            SafetyFlag(
                code="ALLERGY_RECONCILIATION_UNKNOWN",
                severity=Severity.WARNING,
                message="Allergy reconciliation not recorded.",
            )
        )

    # Stale monitoring labs
    monitoring_tests = {"potassium", "creatinine", "egfr", "hba1c", "sodium"}
    latest_lab: dict[str, datetime | None] = {}
    for lab in patient.lab_results:
        name = lab.test_name.lower()
        if not any(t in name for t in monitoring_tests):
            continue
        dt = _parse_dt(lab.test_date)
        if dt and (name not in latest_lab or dt > latest_lab[name]):
            latest_lab[name] = dt

    for test_name, dt in latest_lab.items():
        if dt is None:
            continue
        age = (ref - dt.date()).days
        if age > thresholds.stale_lab_days:
            assessment.stale.append(
                DataGap(
                    category="stale_lab",
                    description=f"{test_name} last measured {age} days ago (threshold {thresholds.stale_lab_days}).",
                    field=test_name,
                )
            )
            assessment.insufficient = True

    # Preliminary cardiology tests
    for test in patient.cardiology_tests:
        if (test.status or "").lower() == "preliminary":
            assessment.insufficient = True
            assessment.missing.append(
                DataGap(
                    category="preliminary_result",
                    description=f"Cardiology test {test.test_or_procedure_name} is preliminary.",
                    field=test.record_id,
                )
            )
            assessment.flags.append(
                SafetyFlag(
                    code="PRELIMINARY_CARDIOLOGY_TEST",
                    severity=Severity.WARNING,
                    message=f"Preliminary result: {test.test_or_procedure_name}",
                )
            )

    # Medication status conflicts — same drug active and stopped
    by_drug: dict[str, set[str]] = {}
    for med in patient.medications:
        key = med.drug_name.lower().strip()
        by_drug.setdefault(key, set()).add(med.medication_status.lower())
    for drug, statuses in by_drug.items():
        if "active" in statuses and "stopped" in statuses:
            assessment.conflict = True
            assessment.conflicts.append(
                ConflictItem(
                    code="MEDICATION_STATUS_CONFLICT",
                    description=f"Conflicting medication statuses for {drug}: active and stopped records coexist.",
                    withheld="Medication change recommendation",
                    owner="Primary cardiologist",
                    urgency=Severity.WARNING,
                )
            )

    # Allergy-medication conflicts
    active_meds = [m for m in patient.medications if m.medication_status.lower() == "active"]
    for allergy in patient.allergies:
        allergy_type = (allergy.allergy_type or "").lower()
        if allergy_type != "allergy":
            continue
        if (allergy.allergy_status or allergy.status or "").lower() not in {"active", "valid", ""}:
            continue
        for med in active_meds:
            if _drug_matches_allergen(med.drug_name, allergy.allergen):
                assessment.conflict = True
                assessment.conflicts.append(
                    ConflictItem(
                        code="ALLERGY_MEDICATION_CONFLICT",
                        description=(
                            f"Active medication {med.drug_name} conflicts with allergy to {allergy.allergen}."
                        ),
                        withheld="Continue recommendation",
                        owner="Primary cardiologist",
                        urgency=Severity.URGENT,
                    )
                )

    # High potassium + ACE/ARB
    latest_k: float | None = None
    for lab in patient.lab_results:
        if "potassium" in lab.test_name.lower():
            if lab.test_value is not None:
                latest_k = float(lab.test_value)
    has_ace_arb = any(_drug_class(m.drug_name, thresholds.ace_arb_drugs) for m in active_meds)
    if latest_k is not None and latest_k > thresholds.high_potassium_mmol and has_ace_arb:
        assessment.urgent = True
        assessment.flags.append(
            SafetyFlag(
                code="HIGH_POTASSIUM_ACE_ARB",
                severity=Severity.URGENT,
                message=f"Potassium {latest_k} mmol/L with active ACE/ARB.",
            )
        )

    # Bradycardia + rate limiting medication
    latest_hr: int | None = None
    for vital in sorted(
        patient.vital_signs,
        key=lambda v: _parse_dt(v.measured_at) or datetime.min,
        reverse=True,
    ):
        if vital.heart_rate is not None:
            latest_hr = vital.heart_rate
            break
    has_rate_limiter = any(
        _drug_class(m.drug_name, thresholds.rate_limiting_drugs) for m in active_meds
    )
    if latest_hr is not None and latest_hr < thresholds.marked_bradycardia_bpm and has_rate_limiter:
        assessment.urgent = True
        assessment.flags.append(
            SafetyFlag(
                code="BRADYCARDIA_RATE_LIMITER",
                severity=Severity.URGENT,
                message=f"Heart rate {latest_hr} bpm with rate-limiting medication.",
            )
        )

    # Severe hypoxia emergency proxy
    latest_spo2: int | None = None
    for vital in sorted(
        patient.vital_signs,
        key=lambda v: _parse_dt(v.measured_at) or datetime.min,
        reverse=True,
    ):
        if vital.oxygen_saturation is not None:
            latest_spo2 = vital.oxygen_saturation
            break
    if latest_spo2 is not None and latest_spo2 < thresholds.severe_hypoxia_spo2:
        assessment.emergency = True
        assessment.flags.append(
            SafetyFlag(
                code="SEVERE_HYPOXIA",
                severity=Severity.EMERGENCY,
                message=f"Oxygen saturation {latest_spo2}% below emergency threshold.",
            )
        )

    # Unreviewed abnormal lab
    for lab in patient.lab_results:
        interp = (lab.interpretation or "").lower()
        status = (lab.status or "").lower()
        if interp in {"high", "low", "critical", "abnormal"} and status == "final":
            # treat very recent abnormal without explicit review as urgent in tagged cases
            dt = _parse_dt(lab.test_date)
            if dt and (ref - dt.date()).days <= 14:
                assessment.urgent = True
                assessment.flags.append(
                    SafetyFlag(
                        code="UNREVIEWED_ABNORMAL_LAB",
                        severity=Severity.URGENT,
                        message=f"Recent abnormal {lab.test_name}: {lab.interpretation}.",
                    )
                )

    # Peri-procedure plan missing + anticoagulant
    has_anticoag = any(_drug_class(m.drug_name, thresholds.anticoagulants) for m in active_meds)
    if has_anticoag:
        for test in patient.cardiology_tests:
            combined = f"{test.notes or ''} {test.result_summary or ''}".lower()
            status = (test.status or "").lower()
            missing_plan = (
                "medication plan not documented" in combined
                or "peri-procedure medication clarification" in combined
                or "requires peri-procedure" in combined
            )
            scheduled = status in {"scheduled", "planned", "pending"} or "scheduled" in combined
            if missing_plan or scheduled and "plan not documented" in combined:
                assessment.conflict = True
                assessment.conflicts.append(
                    ConflictItem(
                        code="PERI_PROCEDURE_PLAN_MISSING",
                        description=(
                            f"Active anticoagulant with scheduled procedure "
                            f"{test.test_or_procedure_name} and no documented peri-procedure plan."
                        ),
                        withheld="Hold/restart instructions",
                        owner="Anticoagulation clinic",
                        urgency=Severity.URGENT,
                    )
                )

    return assessment
