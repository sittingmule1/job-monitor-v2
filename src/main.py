"""
main.py
=======
Entry point. Pipeline:
  1. Pull new emails under the Job Alerts label
  2. Route each to its parser based on sender
  3. Dedupe everything together
  4. Score + render digest
  5. Write to docs/index.html for GitHub Pages

No standalone ATS crawl — Verizon/PBS/NBCU/EchoStar are email-driven sources
like everything else; a per-posting lookup (not a company-wide pull) is the
planned addition once a real sample email exists for one of them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.sources import EMAIL_SOURCES
from src.parsers import PARSER_REGISTRY
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

    # No company-wide ATS crawl. Verizon/PBS/NBCU/EchoStar have no real
    # email samples yet — per-posting lookup (triggered by a specific job
    # link inside an actual alert email) will replace this once we have one
    # to build the parser from. Until then these sources stay untouched.

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
