import sys
import os
from pathlib import Path
import json
import base64
import re
from email.utils import parseaddr

sys.path.append(str(Path(__file__).resolve().parents[1]))

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from utils.clean_text import clean_email_text
from bs4 import BeautifulSoup

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

token_path = "credentials/token.json"
credentials_path = "credentials/gmail_credentials.json"

Path("credentials").mkdir(parents=True, exist_ok=True)

creds = None


def infer_source_from_sender(sender):
    display_name, email = parseaddr(sender)

    domain = email.split("@")[-1].lower() if "@" in email else ""

    suggested_name = display_name.strip().replace('"', "")

    if not suggested_name and domain:
        suggested_name = (
            domain.split(".")[0]
            .replace("-", " ")
            .replace("_", " ")
            .title()
        )

    return domain, suggested_name


if os.path.exists(token_path):

    creds = Credentials.from_authorized_user_file(
        token_path,
        SCOPES
    )

if creds and creds.expired and creds.refresh_token:

    creds.refresh(Request())

if not creds or not creds.valid:

    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_path,
        SCOPES
    )

    creds = flow.run_local_server(port=0)

    with open(token_path, "w") as token:
        token.write(creds.to_json())

service = build("gmail", "v1", credentials=creds)

with open("data/metadata/email_sources.json", "r") as f:
    source_registry = json.load(f)

with open("config/gmail_labels.json", "r") as f:
    gmail_labels = json.load(f)

messages = []

for label_name, label_id in gmail_labels.items():

    results = service.users().messages().list(
        userId="me",
        labelIds=[label_id],
        maxResults=5
    ).execute()

    label_messages = results.get("messages", [])

    print(f"{label_name}: {len(label_messages)} emails found")

    for m in label_messages:
        m["aeon_gmail_label"] = label_name
        messages.append(m)

print(f"\nFound {len(messages)} emails\n")

output_dir = Path("data/intake/email")
output_dir.mkdir(parents=True, exist_ok=True)

candidate_dir = Path("data/metadata")
candidate_dir.mkdir(parents=True, exist_ok=True)

candidate_path = candidate_dir / "source_candidates.jsonl"

for msg in messages:

    msg_id = msg["id"]

    message = service.users().messages().get(
        userId="me",
        id=msg_id,
        format="full"
    ).execute()

    headers = message["payload"].get("headers", [])

    subject = ""
    sender = ""

    for header in headers:

        if header["name"] == "Subject":
            subject = header["value"]

        elif header["name"] == "From":
            sender = header["value"]

    gmail_label = msg.get("aeon_gmail_label", "")

    domain, suggested_name = infer_source_from_sender(sender)

    source_name = suggested_name or "Unknown"
    priority = "low"
    importance_score = 1
    default_verticals = []
    known_source = False

    for registered_domain, metadata in source_registry.items():

        if registered_domain.lower() in sender.lower():

            source_name = metadata["name"]
            priority = metadata["priority"]
            importance_score = metadata["importance_score"]
            default_verticals = metadata.get(
                "default_verticals",
                []
            )

            known_source = True

            break

    payload = message["payload"]

    body_data = ""

    parts = payload.get("parts", [])

    for part in parts:

        mime = part.get("mimeType")

        data = part.get("body", {}).get("data")

        if not data:
            continue

        decoded = base64.urlsafe_b64decode(
            data
        ).decode("utf-8", errors="ignore")

        if mime == "text/plain":

            body_data = decoded
            break

        elif mime == "text/html" and not body_data:

            soup = BeautifulSoup(decoded, "html.parser")

            body_data = soup.get_text(separator="\n")

    body_data = clean_email_text(body_data)

    if not body_data.strip():
        continue

    if not known_source and domain:

        candidate = {
            "domain": domain,
            "sender": sender,
            "subject": subject,
            "gmail_label": gmail_label,
            "suggested_name": source_name,
            "priority": priority,
            "importance_score": importance_score
        }

        with candidate_path.open("a") as f:
            f.write(json.dumps(candidate) + "\n")

    full_content = (
        f"SOURCE: {source_name}\n"
        f"SOURCE_DOMAIN: {domain}\n"
        f"KNOWN_SOURCE: {known_source}\n"
        f"SENDER: {sender}\n"
        f"SUBJECT: {subject}\n"
        f"PRIORITY: {priority}\n"
        f"GMAIL_LABEL: {gmail_label}\n"
        f"IMPORTANCE_SCORE: {importance_score}\n\n"
        f"{body_data}\n"
    )

    output_file = output_dir / f"gmail_{msg_id}.txt"

    output_file.write_text(full_content)

    print(f"Saved: {output_file.name}")