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

# Links that are never the actual job posting — footer/settings/legal
# boilerplate present in nearly every marketing-style email. Filtered out
# before picking "the" link, regardless of source.
_NON_JOB_LINK_PATTERNS = [
    "unsubscribe", "/preferences", "/settings", "privacy", "view-in-browser",
    "mailto:", "helpcenter", "support.", "/optout", "manage-notification",
    "manage-alert", "email-settings",
    # LinkedIn's own header "you have notifications" badge link — confirmed
    # by a real user report that this was being picked as the job link,
    # landing on the generic feed instead of any specific posting.
    "linkedin.com/comm/feed", "linkedin.com/feed", "home_glimmer_static_badging",
]


def _first_job_link(html_body, must_contain=None):
    """Returns the first link in the body that looks like an actual job
    posting rather than footer/settings noise. If must_contain is given,
    only considers links whose domain matches one of those hints (e.g. the
    sender's own domain) — otherwise takes the first non-boilerplate link
    found, in document order.

    This is a best-effort heuristic, not a verified pattern per source —
    unlike Lensa (confirmed against a real email) or Workday/SmartRecruiters
    (confirmed against real API responses), this hasn't been checked against
    a real sample from every sender it's applied to. Treat any link it
    produces as worth spot-checking until proven against real mail."""
    if not html_body:
        return None
    soup = BeautifulSoup(html_body, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        low = href.lower()
        if any(p in low for p in _NON_JOB_LINK_PATTERNS):
            continue
        if must_contain and not any(m in low for m in must_contain):
            continue
        return href
    return None


def _base_record(source_name, confidence, subject):
    return {
        "title": None,
        "company": None,
        "location": None,
        "link": None,
        "source": source_name,
        "confidence": confidence,
        "raw_subject": subject,
    }


def _linkedin_body_location(html_body, company):
    """Best-effort: the subject line never carries location — it's always in
    the body, specific to that one job. Reuses the 'Company · Location'
    middle-dot line pattern already confirmed for LinkedIn's digest-body
    format (see _parse_linkedin_digest_body), on the assumption LinkedIn
    renders job cards the same way across its email types. That specific
    reuse hasn't been checked against a real Pattern A/B sample yet, so
    treat any location this returns as worth a spot-check, not a guarantee.
    Matches loosely (company name as a substring) since the body's company
    text may include a suffix (e.g. "Netflix, Inc.") the subject doesn't."""
    if not html_body or not company:
        return None
    soup = BeautifulSoup(html_body, "html.parser")
    text = soup.get_text(separator="\n")
    company_lower = company.strip().lower()
    for line in text.split("\n"):
        line = line.strip()
        m = re.match(r'^(.+?)\s*\u00b7\s*(.+)$', line)
        if m and company_lower in m.group(1).strip().lower():
            return m.group(2).strip()
    return None


def linkedin_subject(source_name, default_confidence, subject, sender, html_body):
    # Link extraction: requires a job-specific path ("/jobs/"), not just the
    # linkedin.com domain. A real user report caught this failing — the
    # bare domain match was grabbing LinkedIn's own header notification-badge
    # link (which sits first in the email, before any job link) and sending
    # people to their generic feed instead of the actual posting. That badge
    # link is also now in _NON_JOB_LINK_PATTERNS as a second layer of defense.
    #
    # LinkedIn's "your job alert has been created" confirmation email is NOT
    # empty — it bundles an initial batch of matching postings directly in
    # the body (confirmed against a real example: 6 real Verizon postings
    # were inside one of these). An earlier version of this code wrongly
    # assumed "has been created" meant no job content and silently dropped
    # the whole email — that was a real mistake that would have discarded
    # genuine postings. Route it to the digest-style body parser instead.
    if re.match(r'^.+?:\s*your job alert for .+ has been created', subject, re.IGNORECASE):
        return _parse_linkedin_digest_body(source_name, subject, html_body)

    # Real LinkedIn alert emails use curly/smart quotes ("..."), not straight
    # ASCII quotes ("..."). The original regex only matched straight quotes,
    # which silently sent every quoted-search-term alert — the exact format
    # meant to be VERIFIED-tier — to the unparsed fallback instead. Normalize
    # before matching rather than trying to maintain two character classes.
    normalized = subject.replace("\u201c", '"').replace("\u201d", '"')

    # Pattern A: "search term": Company - Title posted on date
    m = re.match(r'^"(.+?)":\s*(.+?)\s*-\s*(.+?)\s*posted on', normalized)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["company"] = m.group(2).strip()
        rec["title"] = m.group(3).strip()
        rec["location"] = _linkedin_body_location(html_body, rec["company"])
        rec["link"] = _first_job_link(html_body, must_contain=["linkedin.com/comm/jobs", "linkedin.com/jobs"])
        return [rec]

    # Pattern B: Title at Company: up to $X/year   OR   Title at Company
    m = re.match(r'^(.+?)\s+at\s+(.+?)(?:[:,]|$)', normalized)
    if m:
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = m.group(1).strip()
        rec["company"] = m.group(2).strip()
        rec["location"] = _linkedin_body_location(html_body, rec["company"])
        rec["link"] = _first_job_link(html_body, must_contain=["linkedin.com/comm/jobs", "linkedin.com/jobs"])
        return [rec]

    # Pattern C: "search term" and similar jobs — LinkedIn's algorithmic
    # recommendation format for a batched/company-name saved search. No
    # title/company to extract, but the search term itself is useful signal
    # (tells you which of your searches triggered it), so surface it as the
    # company field rather than leaving everything blank.
    m = re.match(r'^"(.+?)"\s+and similar jobs', normalized)
    if m:
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["company"] = f'(matched search: "{m.group(1).strip()}")'
        rec["link"] = _first_job_link(html_body, must_contain=["linkedin.com/comm/jobs", "linkedin.com/jobs"])
        return [rec]

    # Unrecognized subject shape — don't guess.
    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    return [rec]


def _parse_linkedin_digest_body(source_name, subject, html_body):
    """Extracts bundled postings from a LinkedIn 'alert created' email.
    Confirmed real structure (from an actual example): each posting renders
    as a repeating text block —
        Verizon
        Contract Manager, Federal – Senior Manager
        Verizon · Annapolis Junction, Maryland, United States
        [optional connections/alumni line]
    Rather than guess at LinkedIn's underlying HTML/link structure (which
    has been wrong twice already this session for other sources), this
    anchors on the distinctive "Company · Location" line — the middle-dot
    separator is unlikely to appear elsewhere in the email — and takes the
    line immediately before it as the job title. Capped at BEST_EFFORT since
    it's built from one confirmed example, not a documented format.

    Link extraction: tries each <a> tag's own text first, on the assumption
    each posting card is individually wrapped in a link (confirmed pattern
    for Lensa; unconfirmed but plausible for LinkedIn). Falls back to the
    old whole-page text scan — without a link — only if no anchor contains
    a recognizable posting block, so a wrong assumption about the HTML
    structure degrades to "no link" rather than to "no posting at all"."""
    if not html_body:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    soup = BeautifulSoup(html_body, "html.parser")

    records = []
    for a in soup.find_all("a", href=True):
        lines = [l.strip() for l in a.get_text(separator="\n").split("\n") if l.strip()]
        for i, line in enumerate(lines):
            m = re.match(r'^(.+?)\s*\u00b7\s*(.+)$', line)
            if m and i > 0:
                rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
                rec["company"] = m.group(1).strip()
                rec["location"] = m.group(2).strip()
                rec["title"] = lines[i - 1].strip()
                rec["link"] = a["href"]
                records.append(rec)
                break
    if records:
        return records

    # Second pass: a different LinkedIn layout (title/company/location on
    # separate lines, "View job" link) — confirmed as a real, distinct
    # format from the one just tried above.
    records = _parse_linkedin_search_results_body(source_name, subject, html_body)
    if records:
        return records

    # Fallback: postings aren't individually wrapped in anchors after all —
    # extract title/company from the page text with no link rather than
    # losing the postings entirely.
    lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]
    for i, line in enumerate(lines):
        m = re.match(r'^(.+?)\s*\u00b7\s*(.+)$', line)
        if m and i > 0:
            rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
            rec["company"] = m.group(1).strip()
            rec["location"] = m.group(2).strip()
            rec["title"] = lines[i - 1].strip()
            records.append(rec)
    if not records:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    return records


