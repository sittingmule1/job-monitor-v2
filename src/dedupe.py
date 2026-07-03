"""
dedupe.py
=========
Collapses duplicate postings (same job surfaced via multiple searches/
senders) and tracks what's already been shown so re-runs don't repeat
yesterday's digest.

State lives in state/seen_jobs.json — a flat list of hashes with a cap on
age so the file doesn't grow forever.
"""

import datetime
import hashlib
import json
import os
import time

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "seen_jobs.json")
RETENTION_DAYS = 45


def _normalize(text):
    if not text:
        return ""
    return "".join(ch.lower() for ch in text if ch.isalnum())


def job_hash(record):
    """
    Hashes on title+company when both are available. When a parser couldn't
    extract either (both None), falling back to those blank strings would
    hash every unparsed record from a given source to the SAME key — silently
    collapsing genuinely distinct postings into one. Fall back to the raw
    subject line instead, which is still distinct per email even when we
    can't tell what job it refers to.

    Flag-only records (constant placeholder title, e.g. "check site directly")
    are day-scoped: without this, the first time a company like Paramount
    fires a flag-only email it shows as NEW, and every subsequent day's email
    for that same company gets marked "already seen" even though a fresh
    email genuinely arrived that day. Since presence in this run's email pull
    already means something changed, these should read as new on every day
    they appear; scoping the hash to today's date achieves that while still
    collapsing duplicate emails within the same run/day into one entry.
    """
    title = record.get("title")
    company = record.get("company")
    if not title and not company:
        base = _normalize(record.get("raw_subject")) or _normalize(record.get("source"))
    else:
        base = _normalize(title) + "|" + _normalize(company)

    if record.get("ephemeral"):
        base += "|" + datetime.date.today().isoformat()

    return hashlib.sha256(base.encode()).hexdigest()


def load_seen():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH) as f:
        return json.load(f)


def save_seen(seen):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(seen, f)


def dedupe_and_mark(records):
    """Returns (new_records, merged_records) where merged_records collapses
    exact title+company duplicates within this run and tags each with the
    list of sources that surfaced it."""
    seen = load_seen()
    now = time.time()
    cutoff = now - RETENTION_DAYS * 86400
    seen = {h: ts for h, ts in seen.items() if ts > cutoff}

    merged = {}
    for rec in records:
        h = job_hash(rec)
        if h in merged:
            merged[h]["sources"].append(rec["source"])
            # Keep the highest-confidence version of the record
            tier_rank = {"verified": 0, "best_effort": 1, "manual_check": 2}
            if tier_rank.get(rec["confidence"].value if hasattr(rec["confidence"], "value") else rec["confidence"], 2) < \
               tier_rank.get(merged[h]["confidence"].value if hasattr(merged[h]["confidence"], "value") else merged[h]["confidence"], 2):
                merged[h].update({k: v for k, v in rec.items() if k != "sources"})
        else:
            rec = dict(rec)
            rec["sources"] = [rec["source"]]
            merged[h] = rec

    new_records = []
    for h, rec in merged.items():
        rec["is_new"] = h not in seen
        if rec["is_new"]:
            new_records.append(rec)
        seen[h] = now

    save_seen(seen)
    return new_records, list(merged.values())
