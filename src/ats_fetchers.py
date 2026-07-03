"""
ats_fetchers.py
================
Direct, structured fetches against each company's ATS. These are the
VERIFIED-tier sources — no email round-trip, no subject-line guessing.

IMPORTANT: these endpoints are undocumented/semi-public conventions, not
official APIs with a support contract. They can change without notice.
Every fetch is wrapped so a failure degrades gracefully to a MANUAL_CHECK
flag for that company rather than crashing the whole run.
"""

import requests
from src.sources import Confidence
from src.keywords import KEYWORDS

REQUEST_TIMEOUT = 15


def _keyword_hit(text):
    text = (text or "").lower()
    return any(k in text for k in KEYWORDS)


def fetch_workday(source, max_results=50, page_size=20, max_pages=10):
    """
    Workday exposes a JSON search endpoint at:
      https://{host}/wday/cxs/{tenant}/{site}/jobs
    via POST with a search text + pagination body. This is the same
    endpoint the public career-site search box calls in the browser.

    Rather than issuing one request per keyword (14 keywords x N Workday
    companies = a lot of chatty, redundant requests for the same posting
    set), pull with an empty searchText — which returns the full open-req
    list — paginated, and filter client-side against KEYWORDS. One posting
    list per company instead of one per keyword.
    """
    host = source["host"]
    tenant = source["tenant"]
    site = source["site"]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

    results = []
    try:
        offset = 0
        for _ in range(max_pages):
            payload = {
                "appliedFacets": {},
                "limit": page_size,
                "offset": offset,
                "searchText": "",
            }
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                break
            data = resp.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break
            for posting in postings:
                title = posting.get("title", "")
                if not _keyword_hit(title):
                    continue
                results.append({
                    "title": title,
                    "company": source["name"],
                    "link": f"https://{host}/{tenant}/{site}{posting.get('externalPath', '')}",
                    "source": f"{source['name']} (Workday, direct)",
                    "confidence": Confidence.VERIFIED,
                    "raw_subject": title,
                })
            total = data.get("total", 0)
            offset += page_size
            if offset >= total:
                break
    except Exception as e:
        # Degrade to a single manual-check flag rather than failing the run.
        return [{
            "title": f"(fetch failed — check {source['name']} careers site directly: {e})",
            "company": source["name"],
            "link": f"https://{host}",
            "source": f"{source['name']} (Workday, fetch error)",
            "confidence": Confidence.MANUAL_CHECK,
            "raw_subject": "",
        }]
    return results[:max_results]


def fetch_smartrecruiters(source, max_results=50):
    """
    SmartRecruiters has a genuinely public, documented posting API:
      https://api.smartrecruiters.com/v1/companies/{companyId}/postings
    No auth required for public postings.
    """
    company_id = source["company_id"]
    url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"

    results = []
    try:
        resp = requests.get(url, params={"limit": 100}, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise ValueError(f"status {resp.status_code}")
        data = resp.json()
        for posting in data.get("content", []):
            title = posting.get("name", "")
            if not _keyword_hit(title):
                continue
            results.append({
                "title": title,
                "company": source["name"],
                "link": posting.get("ref") or posting.get("applyUrl", ""),
                "source": f"{source['name']} (SmartRecruiters, direct)",
                "confidence": Confidence.VERIFIED,
                "raw_subject": title,
            })
    except Exception as e:
        return [{
            "title": f"(fetch failed — check {source['name']} careers site directly: {e})",
            "company": source["name"],
            "link": "",
            "source": f"{source['name']} (SmartRecruiters, fetch error)",
            "confidence": Confidence.MANUAL_CHECK,
            "raw_subject": "",
        }]
    return results[:max_results]


FETCHER_REGISTRY = {
    "workday": fetch_workday,
    "smartrecruiters": fetch_smartrecruiters,
}


def run_all_ats_fetchers(ats_sources):
    all_results = []
    for source in ats_sources:
        fetcher = FETCHER_REGISTRY.get(source["platform"])
        if not fetcher:
            continue
        all_results.extend(fetcher(source))
    return all_results