def _parse_linkedin_search_results_body(source_name, subject, html_body):
    """Handles a SECOND LinkedIn bundled-postings layout, confirmed against
    a real example — different from the 'Company · Location' single-line
    format handled above. This one lays out each posting as:
        Title
        Company
        Location
        [optional: "1 connection" / "24 school alumni" / "This company is
         actively hiring" — not always present]
        View job: <link>
        ----------
    Rather than assume every LinkedIn digest uses the same layout (which
    turned out false), this is tried as a second pass when the Company ·
    Location pattern finds nothing, using the "View job" link position as
    an anchor and walking backward to collect the title/company/location
    lines, skipping the optional insight line if present."""
    if not html_body:
        return None
    soup = BeautifulSoup(html_body, "html.parser")
    lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]
    job_anchors = [
        a for a in soup.find_all("a", href=True)
        if "linkedin.com" in a["href"].lower() and "/jobs/view/" in a["href"].lower()
    ]
    if not job_anchors:
        return None

    insight_pattern = re.compile(
        r'^\d+\s+(connection|connections|school alumni)$|^this company is actively hiring$',
        re.IGNORECASE,
    )
    view_job_indices = [i for i, l in enumerate(lines) if l.lower().startswith("view job")]
    if len(view_job_indices) != len(job_anchors):
        return None  # counts don't line up — don't guess at pairing them

    records = []
    for idx, a in zip(view_job_indices, job_anchors):
        collected = []
        j = idx - 1
        while j >= 0 and len(collected) < 3:
            line = lines[j]
            if line.lower().startswith("view job") or line.strip("- ") == "":
                break
            if insight_pattern.match(line):
                j -= 1
                continue
            collected.append(line)
            j -= 1
        collected.reverse()
        if len(collected) < 2:
            continue  # not enough context to trust a guess
        if len(collected) >= 3:
            title, company, location = collected[0], collected[1], collected[2]
        else:
            title, company, location = None, collected[0], None
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = title
        rec["company"] = company
        rec["location"] = location
        rec["link"] = a["href"]
        records.append(rec)
    return records if records else None
    # Format A (match.indeed.com): "Title @ Company" or "Title @ Company. N more X jobs in Y"
