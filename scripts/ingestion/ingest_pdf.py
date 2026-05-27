import argparse
import hashlib
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from pypdf import PdfReader
except ImportError:
    print("Missing dependency: pypdf. Install it with: pip install pypdf")
    raise SystemExit(1)

from scripts.utils.clean_text import clean_email_text


def safe_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_handle(value):
    return str(value or "").strip().lstrip("@")


def collect_pdf_paths(inputs):
    pdf_paths = []

    for raw_input in inputs:
        path = Path(raw_input)

        if path.is_dir():
            pdf_paths.extend(sorted(path.glob("*.pdf")))
        elif path.suffix.lower() == ".pdf":
            pdf_paths.append(path)

    return pdf_paths


def extract_pdf_text(pdf_path):
    reader = PdfReader(str(pdf_path))
    pages = []

    for page in reader.pages:
        text = page.extract_text() or ""
        text = clean_email_text(text)

        if text.strip():
            pages.append(text.strip())

    extracted_text = "\n\n".join(pages).strip()
    title = ""

    try:
        metadata = reader.metadata or {}
        title = str(metadata.get("/Title") or "").strip()
    except Exception:
        title = ""

    return extracted_text, title, len(reader.pages)


def source_name_from_path(pdf_path, metadata_title):
    if metadata_title:
        return metadata_title

    return pdf_path.stem.replace("_", " ").replace("-", " ").title()


def output_path_for(pdf_path, output_dir):
    path_hash = hashlib.sha256(
        str(pdf_path.resolve()).encode("utf-8")
    ).hexdigest()[:10]
    safe_stem = pdf_path.stem.replace(" ", "_")
    return output_dir / f"{safe_stem}-{path_hash}.jsonl"


def build_record(pdf_path, args):
    extracted_text, metadata_title, page_count = extract_pdf_text(pdf_path)

    if not extracted_text.strip():
        return None

    source_name = args.source_name or source_name_from_path(
        pdf_path,
        metadata_title
    )
    subject = args.subject or metadata_title or source_name
    normalized_content = extracted_text.lower().strip()
    dedupe_hash = hashlib.sha256(
        normalized_content.encode("utf-8")
    ).hexdigest()[:16]

    record = {
        "source_type": "pdf",
        "source_file": str(pdf_path.resolve()),
        "source_id": pdf_path.name,
        "source_name": source_name,
        "source_domain": "",
        "known_source": "False",
        "subject": subject,
        "priority": args.priority,
        "importance_score": safe_int(args.importance_score, 1),
        "verticals": args.verticals,
        "content": extracted_text,
        "content_preview": extracted_text[:400],
        "dedupe_hash": dedupe_hash,
        "item_id": dedupe_hash,
        "timestamp": datetime.now(UTC).isoformat(),
        "page_count": page_count,
        "pdf_title": metadata_title,
        "raw_text": extracted_text
    }

    if args.source_handle:
        record["source_handle"] = normalize_handle(args.source_handle)

    if args.source_url:
        record["source_url"] = args.source_url

    return record


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from local PDFs and write normalized JSONL intake records."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="One or more PDF files or directories containing PDFs."
    )
    parser.add_argument(
        "--source-name",
        default="",
        help="Optional source name to stamp onto every extracted PDF."
    )
    parser.add_argument(
        "--source-handle",
        default="",
        help="Optional source handle or owner name for traceability."
    )
    parser.add_argument(
        "--source-url",
        default="",
        help="Optional source URL to keep with the extracted record."
    )
    parser.add_argument(
        "--subject",
        default="",
        help="Optional subject override."
    )
    parser.add_argument(
        "--priority",
        default="low",
        choices=["low", "medium", "high"],
        help="Priority to stamp on the extracted record."
    )
    parser.add_argument(
        "--importance-score",
        default=1,
        help="Importance score to stamp on the extracted record."
    )
    parser.add_argument(
        "--vertical",
        dest="verticals",
        action="append",
        default=[],
        help="Optional vertical tag. Repeat to assign multiple verticals."
    )
    parser.add_argument(
        "--output-dir",
        default="data/intake/pdf",
        help="Directory where normalized JSONL files will be written."
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = collect_pdf_paths(args.inputs)

    if not pdf_paths:
        print("No PDF files found.")
        raise SystemExit(0)

    for pdf_path in pdf_paths:
        record = build_record(pdf_path, args)

        if not record:
            print(f"Skipped empty PDF: {pdf_path}")
            continue

        output_path = output_path_for(pdf_path, output_dir)
        output_path.write_text(json.dumps(record) + "\n")
        print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
