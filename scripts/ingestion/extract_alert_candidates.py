import json
from pathlib import Path

log_path = Path("data/processed/intake_log.jsonl")
alert_path = Path("data/processed/alert_candidates.jsonl")

alert_path.parent.mkdir(parents=True, exist_ok=True)

if not log_path.exists():
    print("No intake log found.")
    raise SystemExit(0)

alerts = []

for line in log_path.read_text().splitlines():
    if not line.strip():
        continue

    item = json.loads(line)

    importance_score = int(item.get("importance_score", 1))
    watchlist_hits = item.get("watchlist_hits", [])

    if importance_score >= 8 or watchlist_hits:
        alerts.append(item)

with alert_path.open("w") as f:
    for item in alerts:
        f.write(json.dumps(item) + "\n")

print(f"Extracted {len(alerts)} alert candidates.")