def indeed_subject(source_name, default_confidence, subject, sender, html_body):
    # Format A (match.indeed.com): "Title @ Company" or "Title @ Company. N more X jobs in Y"
    m = re.match(r'^(.+?)\s*@\s*(.+?)(?:\.|$)', subject)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["title"] = m.group(1).strip()
        rec["company"] = m.group(2).strip()
        # Must match Indeed's specific job-link pattern (/rc/clk, carrying a
        # jk= job-key parameter), not just any indeed.com link — confirmed
        # against a real email that Indeed's own logo/homepage link also
        # contains "indeed.com" and appears BEFORE the real job link, so a
        # generic domain match would have grabbed the wrong URL.
        rec["link"] = _first_job_link(html_body, must_contain=["/rc/clk"])
        return [rec]

    # Format B (jobalert.indeed.com): "Title at Company. N more X job(s) in Location"
    # e.g. "Social Media Manager, Enterprise Social Operations at Early Warning
    # Services. 1 content operations job in Sterling, VA"
    m = re.match(r'^(.+?)\s+at\s+(.+?)\.\s+\d+', subject)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["title"] = m.group(1).strip()
        rec["company"] = m.group(2).strip()
        # Location, when present, trails as "... N more X job(s) in Location" —
        # searched separately (not required for the match above) since not
        # every real subject of this shape necessarily ends with it.
        loc_m = re.search(r'\bjobs?\s+in\s+(.+)$', subject, re.IGNORECASE)
        if loc_m:
            rec["location"] = loc_m.group(1).strip()
        rec["link"] = _first_job_link(html_body, must_contain=["/rc/clk"])
        return [rec]

    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    return [rec]


