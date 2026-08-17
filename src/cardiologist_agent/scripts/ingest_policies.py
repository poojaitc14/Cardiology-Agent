from __future__ import annotations

from cardiologist_agent.config.settings import get_settings
from cardiologist_agent.retrieval.ingest import ingest_runtime_policies, save_index


def main() -> None:
    settings = get_settings()
    chunks = ingest_runtime_policies(settings)
    save_index(chunks, settings.index_file)
    print(f"Ingested {len(chunks)} runtime policy chunks (evaluation PDFs excluded)")


if __name__ == "__main__":
    main()
