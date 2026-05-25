from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

flow = InstalledAppFlow.from_client_secrets_file(
    "credentials/gmail_credentials.json",
    SCOPES
)

creds = flow.run_local_server(port=0)

service = build("gmail", "v1", credentials=creds)

results = service.users().labels().list(userId="me").execute()

labels = results.get("labels", [])

print("\nGmail Labels:\n")

for label in labels:
    print(label["name"])