def ziprecruiter_digest_body(source_name, subject, html_body):
    """ZipRecruiter emails are NOT single-job alerts — confirmed against a
    real example, the subject named only 1 featured job ('Sports Data
    Reporter') while the body contained roughly 24 separate postings. The
    old subject-only extraction was silently dropping the other ~23 every
    single time. Real structure: a job-title <a> (recognizable by its
    ziprecruiter.com/km/ or /ekm/ URL) is a SIBLING of a <p>Company • Location</p>
    element, not a parent — so unlike Lensa/LinkedIn, checking the anchor's
    own text doesn't work here. Instead: get the full page text as a list of
    lines, locate each title's line by exact match, then scan a few lines
    forward for the "Company • Location" pattern that follows it."""
    if not html_body:
        return None
    soup = BeautifulSoup(html_body, "html.parser")
    lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]
    title_links = [
        a for a in soup.find_all("a", href=True)
        if ("ziprecruiter.com/km/" in a["href"] or "ziprecruiter.com/ekm/" in a["href"])
    ]
    # "Apply Now" / "View Details" are button links reusing the same href
    # as the title link for that job — skip those. Also seen in a live run:
    # footer/nav boilerplate ("View More Jobs", "Privacy Policy",
    # "Unsubscribe") apparently sits on the same ziprecruiter.com/km/ or
    # /ekm/ URL pattern as real job links, which let three fake postings
    # through with garbage companies ("Phil", "|", blank). Excluded by text
    # match rather than URL, since the URL pattern alone can't tell them
    # apart from a real posting.
    _NON_JOB_LINK_TEXT = (
        "apply now", "view details", "view more jobs", "privacy policy",
        "unsubscribe", "terms of service", "terms of use", "help center",
    )
    seen_hrefs = set()
    records = []
    for a in title_links:
        text = a.get_text(strip=True)
        href = a["href"]
        if not text or text.lower() in _NON_JOB_LINK_TEXT or text == "|" or href in seen_hrefs:
            continue
        try:
            idx = lines.index(text)
        except ValueError:
            continue  # title text didn't match a line exactly (e.g. truncated with "...") — skip rather than guess
        company = None
        location = None
        for j in range(idx + 1, min(idx + 4, len(lines))):
            m = re.match(r'^(.+?)\s*\u2022\s*(.+)$', lines[j])
            if m:
                company = m.group(1).strip()
                location = m.group(2).strip()
                break
        if company is None and idx + 1 < len(lines):
            # No "Company • Location" bullet pattern found nearby — confirmed
            # against a real example (Thermo Fisher Scientific) that some
            # listings show a bare company name with no location at all.
            # Use the very next line as a best-effort company name rather
            # than leaving it blank.
            company = lines[idx + 1].strip()
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = text
        rec["company"] = company
        rec["location"] = location
        rec["link"] = href
        records.append(rec)
        seen_hrefs.add(href)
    return records if records else None


def ziprecruiter_subject(source_name, default_confidence, subject, sender, html_body):
    # Try the full digest body first — real emails carry far more postings
    # in the body than the single job named in the subject (see docstring
    # on ziprecruiter_digest_body). Only fall back to subject-only parsing
    # if the body extraction genuinely finds nothing.
    digest_records = ziprecruiter_digest_body(source_name, subject, html_body)
    if digest_records:
        return digest_records

    # Pattern A: "$X/yr Title job in City, ST"
    m = re.match(r'^\$[\d,]+/\w+\s+(.+?)\s+job in\s+(.+)$', subject)
    if m:
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)  # location in title, no company
        rec["title"] = m.group(1).strip()
        rec["location"] = m.group(2).strip()
        rec["link"] = _first_job_link(html_body, must_contain=["ziprecruiter.com"])
        return [rec]
    # Pattern B: "Company has a Title opening now"
    m = re.match(r'^(.+?)\s+has a\s+(.+?)\s+opening now$', subject)
    if m:
        rec = _base_record(source_name, default_confidence, subject)
        rec["company"] = m.group(1).strip()
        rec["title"] = m.group(2).strip()
        rec["link"] = _first_job_link(html_body, must_contain=["ziprecruiter.com"])
        return [rec]
    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    return [rec]


