import sys
from pathlib import Path
import json
import base64

sys.path.append(str(Path(__file__).resolve().parents[1]))

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from utils.clean_text import clean_email_text
from bs4 import BeautifulSoup

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

flow = InstalledAppFlow.from_client_secrets_file(
    "credentials/gmail_credentials.json",
    SCOPES
)

creds = flow.run_local_server(port=0)

service = build("gmail", "v1", credentials=creds)

with open("data/metadata/email_sources.json", "r") as f:
    source_registry = json.load(f)

# Change label here
label_id = "Label_195904735065236313"

results = service.users().messages().list(
    userId="me",
    labelIds=[label_id],
    maxResults=5
).execute()

messages = results.get("messages", [])

print(f"\nFound {len(messages)} emails\n")

output_dir = Path("data/intake/email")
output_dir.mkdir(parents=True, exist_ok=True)

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

    source_name = "Unknown"
    priority = "low"
    importance_score = 1

    for domain, metadata in source_registry.items():

        if domain.lower() in sender.lower():

            source_name = metadata["name"]
            priority = metadata["priority"]
            importance_score = metadata["importance_score"]

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

    full_content = (
        f"SOURCE: {source_name}\n"
        f"SENDER: {sender}\n"
        f"SUBJECT: {subject}\n"
        f"PRIORITY: {priority}\n"
        f"IMPORTANCE_SCORE: {importance_score}\n\n"
        f"{body_data}\n"
    )

    output_file = output_dir / f"gmail_{msg_id}.txt"

    output_file.write_text(full_content)

    print(f"Saved: {output_file.name}")