import json
import re
from collections import defaultdict
from pathlib import Path

log_path = Path("data/processed/intake_log.jsonl")
output_path = Path("data/processed/daily_digest.md")

vertical_map = defaultdict(list)

with open(log_path, "r") as f:
    for line in f:
        if not line.strip():
            continue

        item = json.loads(line)

        for vertical in item.get("verticals", []):
            vertical_map[vertical].append(item)

lines = []
lines.append("# Daily Intelligence Digest\n")

for vertical, items in sorted(vertical_map.items()):

    lines.append(f"\n## {vertical}\n")

    for item in items[-5:]:

        preview = item["content_preview"].replace("\n", " ").strip()

        preview = re.sub(r"https?://\S+", "", preview)
        preview = re.sub(r"\s+", " ", preview).strip()

        source = item["source_file"]
        item_id = item.get("item_id", "no-id")

        lines.append(
            f"- `{item_id}` — **{source}** — {preview[:180]}..."
        )

digest = "\n".join(lines)

output_path.write_text(digest)

print(digest)
print(f"\nSaved digest to: {output_path}")