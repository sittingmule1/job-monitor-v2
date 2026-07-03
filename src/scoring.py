"""
scoring.py
==========
Assigns a sort-order score. This does NOT filter anything out — every
record the parsers/fetchers produced still reaches the digest. Scoring only
decides ordering within each confidence tier, so a priority-company hit
surfaces above a generic keyword match even at the same tier.
"""

from src.keywords import PRIORITY_COMPANIES, KEYWORDS, NOISE_TERMS


def score(record):
    text = f"{record.get('title', '')} {record.get('company', '')}".lower()
    s = 0
    if any(c in text for c in PRIORITY_COMPANIES):
        s += 100
    if any(k in text for k in KEYWORDS):
        s += 10
    if any(n in text for n in NOISE_TERMS):
        s -= 20
    if record.get("is_new"):
        s += 5
    return s


def sort_records(records):
    return sorted(records, key=score, reverse=True)