def lensa_body(source_name, default_confidence, subject, sender, html_body):
    """Lensa emails list multiple postings in the HTML body, each wrapped as
    one large clickable block: company name, then job title, then salary
    and a list of benefit badges (e.g. "401K Plan", "Health Insurance"),
    all as text inside a single <a> tag whose href points through Lensa's
    own click-tracking redirect (sg3email.lensa.com/ls/click?...) rather
    than a direct job URL. An earlier assumption that the final line was
    location was tested against a live run and disproven — it's reliably
    a benefit badge, not a place — so location isn't extracted here at all
    until a raw sample clarifies whether/where it actually appears.

    Confirmed against a real Lensa email — the original assumption (looking
    for '/job/' or '/l/' in the link) was wrong and matched nothing, which
    is why every Lensa posting was previously falling through to manual-check
    with no title extracted. Still capped at BEST_EFFORT since the block
    structure (company on line 1, title on line 2) is inferred from one
    sample, not guaranteed across every template Lensa might use."""
    records = []
    if not html_body:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    soup = BeautifulSoup(html_body, "html.parser")
    links = [a for a in soup.find_all("a", href=True) if "lensa.com" in a["href"] and "click" in a["href"]]
    # No hard cap on count — confirmed against a real email with 22 postings
    # that an earlier [:20] slice silently dropped 2-3 real jobs before the
    # 2-line structural filter even got a chance to reject the non-job links
    # (nav/footer links are single-line and get filtered out below anyway,
    # so a cap here was doing nothing except cutting off legitimate postings).
    for a in links:
        lines = [line.strip() for line in a.get_text(separator="\n").split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        # Real emails use U+2024 (one dot leader) as a trailing decorative
        # mark on some company names, not U+2022 (bullet) as first assumed —
        # confirmed by decoding a real sample. Strip both to be safe.
        rec["company"] = lines[0].rstrip("\u2022\u2024").strip()
        rec["title"] = lines[1]
        # Location extraction was tried here (taking the last line, on the
        # theory it's reliably location whether or not salary is present)
        # and a live run proved it wrong: the last line is consistently a
        # benefit/perk badge instead — "401K Plan", "Health Insurance",
        # "Remote", "Full-Time", etc., not a place. A confidently wrong
        # location is worse than an honest blank, so this isn't attempted
        # until a real raw Lensa email can be inspected to find where
        # location actually sits in the card (if it's even present at all —
        # it may simply not be, for cards that show a benefits list instead).
        rec["link"] = a["href"]
        records.append(rec)
    if not records:
        records = [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    return records


def agency_body(source_name, default_confidence, subject, sender, html_body):
    """Kimble/JJ Alerts/Robert Half: the subject only names 2-3 companies,
    but confirmed against a real JJ Alerts email, the body actually contains
    far more individual postings (10, in the confirmed sample) organized
    under section headers like 'New Opportunities in Your Area'. Each
    posting is a distinct job title with its own link — extracting all of
    them instead of just the handful named in the subject.

    Real format has no separator character between company and location
    (e.g. 'Fox Television Stations Phoenix, AZ' — company and city just run
    together with a space). Splitting them apart would require guessing
    where one ends and the other begins, which risks mislabeling a city as
    part of the company name or vice versa — so they're kept combined in
    the company field rather than presented with false confidence in a
    clean split.

    Job links are identified by matching the sender's own domain, since
    that pattern was confirmed for JJ Alerts (johnsonjobs.com) but hasn't
    been verified against a real Kimble Group email yet — for any sender
    where this finds no matching links, falls back to the original
    subject-only company-list extraction rather than returning nothing."""
    domain = ""
    if sender and "@" in sender:
        domain = sender.split("@")[-1].strip("> ").lower()

    if html_body and domain:
        soup = BeautifulSoup(html_body, "html.parser")
        lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]
        job_links = [
            a for a in soup.find_all("a", href=True)
            if domain in a["href"].lower() and "/job" in a["href"].lower()
            and not any(p in a["href"].lower() for p in _NON_JOB_LINK_PATTERNS)
            and "post-a-job" not in a["href"].lower() and "/job2/" not in a["href"].lower()
        ]
        seen_hrefs = set()
        records = []
        for a in job_links:
            text = a.get_text(strip=True)
            href = a["href"]
            if not text or href in seen_hrefs:
                continue
            try:
                idx = lines.index(text)
            except ValueError:
                continue
            company_and_location = lines[idx + 1] if idx + 1 < len(lines) else None
            company = company_and_location
            if company_and_location:
                # Kimble Group uses a clean " - " separator between company
                # and location (confirmed real example); JJ Alerts has no
                # separator at all and the two run together. Split when the
                # separator is present, keep combined otherwise rather than
                # guessing where a company name ends without one.
                m2 = re.match(r'^(.+?)\s+-\s+(.+)$', company_and_location)
                if m2:
                    company = m2.group(1).strip()
            rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
            rec["title"] = text
            rec["company"] = company
            rec["link"] = href
            records.append(rec)
            seen_hrefs.add(href)
        if records:
            return records

    # Fallback: body extraction found nothing (unverified sender format, or
    # no html body available) — extract the few companies named in the
    # subject line as before. "Recommended Jobs With X, Y and Z" / "Jobs at X, Y and Z"
    m = re.search(r'(?:with|at)\s+(.+)$', subject, re.IGNORECASE)
    companies = []
    if m:
        companies = [c.strip() for c in re.split(r',| and ', m.group(1)) if c.strip()]
    if not companies:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]

    links = []
    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not any(p in href.lower() for p in _NON_JOB_LINK_PATTERNS):
                links.append(href)

    records = []
    for idx, c in enumerate(companies):
        rec = _base_record(source_name, default_confidence, subject)
        rec["company"] = c
        rec["title"] = "(agency digest — no job title in email, click through to see roles)"
        rec["link"] = links[idx] if idx < len(links) else None
        records.append(rec)
    return records


