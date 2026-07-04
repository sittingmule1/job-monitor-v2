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

REQUEST_TIMEOUT = 15

# No keyword gate here. Every posting a source returns reaches the digest —
# scoring.py handles relevance ordering (including PRIORITY_COMPANIES and
# KEYWORDS), it does not decide what's visible. See scoring.py docstring:
# "This does NOT filter anything out." Filtering here would silently drop
# real postings whose titles are worded differently than KEYWORDS expects,
# with no error and no manual-check flag — indistinguishable from "no jobs
# today." That happened in practice: PBS and NBCU postings were being
# dropped by a per-posting keyword check even though both are on
# PRIORITY_COMPANIES and were never meant to be filtered at all.


def _workday_location(posting):
    # Workday's cxs jobPostings items commonly expose a "locationsText" field
    # (e.g. "Ashburn, VA" or "Multiple Locations"). Unverified against a live
    # response for these specific tenants — check the next run's digest to
    # confirm this populates rather than coming back empty.
    return posting.get("locationsText") or ""


def _smartrecruiters_location(posting):
    # SmartRecruiters' public postings API returns a "location" object with
    # city/region/country fields (all optional/nullable per their docs).
    loc = posting.get("location") or {}
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    return ", ".join(p for p in parts if p)


def fetch_workday(source, max_results=1000, page_size=50, max_pages=25):
    """
    Workday exposes a JSON search endpoint at:
      https://{host}/wday/cxs/{tenant}/{site}/jobs
    via POST with a search text + pagination body. This is the same
    endpoint the public career-site search box calls in the browser.

    Pull with an empty searchText — which returns the full open-req list —
    paginated across all pages. No client-side keyword filtering: every
    posting the company has open is returned as-is; scoring.py decides
    display order, not this fetcher.
    """
    host = source["host"]
    tenant = source["tenant"]
    site = source["site"]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

    results = []
    raw_total_seen = 0  # every posting seen, before keyword filtering —
                         # used to tell "genuinely 0 matches" apart from
                         # "likely reading the wrong tenant/site entirely"
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
                print(f"    [{source['name']}] Workday returned HTTP {resp.status_code} — "
                      f"likely wrong tenant/site slug, not a real 'no jobs' result")
                break
            data = resp.json()
            postings = data.get("jobPostings", [])
            raw_total_seen += len(postings)
            if not postings:
                break
            for posting in postings:
                title = posting.get("title", "")
                results.append({
                    "title": title,
                    "company": source["name"],
                    "location": _workday_location(posting),
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

    if raw_total_seen == 0:
        print(f"    [{source['name']}] saw 0 total postings — "
              f"this strongly suggests the tenant/site URL is wrong, not that the company has zero openings")
    else:
        print(f"    [{source['name']}] saw {raw_total_seen} total open postings, all included (no keyword filter)")

    return results[:max_results]


def fetch_smartrecruiters(source, max_results=1000, page_size=100, max_pages=10):
    """
    SmartRecruiters has a genuinely public, documented posting API:
      https://api.smartrecruiters.com/v1/companies/{companyId}/postings
    No auth required for public postings.

    Paginated rather than a single request — a company the size of
    NBCUniversal almost certainly has more open postings than fit in one
    page, and only checking page 1 would silently miss real postings further
    down the list. No client-side keyword filtering: every posting returned
    by the API reaches the digest as-is.
    """
    company_id = source["company_id"]
    url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"

    results = []
    raw_total_seen = 0
    try:
        offset = 0
        for _ in range(max_pages):
            resp = requests.get(url, params={"limit": page_size, "offset": offset}, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                print(f"    [{source['name']}] SmartRecruiters returned HTTP {resp.status_code} — "
                      f"likely wrong company ID, not a real 'no jobs' result")
                break
            data = resp.json()
            postings = data.get("content", [])
            raw_total_seen += len(postings)
            if not postings:
                break
            for posting in postings:
                title = posting.get("name", "")
                results.append({
                    "title": title,
                    "company": source["name"],
                    "location": _smartrecruiters_location(posting),
                    "link": posting.get("ref") or posting.get("applyUrl", ""),
                    "source": f"{source['name']} (SmartRecruiters, direct)",
                    "confidence": Confidence.VERIFIED,
                    "raw_subject": title,
                })
            total_found = data.get("totalFound", 0)
            offset += page_size
            if offset >= total_found:
                break

        if raw_total_seen == 0:
            print(f"    [{source['name']}] saw 0 total postings — "
                  f"this strongly suggests the company ID is wrong, not that the company has zero openings")
        else:
            print(f"    [{source['name']}] saw {raw_total_seen} total open postings (all pages), all included (no keyword filter)")
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
            print(f"  [{source['name']}] no fetcher registered for platform '{source['platform']}' — skipped")
            continue
        results = fetcher(source)
        error_count = sum(1 for r in results if r["confidence"] == Confidence.MANUAL_CHECK)
        hit_count = len(results) - error_count
        if error_count and not hit_count:
            print(f"  [{source['name']}] FETCH ERROR — degraded to manual-check flag")
        elif hit_count == 0:
            print(f"  [{source['name']}] fetch succeeded but returned 0 postings — verify this is real, not a silent field-name mismatch")
        else:
            print(f"  [{source['name']}] {hit_count} postings (unfiltered)")
        all_results.extend(results)
    return all_results
