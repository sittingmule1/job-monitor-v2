"""
digest.py
=========
Renders the static HTML digest published to GitHub Pages. The whole point
of this file: confidence tier is never ambiguous. Every section is labeled
with what it means for how much you should trust it unread.
"""

import datetime
from src.sources import Confidence
from src.scoring import sort_records

TIER_META = {
    Confidence.VERIFIED: {
        "label": "✅ Verified — title, company, and link confirmed",
        "desc": "Structured data straight from the source. Safe to scan and act on directly.",
    },
    Confidence.BEST_EFFORT: {
        "label": "⚠️ Best-effort — parsed, but format is inconsistent",
        "desc": "Extracted automatically but from a source known to shift format. Worth a quick sanity check before acting.",
    },
    Confidence.MANUAL_CHECK: {
        "label": "🔍 Manual-check — activity detected, details not available",
        "desc": "The monitor knows something changed here but can't tell you what. Click through and look yourself.",
    },
}

TIER_ORDER = [Confidence.VERIFIED, Confidence.BEST_EFFORT, Confidence.MANUAL_CHECK]


def _tier_value(rec):
    c = rec["confidence"]
    return c if isinstance(c, Confidence) else Confidence(c)


def render(all_records, new_only_count):
    generated = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    by_tier = {t: [] for t in TIER_ORDER}
    for rec in all_records:
        by_tier[_tier_value(rec)].append(rec)

    sections_html = []
    for tier in TIER_ORDER:
        recs = sort_records(by_tier[tier])
        if not recs:
            continue
        meta = TIER_META[tier]
        rows = []
        for r in recs:
            title = r.get("title") or "(no title extracted)"
            company = r.get("company") or ""
            link = r.get("link") or ""
            sources = ", ".join(sorted(set(r.get("sources", [r.get("source", "")]))))
            new_badge = '<span class="new-badge">NEW</span>' if r.get("is_new") else ""
            title_html = f'<a href="{link}" target="_blank">{title}</a>' if link else title
            rows.append(f"""
                <tr>
                    <td>{new_badge}{title_html}</td>
                    <td>{company}</td>
                    <td class="src">{sources}</td>
                </tr>""")
        sections_html.append(f"""
        <section class="tier-{tier.value}">
            <h2>{meta['label']} <span class="count">({len(recs)})</span></h2>
            <p class="tier-desc">{meta['desc']}</p>
            <table>
                <thead><tr><th>Title</th><th>Company</th><th>Source(s)</th></tr></thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </section>""")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Job Monitor Digest</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ font-size: 1.4em; }}
  .meta {{ color: #666; margin-bottom: 30px; }}
  section {{ margin-bottom: 40px; }}
  h2 {{ font-size: 1.1em; border-bottom: 2px solid #ddd; padding-bottom: 6px; }}
  .tier-verified h2 {{ border-color: #2e7d32; }}
  .tier-best_effort h2 {{ border-color: #f9a825; }}
  .tier-manual_check h2 {{ border-color: #c62828; }}
  .tier-desc {{ color: #555; font-size: 0.9em; margin-top: 4px; }}
  .count {{ color: #888; font-weight: normal; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid #eee; font-size: 0.92em; }}
  th {{ color: #888; font-weight: 600; font-size: 0.8em; text-transform: uppercase; }}
  td.src {{ color: #888; font-size: 0.85em; }}
  a {{ color: #1a5fb4; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .new-badge {{ background: #2e7d32; color: white; font-size: 0.7em; padding: 2px 6px; border-radius: 3px; margin-right: 6px; }}
</style>
</head>
<body>
<h1>Job Monitor Digest</h1>
<p class="meta">Generated {generated} &middot; {new_only_count} new since last run &middot; {len(all_records)} total tracked</p>
{''.join(sections_html)}
</body>
</html>"""
    return html
