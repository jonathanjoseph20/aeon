import json
from pathlib import Path

log_path = Path("data/processed/intake_log.jsonl")

if not log_path.exists():
    print("No intake log found.")
    raise SystemExit(0)

records = []

for line in log_path.read_text().splitlines():
    if not line.strip():
        continue

    item = json.loads(line)

    preview = item.get("content_preview", "").strip()
    subject = item.get("subject", "").strip()
    source = item.get("source_name", "Unknown")

    summary = preview

    if len(summary) > 220:
        summary = summary[:220].rsplit(" ", 1)[0] + "..."

    item["summary"] = summary
    item["why_it_matters"] = (
        f"Source: {source}. Subject: {subject}. "
        "Included because it passed AEON classification and filtering."
    )

    records.append(item)

with log_path.open("w") as f:
    for item in records:
        f.write(json.dumps(item) + "\n")

print(f"Summarized {len(records)} items.")