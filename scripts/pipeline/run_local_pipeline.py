import subprocess

print("\n=== Running local AEON intelligence pipeline ===\n")

steps = [
    ["python3", "scripts/ingestion/classify_email.py"],
    ["python3", "scripts/ingestion/summarize_items.py"],
    ["python3", "scripts/ingestion/cluster_items.py"],
    ["python3", "scripts/ingestion/extract_alert_candidates.py"],
    ["python3", "scripts/ingestion/build_digest.py"],
]

for step in steps:
    print(f"\nRunning: {' '.join(step)}")
    result = subprocess.run(step)

    if result.returncode != 0:
        print("\nPipeline failed.")
        raise SystemExit(result.returncode)

print("\nPipeline complete.")
