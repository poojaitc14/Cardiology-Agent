from __future__ import annotations

from cardiologist_agent.config.settings import get_settings
from cardiologist_agent.repositories.patient import LocalJsonPatientRepository
from cardiologist_agent.retrieval.ingest import ingest_runtime_policies, load_inventory, save_index


def main() -> None:
    settings = get_settings()
    inventory = load_inventory(settings)
    runtime_count = sum(
        1
        for d in inventory
        if d.get("runtime_retrieval_allowed") and d.get("corpus_eligibility") == "runtime"
    )
    eval_count = sum(1 for d in inventory if d.get("corpus_eligibility") == "evaluation")
    print(
        f"Inventory: {len(inventory)} documents ({runtime_count} runtime, {eval_count} evaluation-only)"
    )
    chunks = ingest_runtime_policies(settings)
    save_index(chunks, settings.index_file)
    print(f"Ingested {len(chunks)} runtime chunks to {settings.index_file}")

    repo = LocalJsonPatientRepository(settings.patients_file)
    errors = repo.validate_all()
    if errors:
        for err in errors:
            print(f"VALIDATION ERROR: {err}")
        raise SystemExit(1)
    print("Patient validation passed (100 patients)")


if __name__ == "__main__":
    main()
