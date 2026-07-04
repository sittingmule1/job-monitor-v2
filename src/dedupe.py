"""
dedupe.py
=========
Collapses duplicate postings (same job surfaced via multiple searches/
senders) and maintains a rolling, persistent view of everything seen
recently — not just what arrived in this specific run.

State lives in state/seen_jobs.json, keyed by job hash, storing the full
record plus a last-seen timestamp. Each run:
  1. Loads whatever was persisted from prior runs.
  2. Merges in whatever this run's freshly-pulled emails produced, refreshing
     last-seen for postings still present and adding genuinely new ones.
  3. Drops anything whose last-seen has aged past RETENTION_DAYS.
  4. Persists the result for next time, and returns it for the digest.

This matters because fetch_new_messages() only pulls emails received since
the last run — by design, so old emails aren't reprocessed forever. But that
means a posting whose source email arrived hours or days ago would vanish
from the digest the moment that email ages out of the "new since last run"
window, unless something keeps it alive across runs. Storing only a
hash+timestamp (an earlier version of this file did exactly that) doesn't
provide that — there's no title/company/link left to redisplay once the
originating run is over. Storing the full record is what makes the "stays
visible for a while, not just the day it arrived" behavior actually work.
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


def _tier_rank(confidence):
    val = confidence.value if hasattr(confidence, "value") else confidence
    return {"verified": 0, "best_effort": 1, "manual_check": 2}.get(val, 2)


def dedupe_and_mark(records):
    """Returns (new_records, merged_records). merged_records is the full
    rolling view — this run's postings merged with whatever from prior runs
    hasn't aged out yet — which is what the digest should render. Persists
    the result so the next run has it too."""
    stored = load_seen()  # hash -> {"record": {...}, "last_seen": epoch}
    now = time.time()
    cutoff = now - RETENTION_DAYS * 86400

    # Migration guard: the old format stored hash -> plain timestamp number,
    # with no record data to recover. Those entries can't be turned into
    # displayable postings, so they're dropped rather than crashing on
    # `entry.get(...)` against a bare number. This costs the old "already
    # seen" history (a handful of postings may briefly re-show as NEW once),
    # not any real posting data — nothing usable existed in that old format
    # anyway.
    stored = {h: e for h, e in stored.items() if isinstance(e, dict) and "record" in e}

    # Start from persisted state, dropping anything too old to keep showing.
    merged = {
        h: dict(entry["record"], sources=entry["record"].get("sources", []))
        for h, entry in stored.items()
        if entry.get("last_seen", 0) > cutoff
    }
    is_new = {h: False for h in merged}

    for rec in records:
        h = job_hash(rec)
        if h in merged:
            existing_sources = merged[h].get("sources", [])
            if rec["source"] not in existing_sources:
                existing_sources.append(rec["source"])
            if _tier_rank(rec["confidence"]) < _tier_rank(merged[h]["confidence"]):
                merged[h].update({k: v for k, v in rec.items() if k != "sources"})
            merged[h]["sources"] = existing_sources
        else:
            rec = dict(rec)
            rec["sources"] = [rec["source"]]
            merged[h] = rec
            is_new[h] = h not in stored  # genuinely new, not just refreshed

    new_records = []
    new_stored = {}
    for h, rec in merged.items():
        rec["is_new"] = is_new.get(h, False)
        if rec["is_new"]:
            new_records.append(rec)
        new_stored[h] = {"record": rec, "last_seen": now}

    save_seen(new_stored)
    return new_records, list(merged.values())
