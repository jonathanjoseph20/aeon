import yaml
import json
import hashlib
from pathlib import Path
from datetime import datetime, UTC

with open("config/verticals.yml", "r") as f:
    verticals = yaml.safe_load(f)

email_folder = Path("data/intake/email")
log_path = Path("data/processed/intake_log.jsonl")
log_path.parent.mkdir(parents=True, exist_ok=True)
log_path.touch(exist_ok=True)

existing_ids = set()

with open(log_path, "r") as f:
    for line in f:
        if line.strip():
            existing_ids.add(json.loads(line).get("item_id"))

files = sorted(email_folder.glob("*.txt"))

for email_path in files:
    content = email_path.read_text()
    normalized = content.strip().lower()

    item_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    if item_id in existing_ids:
        print(f"Skipped duplicate: {email_path.name}")
        continue

    scores = {}

    for vertical, data in verticals.items():
        keywords = data.get("keywords", [])
        score = 0

        for keyword in keywords:
            score += normalized.count(keyword.lower())

        scores[vertical] = score

    matched_verticals = [
        vertical for vertical, score in scores.items()
        if score >= 2
    ]

    record = {
        "item_id": item_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "source_type": "email_manual",
        "source_file": str(email_path),
        "verticals": matched_verticals,
        "scores": scores,
        "content_preview": content[:200]
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"Processed: {email_path.name} → {matched_verticals}")