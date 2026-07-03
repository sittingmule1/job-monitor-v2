"""
main.py
=======
Entry point. Pipeline:
  1. Pull new emails under the Job Alerts label
  2. Route each to its parser based on sender
  3. Fetch ATS sources directly (independent of email)
  4. Dedupe everything together
  5. Score + render digest
  6. Write to docs/index.html for GitHub Pages
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.sources import EMAIL_SOURCES, ATS_SOURCES
from src.parsers import PARSER_REGISTRY
from src.ats_fetchers import run_all_ats_fetchers
from src.dedupe import dedupe_and_mark
from src.digest import render
from src.gmail_client import fetch_new_messages

DOCS_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "index.html")


def match_source(sender):
    sender = (sender or "").lower()
    for src in EMAIL_SOURCES:
        if any(pattern in sender for pattern in src["match"]):
            return src
    return None


def run():
    print("Pulling new Job Alerts emails...")
    emails = fetch_new_messages()
    print(f"  {len(emails)} new emails")

    all_records = []

    for email in emails:
        src = match_source(email["sender"])
        if not src:
            # Unrecognized sender under the label — surface as manual-check
            # rather than silently dropping it.
            all_records.append({
                "title": f"(unrecognized sender: {email['sender']})",
                "company": None,
                "link": None,
                "source": "Unmapped sender",
                "confidence": "manual_check",
                "raw_subject": email["subject"],
            })
            continue
        parser = PARSER_REGISTRY[src["parser"]]
        records = parser(src["name"], src["confidence"], email["subject"], email["sender"], email["html_body"])
        all_records.extend(records)

    print("Fetching ATS sources directly (Verizon, PBS, EchoStar, NBCUniversal)...")
    ats_records = run_all_ats_fetchers(ATS_SOURCES)
    print(f"  {len(ats_records)} postings from direct ATS fetch")
    all_records.extend(ats_records)

    print("Deduplicating...")
    new_records, merged_records = dedupe_and_mark(all_records)
    print(f"  {len(new_records)} new, {len(merged_records)} total tracked")

    print("Rendering digest...")
    html = render(merged_records, len(new_records))
    os.makedirs(os.path.dirname(DOCS_PATH), exist_ok=True)
    with open(DOCS_PATH, "w") as f:
        f.write(html)
    print(f"Digest written to {DOCS_PATH}")


if __name__ == "__main__":
    run()
