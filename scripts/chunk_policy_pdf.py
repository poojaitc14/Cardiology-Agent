"""Extract and structure-aware chunk the approved synthetic medication safety policy.

Run from the repository root:
    python scripts/chunk_policy_pdf.py
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


DEFAULT_PDF = Path("docs/synthetic_hospital_medication_safety_policy.pdf")
DEFAULT_OUTPUT = Path("data/synthetic_hospital_medication_safety_policy_chunks.json")
DOCUMENT_ID = "SYNTH-HMSP-001"
TITLE = "Synthetic Hospital Medication Safety Policy"
VERSION = "1.0"
EFFECTIVE_DATE = "2026-08-14"
STATUS = "APPROVED"
TARGET_TOKENS = 550
MAX_TOKENS = 700
OVERLAP_TOKENS = 75

# Valid examples: "1. Purpose and Scope", "1.1 Core safety principles",
# "4. High-Risk Medicines", and "4.1 Anticoagulants". A major heading must
# have a period, and any minor number must be non-zero; this excludes metadata
# such as "1.0 Status" and dates such as "14 August 2026".
NUMBERED_HEADING = re.compile(
    r"^(?P<number>[1-9]\d*\.(?:[1-9]\d*(?:\.[1-9]\d*)*)?)\s+(?P<title>[A-Z][^\n]{2,})$",
    re.MULTILINE,
)
MONTH_DATE = re.compile(
    r"^\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}$",
    re.IGNORECASE,
)
PAGE_ARTIFACT = re.compile(r"^(page\s+)?\d+(\s+of\s+\d+)?$", re.IGNORECASE)
DOCUMENT_CONTROL_LABEL = re.compile(
    r"^(document\s+(id|control)|version|status|effective\s+date|review\s+date|owner|approver)\b",
    re.IGNORECASE,
)
EDUCATIONAL_HEADER_FOOTER = re.compile(
    r"^(demo\s*/\s*synthetic\s+policy|educational\s+project\s+use\s+only)$",
    re.IGNORECASE,
)


@dataclass
class SectionPart:
    section: str
    page: int
    text: str


def normalize(text: str) -> str:
    text = text.replace(
        "DEMO / SYNTHETIC POLICY - Educational project use only",
        ""
    )

    text = re.sub(r"Page\s+\d+", "", text)

    return re.sub(r"\s+", " ", text).strip()


def remove_page_artifacts(page_text: str) -> str:
    """Remove standalone dates, page numbers, and document-control header/footer lines."""
    kept_lines = []
    for raw_line in page_text.splitlines():
        line = normalize(raw_line)
        if not line or MONTH_DATE.fullmatch(line) or PAGE_ARTIFACT.fullmatch(line):
            continue
        if EDUCATIONAL_HEADER_FOOTER.fullmatch(line):
            continue
        if DOCUMENT_CONTROL_LABEL.match(line) and len(line) < 100:
            continue
        kept_lines.append(raw_line)
    return "\n".join(kept_lines)


def token_count(text: str) -> int:
    """A lightweight approximation suitable for chunk-size control."""
    return len(re.findall(r"\S+", text))


def trailing_tokens(text: str, count: int) -> str:
    tokens = re.findall(r"\S+", text)
    return " ".join(tokens[-count:])


def split_section(section: str, parts: list[SectionPart]) -> list[dict]:
    """Keep section boundaries intact; overlap only when the section exceeds max size."""
    units = [SectionPart(section, part.page, normalize(part.text)) for part in parts if normalize(part.text)]
    if not units:
        return []

    chunks: list[dict] = []
    current_text = ""
    pages: list[int] = []

    def emit() -> None:
        if not current_text:
            return
        chunks.append({
            "document_id": DOCUMENT_ID,
            "title": TITLE,
            "version": VERSION,
            "status": STATUS,
            "effective_date": EFFECTIVE_DATE,
            "section": section,
            "page": str(pages[0]) if len(set(pages)) == 1 else f"{pages[0]}-{pages[-1]}",
            "text": f"{section}\n\n{current_text}",
        })

    for unit in units:
        candidate = f"{current_text} {unit.text}".strip()
        if current_text and token_count(candidate) > MAX_TOKENS:
            emit()
            # Do not overlap normal neighbouring sections. This overlap exists
            # only because one numbered section needs multiple chunks.
            current_text = trailing_tokens(current_text, OVERLAP_TOKENS)
            pages = [pages[-1]] if pages else []
        current_text = f"{current_text} {unit.text}".strip()
        pages.append(unit.page)

    emit()
    return chunks


def extract_section_parts(pdf_path: Path) -> list[SectionPart]:
    reader = PdfReader(str(pdf_path))
    active_section = "Unnumbered introductory content"
    parts: list[SectionPart] = []

    for page_number, page in enumerate(reader.pages, start=1):
        # The cover page is document control/front matter, never clinical RAG content.
        if page_number == 1:
            continue
        page_text = remove_page_artifacts(page.extract_text() or "")
        matches = list(NUMBERED_HEADING.finditer(page_text))
        if not matches:
            if normalize(page_text):
                parts.append(SectionPart(active_section, page_number, page_text))
            continue

        # Preserve any text before the first heading under the preceding section.
        prefix = page_text[:matches[0].start()]
        if normalize(prefix):
            parts.append(SectionPart(active_section, page_number, prefix))

        for index, match in enumerate(matches):
            active_section = f"{match.group('number')} {normalize(match.group('title'))}"
            content_start = match.end()
            content_end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
            content = page_text[content_start:content_end]
            if normalize(content):
                parts.append(SectionPart(active_section, page_number, content))
    return parts


def build_chunks(pdf_path: Path) -> list[dict]:
    by_section: dict[str, list[SectionPart]] = {}

    for part in extract_section_parts(pdf_path):
        by_section.setdefault(part.section, []).append(part)

    chunks: list[dict] = []

    for section, parts in by_section.items():
        chunks.extend(split_section(section, parts))

    chunks = [
        chunk
        for chunk in chunks
        if chunk["section"] != "Unnumbered introductory content"
    ]

    return chunks

def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk an approved medication-policy PDF for later RAG ingestion.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.pdf.is_file():
        raise FileNotFoundError(f"Policy PDF not found: {args.pdf}")

    chunks = build_chunks(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Chunks created: {len(chunks)}")
    print("First 3 chunks:")
    print(json.dumps(chunks[:3], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
