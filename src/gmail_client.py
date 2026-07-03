"""
gmail_client.py
===============
Pulls messages under the "Job Alerts" label since the last recorded run.

Auth: uses a refresh token generated once locally (see README "Gmail API
setup"), stored as a GitHub secret and exchanged for an access token on
each Action run. No user interaction needed after the initial setup.
"""

import base64
import json
import os
import time
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

LAST_RUN_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "last_run.json")
LABEL_NAME = "Job Alerts"


def _get_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds)


def _get_last_run():
    if not os.path.exists(LAST_RUN_PATH):
        return int(time.time()) - 86400  # default: last 24h on first run
    with open(LAST_RUN_PATH) as f:
        return json.load(f)["epoch"]


def _save_last_run(epoch):
    os.makedirs(os.path.dirname(LAST_RUN_PATH), exist_ok=True)
    with open(LAST_RUN_PATH, "w") as f:
        json.dump({"epoch": epoch}, f)


def _find_label_id(service, name):
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"] == name:
            return l["id"]
    raise ValueError(f"Label '{name}' not found — check it exists exactly as named in Gmail.")


def _extract_html(payload):
    if payload.get("mimeType") == "text/html" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        html = _extract_html(part)
        if html:
            return html
    return None


def fetch_new_messages():
    """Returns list of {subject, sender, html_body} for messages under the
    Job Alerts label newer than the last recorded run, and advances the
    last-run marker to now."""
    service = _get_service()
    label_id = _find_label_id(service, LABEL_NAME)
    since_epoch = _get_last_run()
    now_epoch = int(time.time())

    # NOTE: label filtering is done via labelIds, not embedded in the query
    # string — Gmail's `label:` search operator expects a label *name*, and
    # we only have the internal ID at this point. Mixing the two silently
    # returns zero results with no error, so keep them separate.
    query = f"after:{since_epoch}"
    messages = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, labelIds=[label_id], pageToken=page_token, maxResults=100
        ).execute()
        messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    results = []
    for m in messages:
        msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        results.append({
            "subject": headers.get("Subject", ""),
            "sender": headers.get("From", ""),
            "html_body": _extract_html(msg["payload"]),
        })

    _save_last_run(now_epoch)
    return results