def paramount_body(source_name, default_confidence, subject, sender, html_body):
    """Paramount's 'New jobs posted' email is NOT a single-item flag — confirmed
    against two real examples, it lists 9-10 individual job links in a flat,
    simple structure: <a class="agentjoblink" href="...">Title - City, ST, US, ZIP</a>
    Splits title from location on the last ' - ' since city names can contain
    hyphens too (job titles rarely do, but title text also sometimes has an
    em-dash rather than plain hyphen, so this is a best-effort split)."""
    if not html_body:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    soup = BeautifulSoup(html_body, "html.parser")
    job_links = soup.find_all("a", class_="agentjoblink")
    records = []
    for a in job_links:
        text = a.get_text(strip=True)
        href = a.get("href", "")
        # Split off the trailing location if present: "Title - City, ST, US, ZIP"
        parts = text.rsplit(" - ", 1)
        title = parts[0].strip()
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = title
        rec["company"] = source_name
        rec["location"] = parts[1].strip() if len(parts) > 1 else None
        rec["link"] = href
        records.append(rec)
    if not records:
        # Structure didn't match what we've confirmed before — flag rather
        # than silently report zero jobs from an email that likely has some.
        rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
        rec["title"] = "(new posting activity — check site directly, expected job links not found)"
        rec["company"] = source_name
        rec["link"] = _first_job_link(html_body)
        rec["ephemeral"] = True
        return [rec]
    return records


