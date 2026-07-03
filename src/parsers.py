"""
parsers.py
==========
Each function takes a raw email (subject + sender + html body) and returns a
list of JobRecord dicts:

    {
        "title": str | None,
        "company": str | None,
        "link": str | None,
        "source": str,          # human-readable source name, from sources.py
        "confidence": Confidence,
        "raw_subject": str,     # kept for debugging/audit
    }

If a parser can't confidently extract a field, it returns None for that
field rather than guessing — downstream code treats missing title/company
as a signal to drop confidence to MANUAL_CHECK regardless of the source's
default tier.
"""

import re
from bs4 import BeautifulSoup
from src.sources import Confidence


def _base_record(source_name, confidence, subject):
    return {
        "title": None,
        "company": None,
        "link": None,
        "source": source_name,
        "confidence": confidence,
        "raw_subject": subject,
    }


def linkedin_subject(source_name, default_confidence, subject, sender, html_body):
    # Pattern A: "search term": Company - Title posted on date
    m = re.match(r'^"(.+?)":\s*(.+?)\s*-\s*(.+?)\s*posted on', subject)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["company"] = m.group(2).strip()
        rec["title"] = m.group(3).strip()
        return [rec]

    # Pattern B: Title at Company: up to $X/year   OR   Title at Company
    m = re.match(r'^(.+?)\s+at\s+(.+?)(?:[:,]|$)', subject)
    if m:
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = m.group(1).strip()
        rec["company"] = m.group(2).strip()
        return [rec]

    # Unrecognized subject shape — don't guess.
    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    return [rec]


def indeed_subject(source_name, default_confidence, subject, sender, html_body):
    # Format A (match.indeed.com): "Title @ Company" or "Title @ Company. N more X jobs in Y"
    m = re.match(r'^(.+?)\s*@\s*(.+?)(?:\.|$)', subject)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["title"] = m.group(1).strip()
        rec["company"] = m.group(2).strip()
        return [rec]

    # Format B (jobalert.indeed.com): "Title at Company. N more X job(s) in Location"
    # e.g. "Social Media Manager, Enterprise Social Operations at Early Warning
    # Services. 1 content operations job in Sterling, VA"
    m = re.match(r'^(.+?)\s+at\s+(.+?)\.\s+\d+', subject)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["title"] = m.group(1).strip()
        rec["company"] = m.group(2).strip()
        return [rec]

    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    return [rec]


def ziprecruiter_subject(source_name, default_confidence, subject, sender, html_body):
    # Pattern A: "$X/yr Title job in City, ST"
    m = re.match(r'^\$[\d,]+/\w+\s+(.+?)\s+job in\s+(.+)$', subject)
    if m:
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)  # location in title, no company
        rec["title"] = m.group(1).strip()
        return [rec]
    # Pattern B: "Company has a Title opening now"
    m = re.match(r'^(.+?)\s+has a\s+(.+?)\s+opening now$', subject)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["company"] = m.group(1).strip()
        rec["title"] = m.group(2).strip()
        return [rec]
    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    return [rec]


def lensa_body(source_name, default_confidence, subject, sender, html_body):
    """Lensa emails list multiple postings in the HTML body. Structure has
    shifted before, so every extraction is capped at BEST_EFFORT."""
    records = []
    if not html_body:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    soup = BeautifulSoup(html_body, "html.parser")
    # Look for anchor tags that look like job links; Lensa job URLs contain '/job/'
    links = [a for a in soup.find_all("a", href=True) if "/job/" in a["href"] or "/l/" in a["href"]]
    for a in links[:20]:  # cap to avoid footer/nav noise
        text = a.get_text(strip=True)
        if not text or len(text) < 4:
            continue
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = text
        rec["link"] = a["href"]
        records.append(rec)
    if not records:
        records = [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    return records


def agency_body(source_name, default_confidence, subject, sender, html_body):
    """Kimble/JJ Alerts/Robert Half: subject often lists 2-3 company names,
    body has links. Extract companies from subject, link from body if present."""
    records = []
    # "Recommended Jobs With X, Y and Z" / "Jobs at X, Y and Z"
    m = re.search(r'(?:with|at)\s+(.+)$', subject, re.IGNORECASE)
    companies = []
    if m:
        companies = [c.strip() for c in re.split(r',| and ', m.group(1)) if c.strip()]
    if not companies:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    for c in companies:
        rec = _base_record(source_name, default_confidence, subject)
        rec["company"] = c
        records.append(rec)
    return records


def flag_only(source_name, default_confidence, subject, sender, html_body):
    """No reliable job-level detail available from the email itself.
    Surfaces as a single 'activity detected' entry. Marked ephemeral so
    dedupe treats each day's occurrence as new rather than permanently
    suppressing it after the first sighting (see dedupe.job_hash)."""
    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    rec["title"] = "(new posting activity — check site directly)"
    rec["company"] = source_name
    rec["ephemeral"] = True
    return [rec]


PARSER_REGISTRY = {
    "linkedin_subject": linkedin_subject,
    "indeed_subject": indeed_subject,
    "ziprecruiter_subject": ziprecruiter_subject,
    "lensa_body": lensa_body,
    "agency_body": agency_body,
    "flag_only": flag_only,
}
