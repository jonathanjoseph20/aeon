import json
from collections import defaultdict
from pathlib import Path

candidate_path = Path("data/metadata/source_candidates.jsonl")
registry_path = Path("data/metadata/email_sources.json")

if not candidate_path.exists():
    print("No source candidates found.")
    raise SystemExit(0)

with registry_path.open("r") as f:
    registry = json.load(f)

counts = defaultdict(list)

for line in candidate_path.read_text().splitlines():

    if not line.strip():
        continue

    item = json.loads(line)

    domain = item.get("domain")

    if not domain:
        continue

    counts[domain].append(item)

promoted = 0

for domain, items in counts.items():

    if domain in registry:
        continue

    if len(items) < 3:
        continue

    latest = items[-1]

    registry[domain] = {
        "name": latest.get("suggested_name", domain),
        "default_verticals": [],
        "priority": latest.get("priority", "low"),
        "importance_score": latest.get("importance_score", 1),
        "auto_learned": True
    }

    promoted += 1

    print(f"Promoted source: {domain}")

with registry_path.open("w") as f:
    json.dump(registry, f, indent=2)

print(f"Promoted {promoted} sources.")