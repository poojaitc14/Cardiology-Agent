from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.repositories.policy import PolicyChunk, PolicyRetriever, RetrievalResult
from cardiologist_agent.retrieval.ingest import ingest_runtime_policies, load_index, save_index


class LocalPolicyRetriever(PolicyRetriever):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._chunks: list[PolicyChunk] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._allowlist = self._load_allowlist()
        self._ensure_index()

    def _load_allowlist(self) -> dict:
        path = self.settings.resolve(Path("config/retrieval_allowlist.yaml"))
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _ensure_index(self) -> None:
        index_path = self.settings.index_file
        if index_path.exists():
            self._chunks = load_index(index_path)
        else:
            self._chunks = ingest_runtime_policies(self.settings)
            save_index(self._chunks, index_path)
        self._chunks = [
            c
            for c in self._chunks
            if c.corpus_eligibility in self._allowlist.get("runtime_eligible_corpus", ["runtime"])
            and c.document_id not in self._allowlist.get("denied_document_ids", [])
        ]
        if self._chunks:
            self._vectorizer = TfidfVectorizer(stop_words="english")
            texts = [c.text for c in self._chunks]
            self._matrix = self._vectorizer.fit_transform(texts)

    async def retrieve(self, query: str, top_k: int = 5) -> RetrievalResult:
        if not self._chunks or self._vectorizer is None or self._matrix is None:
            return RetrievalResult(chunks=[], query=query, coverage_adequate=False)

        query_vec = self._vectorizer.transform([query])
        scores = (self._matrix @ query_vec.T).toarray().ravel()
        min_score = float(self._allowlist.get("min_retrieval_score", 0.05))
        top_k = int(self._allowlist.get("top_k", top_k))
        ranked = np.argsort(scores)[::-1]
        selected: list[PolicyChunk] = []
        for idx in ranked:
            if scores[idx] < min_score:
                continue
            chunk = self._chunks[int(idx)]
            if chunk.corpus_eligibility in self._allowlist.get("denied_corpus_eligibility", []):
                continue
            selected.append(chunk)
            if len(selected) >= top_k:
                break

        contamination = any(c.corpus_eligibility == "evaluation" for c in selected)
        coverage = len(selected) >= 1 and max(scores) >= min_score
        return RetrievalResult(
            chunks=selected,
            query=query,
            coverage_adequate=coverage and not contamination,
            contamination_detected=contamination,
        )
