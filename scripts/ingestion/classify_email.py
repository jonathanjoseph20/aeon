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

    raw_content = email_path.read_text()

    metadata = {
        "source_name": "Unknown",
        "sender": "",
        "subject": "",
        "priority": "low",
        "importance_score": 1
    }

    body_lines = []

    for line in raw_content.splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("SOURCE:"):
            metadata["source_name"] = line.replace("SOURCE:", "").strip()

        elif line.startswith("SENDER:"):
            metadata["sender"] = line.replace("SENDER:", "").strip()

        elif line.startswith("SUBJECT:"):
            metadata["subject"] = line.replace("SUBJECT:", "").strip()

        elif line.startswith("PRIORITY:"):
            metadata["priority"] = line.replace("PRIORITY:", "").strip()

        elif line.startswith("IMPORTANCE_SCORE:"):
            metadata["importance_score"] = int(
                line.replace("IMPORTANCE_SCORE:", "").strip()
            )

        else:
            body_lines.append(line)

    content = " ".join(body_lines).strip()

    normalized = content.lower()

    item_id = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:16]

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
        "source_name": metadata["source_name"],
        "sender": metadata["sender"],
        "subject": metadata["subject"],
        "priority": metadata["priority"],
        "importance_score": metadata["importance_score"],
        "verticals": matched_verticals,
        "scores": scores,
        "content_preview": content[:200]
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"Processed: {email_path.name} → {matched_verticals}")