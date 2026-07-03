"""
keywords.py
===========
Scoring inputs. Kept separate from sources.py so Dan can tune relevance
without touching parsing/fetch logic.
"""

# Companies that should surface at the TOP of the digest regardless of
# whether the title matches a keyword — these are active-pipeline /
# warm-referral targets, not generic keyword matches.
PRIORITY_COMPANIES = [
    "verizon", "wbd", "warner bros", "cnn", "pbs", "nbcu", "nbcuniversal",
    "paramount", "directv", "telestream", "fubo", "a+e", "echostar",
    "comcast", "disney", "netflix", "amazon",
]

# Core role/domain keywords — used to score relevance of title/description text.
KEYWORDS = [
    "content operations", "video operations", "partner operations",
    "content supply chain", "distribution operations", "vod operations",
    "streaming operations", "media operations", "supply chain",
    "digital asset manager", "digital asset management", "asset librarian",
    "business operations manager", "technical program manager",
    "vendor management", "solutions architect media",
]

# Terms that historically produced false positives — used to DOWN-rank,
# not auto-exclude (Dan reviews the digest either way, this just sorts).
NOISE_TERMS = [
    "intern", "internship", "entry level", "hourly", "retail associate",
    "field technician", "asset management",  # bare "asset management" -> finance false positives
]

# Salary floor for scoring purposes only (never hard-filters — floor is
# acknowledged as permeable). Postings below this get a soft down-rank flag,
# not exclusion.
SALARY_FLOOR = 100_000