def marriott_body(source_name, default_confidence, subject, sender, html_body):
    """Marriott's 'Job Opportunities' email lists a small number of individual
    job links (confirmed: 3 in a real sample), each a plain <a> with the job
    title as the link text and no separate location text — just title + link.
    Distinguished from the 'Manage Your Profile' / social-media footer links
    by requiring the href to contain the Oracle Cloud job-posting path."""
    if not html_body:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    soup = BeautifulSoup(html_body, "html.parser")
    job_links = [a for a in soup.find_all("a", href=True) if "/CandidateExperience/" in a["href"] and "/job/" in a["href"]]
    records = []
    for a in job_links:
        title = a.get_text(strip=True)
        if not title:
            continue
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = title
        rec["company"] = source_name
        rec["link"] = a["href"]
        records.append(rec)
    if not records:
        rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
        rec["title"] = "(new posting activity — check site directly, expected job links not found)"
        rec["company"] = source_name
        rec["link"] = _first_job_link(html_body)
        rec["ephemeral"] = True
        return [rec]
    return records
    """No reliable job-level detail available from the email itself.
    Surfaces as a single 'activity detected' entry. Marked ephemeral so
    dedupe treats each day's occurrence as new rather than permanently
    suppressing it after the first sighting (see dedupe.job_hash).

    These 'new jobs posted' notifications almost always contain a single
    prominent link (a 'View Jobs' button) pointing at the company's career
    page — grabbing the first non-boilerplate link gets you at least that,
    even without a specific job title."""
    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    rec["title"] = "(new posting activity — check site directly)"
    rec["company"] = source_name
    rec["link"] = _first_job_link(html_body)
    rec["ephemeral"] = True
    return [rec]


def flag_only(source_name, default_confidence, subject, sender, html_body):
    """No reliable job-level detail available from the email itself.
    Surfaces as a single 'activity detected' entry. Marked ephemeral so
    dedupe treats each day's occurrence as new rather than permanently
    suppressing it after the first sighting (see dedupe.job_hash).

    These 'new jobs posted' notifications almost always contain a single
    prominent link (a 'View Jobs' button) pointing at the company's career
    page — grabbing the first non-boilerplate link gets you at least that,
    even without a specific job title."""
    rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
    rec["title"] = "(new posting activity — check site directly)"
    rec["company"] = source_name
    rec["link"] = _first_job_link(html_body)
    rec["ephemeral"] = True
    return [rec]


def wbd_body(source_name, default_confidence, subject, sender, html_body):
    """Warner Bros. Discovery's 'Jobs for you' Talent Community email lists
    individual job postings (confirmed against a real example: 5 postings,
    each with title + location, no separate company name needed since the
    whole email is company-specific). Title links and the 'Apply Now'
    button both use the same sendgrid.net click-tracking domain with
    different per-link tracking suffixes — only the title link (identified
    by having real, non-boilerplate text) is kept; the Apply Now duplicate
    and footer links (wbd.com, unsubscribe, social icons) are filtered out."""
    if not html_body:
        return [_base_record(source_name, Confidence.MANUAL_CHECK, subject)]
    soup = BeautifulSoup(html_body, "html.parser")
    lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]
    candidate_links = [a for a in soup.find_all("a", href=True) if "sendgrid.net/ls/click" in a["href"]]
    seen_hrefs = set()
    records = []
    skip_texts = {"apply now", "unsubscribe", "wbd.com", "wbd.com/careers"}
    for a in candidate_links:
        text = a.get_text(strip=True)
        href = a["href"]
        if not text or text.lower() in skip_texts or href in seen_hrefs:
            continue
        try:
            idx = lines.index(text)
        except ValueError:
            continue
        rec = _base_record(source_name, Confidence.BEST_EFFORT, subject)
        rec["title"] = text
        rec["company"] = source_name
        # TODO: docstring above says a real confirmed sample had "title +
        # location" per posting, but location's actual position relative to
        # the title line was never captured in this parser. Needs a fresh
        # real WBD email to confirm the structure before guessing at it —
        # left blank rather than assuming a line offset that might be wrong.
        rec["link"] = href
        records.append(rec)
        seen_hrefs.add(href)
    if not records:
        rec = _base_record(source_name, Confidence.MANUAL_CHECK, subject)
        rec["title"] = "(new posting activity — check site directly, expected job links not found)"
        rec["company"] = source_name
        rec["link"] = _first_job_link(html_body)
        rec["ephemeral"] = True
        return [rec]
    return records


PARSER_REGISTRY = {
    "linkedin_subject": linkedin_subject,
    "indeed_subject": indeed_subject,
    "ziprecruiter_subject": ziprecruiter_subject,
    "lensa_body": lensa_body,
    "agency_body": agency_body,
    "paramount_body": paramount_body,
    "marriott_body": marriott_body,
    "wbd_body": wbd_body,
    "flag_only": flag_only,
}
