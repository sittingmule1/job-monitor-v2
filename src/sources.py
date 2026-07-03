"""
sources.py
==========
Single source of truth for every place a job posting can come from.

Each entry defines:
  - how to recognize it (sender pattern for email sources, or a fetch config for ATS sources)
  - which parser/fetcher handles it
  - its CONFIDENCE TIER, which flows straight through to the digest.

Confidence tiers (do not skip this when adding a new source):
  VERIFIED     -> structured data, title/company/link reliably extracted
  BEST_EFFORT  -> parsed, but format is inconsistent or fragile; spot-check
  MANUAL_CHECK -> monitor can only say "something happened here", not what

Adding a new sender? Default to MANUAL_CHECK until its actual output has been
verified end-to-end at least once. It's easy to relax a tier later; it's a
trust problem to over-promise one now.
"""

from enum import Enum


class Confidence(str, Enum):
    VERIFIED = "verified"
    BEST_EFFORT = "best_effort"
    MANUAL_CHECK = "manual_check"


# ---------------------------------------------------------------------------
# EMAIL SOURCES — pulled from the Gmail "Job Alerts" label, routed by sender
# ---------------------------------------------------------------------------
EMAIL_SOURCES = [
    {
        "name": "LinkedIn Job Alerts",
        "match": ["jobalerts-noreply@linkedin.com"],
        "parser": "linkedin_subject",
        "confidence": Confidence.VERIFIED,
        "notes": "Subject line carries search term + company + title reliably.",
    },
    {
        "name": "LinkedIn Job Recommendations",
        "match": ["jobs-noreply@linkedin.com"],
        "parser": "linkedin_subject",
        "confidence": Confidence.BEST_EFFORT,
        "notes": "Algorithmic feed, not a named saved search — lower relevance signal.",
    },
    {
        "name": "Indeed",
        "match": ["indeed.com"],
        "parser": "indeed_subject",
        "confidence": Confidence.VERIFIED,
        "notes": "Subject = 'Title @ Company'. Cannot map back to which saved search triggered it.",
    },
    {
        "name": "ZipRecruiter",
        "match": ["ziprecruiter.com"],
        "parser": "ziprecruiter_subject",
        "confidence": Confidence.VERIFIED,
        "notes": "Subject usually carries title/company/pay; some geo/salary mismatches seen historically.",
    },
    {
        "name": "Lensa",
        "match": ["lensa.com"],
        "parser": "lensa_body",
        "confidence": Confidence.BEST_EFFORT,
        "notes": "Multiple postings per email, listed in HTML body. Format has shifted before.",
    },
    {
        "name": "Kimble Group",
        "match": ["kimblegroup.com"],
        "parser": "agency_body",
        "confidence": Confidence.BEST_EFFORT,
        "notes": "Staffing agency; body lists 2-3 companies, no direct links guaranteed.",
    },
    {
        "name": "JJ Alerts (Johnson Jobs)",
        "match": ["johnsonjobs.com"],
        "parser": "agency_body",
        "confidence": Confidence.BEST_EFFORT,
        "notes": "Same pattern as Kimble Group.",
    },
    {
        "name": "Robert Half",
        "match": ["roberthalf.com"],
        "parser": "agency_body",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Broad, unfiltered agency feed — flagged as activity only until parser is verified.",
    },
    {
        "name": "Paramount Careers",
        "match": ["noreply.jobs2web.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "'New jobs posted' notification, no job-level detail in email body.",
    },
    {
        "name": "Marriott Careers",
        "match": ["marriotthiring.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Same generic notification pattern as Paramount.",
    },
    {
        "name": "Amdocs",
        "match": ["amdocs.com", "eightfold.ai"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Weekly digest email; format not yet verified against a live sample.",
    },
    {
        "name": "Amazon",
        "match": ["amazon.jobs", "amazon.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "No public API, custom in-house ATS. Also: Amazon RTO policy means remote is rare.",
    },
    {
        "name": "NBCUniversal (email)",
        "match": ["nbcunicareers.com", "nbcuniversal.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Email notification only — the reliable path for NBCU is the SmartRecruiters API fetch below, not this email.",
    },
    {
        "name": "Verizon (email)",
        "match": ["verizon.com", "mycareer.verizon.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Email notification only — the reliable path for Verizon is the Workday API fetch below, not this email.",
    },
    {
        "name": "Fubo",
        "match": ["fubo.tv", "fubotv.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Unverified whether the 5-term search string parsed as OR or AND on their site.",
    },
    {
        "name": "EchoStar (email)",
        "match": ["echostar.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Email notification only — reliable path is the Workday API fetch below.",
    },
    {
        "name": "Google Careers",
        "match": ["careers-noreply@google.com"],
        "parser": "flag_only",
        "confidence": Confidence.MANUAL_CHECK,
        "notes": "Format not yet verified against a live parsed sample.",
    },
]


# ---------------------------------------------------------------------------
# ATS SOURCES — fetched directly, independent of email, on every run
# ---------------------------------------------------------------------------
ATS_SOURCES = [
    {
        "name": "Verizon",
        "platform": "workday",
        "tenant": "verizon",
        "site": "verizon-careers",
        "host": "verizon.wd12.myworkdayjobs.com",
        "confidence": Confidence.VERIFIED,
    },
    {
        "name": "PBS",
        "platform": "workday",
        "tenant": "vhr-pbs",
        "site": "PBSCareers",
        "host": "vhr-pbs.wd5.myworkdayjobs.com",
        "confidence": Confidence.VERIFIED,
    },
    {
        "name": "EchoStar",
        "platform": "workday",
        "tenant": "echostar",
        "site": "echostar",
        "host": "echostar.wd5.myworkdayjobs.com",
        "confidence": Confidence.VERIFIED,
    },
    {
        "name": "NBCUniversal",
        "platform": "smartrecruiters",
        "company_id": "NBCUniversal3",
        "confidence": Confidence.VERIFIED,
    },
    # Paramount / Amdocs / Marriott intentionally omitted from automated fetch
    # for now — SuccessFactors / Eightfold / Oracle Cloud endpoints need to be
    # reverse-engineered per-tenant before they can be trusted. They stay
    # MANUAL_CHECK via the email flag_only path until that happens.
]
