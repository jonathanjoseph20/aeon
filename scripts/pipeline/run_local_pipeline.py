import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_config import load_source_entries, normalize_source_type


INGESTION_DIR = REPO_ROOT / "scripts" / "ingestion"
HERMES_DIR = REPO_ROOT / "scripts" / "hermes"
SLACK_DIR = REPO_ROOT / "scripts" / "slack"
DEFAULT_SOURCES_FILE = REPO_ROOT / "config" / "sources.yml"
DEFAULT_PDF_INPUT_DIR = REPO_ROOT / "data" / "intake" / "pdf"
DEFAULT_GMAIL_TOKEN = REPO_ROOT / "credentials" / "token.json"
DEFAULT_GMAIL_CREDENTIALS = REPO_ROOT / "credentials" / "gmail_credentials.json"


def load_yaml(path):
    if not Path(path).exists():
        return {}

    with Path(path).open("r") as handle:
        return yaml.safe_load(handle) or {}


def has_configured_gmail(token_path, credentials_path):
    return Path(token_path).exists() or Path(credentials_path).exists()


def has_pdf_inputs(pdf_input_dir):
    pdf_input_dir = Path(pdf_input_dir)

    if not pdf_input_dir.exists():
        return False

    return any(pdf_input_dir.glob("*.pdf"))


def has_twitter_feeds(sources_file):
    for entry in load_source_entries(sources_file):
        if normalize_source_type(entry.get("source_type")) == "twitter" and entry.get("feed_urls"):
            return True

    return False


def build_command(script_name, *args):
    return [
        sys.executable,
        str(INGESTION_DIR / script_name),
        *[str(arg) for arg in args],
    ]


def build_hermes_command(script_name, *args):
    return [
        sys.executable,
        str(HERMES_DIR / script_name),
        *[str(arg) for arg in args],
    ]


def build_slack_command(script_name, *args):
    return [
        sys.executable,
        str(SLACK_DIR / script_name),
        *[str(arg) for arg in args],
    ]


def build_subprocess_env():
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_entries = [str(REPO_ROOT)]

    for entry in existing_pythonpath.split(os.pathsep):
        entry = entry.strip()

        if entry and entry not in pythonpath_entries:
            pythonpath_entries.append(entry)

    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return env


def build_pipeline_steps(
    sources_file=DEFAULT_SOURCES_FILE,
    pdf_input_dir=DEFAULT_PDF_INPUT_DIR,
    gmail_token_path=DEFAULT_GMAIL_TOKEN,
    gmail_credentials_path=DEFAULT_GMAIL_CREDENTIALS,
):
    notes = []
    steps = []

    if has_configured_gmail(gmail_token_path, gmail_credentials_path):
        steps.append(
            {
                "label": "Fetch Gmail intake",
                "command": build_command("fetch_gmail.py"),
            }
        )
        steps.append(
            {
                "label": "Promote Gmail source candidates",
                "command": build_command("promote_source_candidates.py"),
            }
        )
    else:
        notes.append("Skipping Gmail intake: no Gmail token or credentials were found.")

    if has_pdf_inputs(pdf_input_dir):
        steps.append(
            {
                "label": "Ingest local PDFs",
                "command": build_command("ingest_pdf.py", pdf_input_dir),
            }
        )
    else:
        notes.append(f"Skipping PDF ingestion: no PDFs found in {pdf_input_dir}.")

    if has_twitter_feeds(sources_file):
        steps.append(
            {
                "label": "Fetch configured Twitter feeds",
                "command": build_command(
                    "fetch_twitter.py",
                    "--feeds",
                    "--sources-file",
                    sources_file,
                ),
            }
        )
    else:
        notes.append("Skipping Twitter feed ingestion: no feed URLs are configured.")

    steps.extend(
        [
            {
                "label": "Classify normalized intake",
                "command": build_command("classify_email.py"),
            },
            {
                "label": "Summarize / preview items",
                "command": build_command("summarize_items.py"),
            },
            {
                "label": "Cluster items",
                "command": build_command("cluster_items.py"),
            },
            {
                "label": "Extract alert candidates",
                "command": build_command("extract_alert_candidates.py"),
            },
            {
                "label": "Promote high-signal items to Hermes",
                "command": build_command("promote_to_hermes.py"),
            },
            {
                "label": "Build source metrics",
                "command": build_command("build_source_metrics.py"),
            },
            {
                "label": "Build entity summary",
                "command": build_command("build_entity_summary.py"),
            },
            {
                "label": "Build narrative summary",
                "command": build_command("build_narrative_summary.py"),
            },
            {
                "label": "Build Hermes synthesis",
                "command": build_hermes_command("build_synthesis.py"),
            },
            {
                "label": "Build digest",
                "command": build_command("build_digest.py"),
            },
            {
                "label": "Build Slack-safe digest payload",
                "command": build_command("build_slack_digest_payload.py"),
            },
            {
                "label": "Build Slack command-center payload",
                "command": build_slack_command("build_command_payload.py"),
            },
        ]
    )

    return steps, notes


def run_pipeline(steps, dry_run=False):
    if dry_run:
        print("\nDry run: the following steps would run:\n")

        for index, step in enumerate(steps, start=1):
            print(f"{index}. {step['label']}")
            print(f"   {' '.join(step['command'])}")

        return 0

    for step in steps:
        print(f"\nRunning: {step['label']}")
        print(f"Command: {' '.join(step['command'])}")

        result = subprocess.run(
            step["command"],
            cwd=REPO_ROOT,
            env=build_subprocess_env(),
        )

        if result.returncode != 0:
            print(f"\nPipeline failed at: {step['label']}")
            raise SystemExit(result.returncode)

    print("\nPipeline complete.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run the deterministic AEON daily pipeline locally."
    )
    parser.add_argument(
        "--sources-file",
        default=str(DEFAULT_SOURCES_FILE),
        help="YAML file used to detect configured Twitter feed URLs.",
    )
    parser.add_argument(
        "--pdf-input-dir",
        default=str(DEFAULT_PDF_INPUT_DIR),
        help="Directory that holds local PDF inputs.",
    )
    parser.add_argument(
        "--gmail-token",
        default=str(DEFAULT_GMAIL_TOKEN),
        help="Path to Gmail OAuth token JSON.",
    )
    parser.add_argument(
        "--gmail-credentials",
        default=str(DEFAULT_GMAIL_CREDENTIALS),
        help="Path to Gmail OAuth client credentials JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned pipeline steps without executing them.",
    )

    args = parser.parse_args()

    print("\n=== Running local AEON daily pipeline ===\n")

    steps, notes = build_pipeline_steps(
        sources_file=Path(args.sources_file),
        pdf_input_dir=Path(args.pdf_input_dir),
        gmail_token_path=Path(args.gmail_token),
        gmail_credentials_path=Path(args.gmail_credentials),
    )

    for note in notes:
        print(note)

    return run_pipeline(steps, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
