"""Parsers for LPBD pipeline outputs."""
from __future__ import annotations
import re


def parse_map_log(lines: list[str]) -> dict:
    # Parses map.log into the DATA shape expected by map_report.html
    domains: list[dict] = []
    current_domain: dict | None = None
    in_examples = False
    example_count = 0

    for line in lines:
        stripped = line.strip()

        # Domain start: "Mapping https://utrgv.edu..."
        m = re.match(r"Mapping (https?://(.+?))\.\.\.", stripped)
        if m:
            current_domain = {
                "name": m.group(2),
                "url": m.group(1),
                "completed": False,
                "no_sitemap": False,
                "sitemap_count": 0,
                "bfs_fetched": 0,
                "bfs_discovered": 0,
                "total_urls": 0,
                "progress": [],
                "examples": [],
            }
            domains.append(current_domain)
            in_examples = False
            example_count = 0
            continue

        if current_domain is None:
            continue

        # No sitemap marker
        if "No sitemap found" in stripped:
            current_domain["no_sitemap"] = True
            continue

        # Sitemap found with pre-seeded count
        m = re.match(r"Sitemap found\. Pre-seeded (\d+) URLs", stripped)
        if m:
            current_domain["sitemap_count"] = int(m.group(1))
            continue

        # New format: Crawled N | Found: N | Queue: N | Excluded: N | Dupes: N | Current: ...
        m = re.match(
            r"\[.+?\] Crawled (\d+) \| Found: (\d+) \| Queue: (\d+) \| "
            r"Excluded: (\d+) \| Dupes: (\d+) \| Current: (.+)",
            stripped,
        )
        if m:
            current_domain["progress"].append({
                "crawled": int(m.group(1)),
                "found": int(m.group(2)),
                "queue": int(m.group(3)),
                "excluded": int(m.group(4)),
                "dupes": int(m.group(5)),
                "current": m.group(6).strip(),
            })
            continue

        # Old format: Crawled N | Queue: N | Kept: N | Excluded: N | Current: ...
        m = re.match(
            r"\[.+?\] Crawled (\d+) \| Queue: (\d+) \| Kept: (\d+) \| Excluded: (\d+) \| Current: (.+)",
            stripped,
        )
        if m:
            current_domain["progress"].append({
                "crawled": int(m.group(1)),
                "found": int(m.group(3)),
                "queue": int(m.group(2)),
                "excluded": int(m.group(4)),
                "dupes": 0,
                "current": m.group(5).strip(),
            })
            continue

        # BFS completion: "BFS fetched N pages, discovered N additional URLs."
        m = re.match(r"BFS fetched (\d+) pages, discovered (\d+) additional URLs", stripped)
        if m:
            current_domain["bfs_fetched"] = int(m.group(1))
            current_domain["bfs_discovered"] = int(m.group(2))
            continue

        # Success line: "Success (url). Sitemap: N | BFS: N new from N fetched | Total: N URLs."
        m = re.match(
            r"Success \(.+?\)\. Sitemap: (\d+) \| BFS: (\d+) new from (\d+) fetched \| Total: (\d+)",
            stripped,
        )
        if m:
            current_domain["sitemap_count"] = int(m.group(1))
            current_domain["bfs_discovered"] = int(m.group(2))
            current_domain["bfs_fetched"] = int(m.group(3))
            current_domain["total_urls"] = int(m.group(4))
            current_domain["completed"] = True
            continue

        # Top 5 examples header
        if stripped.startswith("Top 5 examples"):
            in_examples = True
            example_count = 0
            continue

        # Example URL lines (indented with " - ")
        if in_examples and stripped.startswith("- "):
            if example_count < 5:
                current_domain["examples"].append(stripped[2:])
                example_count += 1
            continue
        elif in_examples and not stripped.startswith("- "):
            in_examples = False

    # Compute exclusion_ratio for each domain
    for d in domains:
        progress = d["progress"]
        if progress:
            last = progress[-1]
            total_seen = last["found"] + last["excluded"]
            d["exclusion_ratio"] = last["excluded"] / total_seen if total_seen else 0
        else:
            d["exclusion_ratio"] = 0

    # Build totals in the shape the template JS expects
    completed = sum(1 for d in domains if d["completed"])
    totals = {
        "domains": len(domains),
        "urls": sum(d["total_urls"] for d in domains),
        "completed_domains": completed,
    }

    return {"type": "map", "domains": domains, "totals": totals}


def parse_scrape_log(lines: list[str]) -> dict:
    # Parses scrape_all.log into the DATA shape expected by scrape_report.html
    domains: list[dict] = []
    error_categories: dict[str, int] = {}
    current_domain: dict | None = None
    total_domains = 0
    log_totals: dict = {}

    for line in lines:
        stripped = line.strip()

        # Domain start: "[N/M] Scraping https://... (N pages)..."
        m = re.match(
            r"\[(\d+)/(\d+)\] Scraping (https?://(.+?)) \((\d+) pages?\)\.\.\.",
            stripped,
        )
        if m:
            total_domains = int(m.group(2))
            current_domain = {
                "index": int(m.group(1)),
                "of": total_domains,
                "url": m.group(3),
                "name": m.group(4),
                "page_count": int(m.group(5)),
                "scraped": 0,
                "unchanged": 0,
                "errors": 0,
                "error_samples": [],
                "saved_to": None,
                "is_custom": False,
            }
            domains.append(current_domain)
            continue

        if current_domain is None:
            # Parse final totals from the log
            m = re.match(r"Total pages scraped:\s*(\d+)", stripped)
            if m:
                log_totals["pages_scraped"] = int(m.group(1))
                continue
            m = re.match(r"Total errors:\s*(\d+)", stripped)
            if m:
                log_totals["errors"] = int(m.group(1))
                continue
            m = re.match(r"Domains processed:\s*(\d+)", stripped)
            if m:
                log_totals["domains"] = int(m.group(1))
                continue
            # Custom page line: "Custom: https://..."
            m = re.match(r"Custom: (https?://\S+)", stripped)
            if m:
                current_domain = {
                    "index": None,
                    "of": None,
                    "url": m.group(1),
                    "name": f"[custom] {m.group(1)}",
                    "page_count": 1,
                    "scraped": 0,
                    "unchanged": 0,
                    "errors": 0,
                    "error_samples": [],
                    "saved_to": None,
                    "is_custom": True,
                }
                domains.append(current_domain)
            continue

        # Domain total line: "Total: Scraped N | Unchanged: N | Errors: N"
        m = re.match(r"Total: Scraped (\d+) \| Unchanged: (\d+) \| Errors: (\d+)", stripped)
        if m:
            current_domain["scraped"] = int(m.group(1))
            current_domain["unchanged"] = int(m.group(2))
            current_domain["errors"] = int(m.group(3))
            current_domain = None
            continue

        # Saved to line
        m = re.match(r"Saved to: (.+)", stripped)
        if m:
            current_domain["saved_to"] = m.group(1)
            if current_domain["is_custom"]:
                current_domain = None
            continue

        # Error sample line (indented "- url: reason")
        m = re.match(r"- (https?://\S+): (.+)", stripped)
        if m:
            url = m.group(1)
            reason = m.group(2)
            category = _categorize_error(reason)
            current_domain["error_samples"].append({
                "url": url,
                "reason": reason,
                "category": category,
            })
            error_categories[category] = error_categories.get(category, 0) + 1
            continue

    # Build totals in the shape the template JS expects (prefer log values)
    non_custom = [d for d in domains if not d["is_custom"]]
    final_totals = {
        "domains": log_totals.get("domains", len(non_custom)),
        "pages_scraped": log_totals.get("pages_scraped", sum(d["scraped"] for d in domains)),
        "errors": log_totals.get("errors", sum(d["errors"] for d in domains)),
    }

    return {
        "type": "scrape",
        "domains": domains,
        "error_categories": error_categories,
        "totals": final_totals,
    }


def _categorize_error(reason: str) -> str:
    # Bucket an error reason string into a category
    r = reason.lower()
    if "duplicate content" in r:
        return "duplicate"
    if "junk title" in r:
        return "junk_title"
    if "empty normalized" in r:
        return "empty_text"
    if "auth or utility" in r:
        return "auth_utility"
    m = re.match(r"http (\d{3})", r)
    if m:
        code = m.group(1)
        return f"http_{code}"
    if "max retries" in r or "nameresolutionerror" in r or "connecttimeouterror" in r:
        return "network"
    return "other"


def slim_benefits(envelope: dict) -> list[dict]:
    # Slim down matched_benefits.json to the fields expected by benefits.html
    results = envelope.get("results", [])
    out = []
    for r in results:
        out.append({
            "id": r.get("match_id", "")[:8],
            "name": r.get("benefit_name", ""),
            "page_title": r.get("page_title", ""),
            "page_url": r.get("page_url", ""),
            "summary": r.get("summary", ""),
            "action_details": r.get("action_details", ""),
            "eligibility": r.get("eligibility_status", ""),
            "match_type": r.get("match_type", ""),
            "action": r.get("action", ""),
            "tags": r.get("tags", []),
            "relevance": r.get("relevance_score", 0),
        })
    return out
