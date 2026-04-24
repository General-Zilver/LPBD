import argparse
import json
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from batch_workers import launch_background, resolve_worker_count, should_run_in_background

# Identifies us in request headers so site admins can see who's hitting their server.
USER_AGENT = "UTRGV-StudentBenefitMapper/0.2 (+https://github.com/General-Zilver/LPBD)"

# File types to skip while collecting URLs so crawl scope stays page-focused.
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
}

# Path fragments that indicate junk pages (login, admin, portals, etc.).
# Case-insensitive check against the URL path. Easy to extend — just add a string.
EXCLUDED_PATH_FRAGMENTS = [
    "/login", "/signin", "/sign-in", "/log-in",
    "/account", "/forgot", "/forgotpassword", "/password",
    "/systemcheck", "/shibboleth",
    "/wp-admin", "/wp-login",
    "/pre_apply", "/print_preview", "/bookmarks",
    "/user/forgot", "/user/edit",
    # Calendar and event infrastructure that generates thousands of per-day pages.
    "/event/", "/events/", "/venue/", "/venues/",
    "/group/", "/groups/",
    "/photo/", "/photos/",
    "/calendar/", "/calendar",
    "/category/", "/tag/",
    # Old catalog archives that bloat the crawl with outdated content.
    "/archive/", "/archive",
]

# Entire subdomains to skip (portals, admin panels, etc.).
EXCLUDED_SUBDOMAINS = [
    "my.utrgv.edu",
    # Auth-walled portals where every page is empty or login-gated.
    "brightspace.utrgv.edu",
    "careers.utrgv.edu",
    "assist.utrgv.edu",
    # Dedicated calendar/event subdomains that produce per-day noise.
    "calendar.utrgv.edu",
    "events.southtexascollege.edu",
]

# Likely benefit-related paths to seed into BFS so we hit relevant content fast
# on large domains. Pages that don't exist (404) fail fast and get skipped.
# Easy to extend — just add a string.
BENEFIT_HUB_PATHS = [
    "/admissions",
    "/financial-aid",
    "/cost-and-aid",
    "/scholarships",
    "/student-services",
    "/student-life",
    "/counseling",
    "/health",
    "/health-services",
    "/wellness",
    "/disability",
    "/accessibility",
    "/veterans",
    "/veteran-services",
    "/tuition",
    "/aid",
    "/benefits",
    "/support",
    "/resources",
    "/students",
    "/current-students",
    "/student-affairs",
    "/student-support",
    "/basic-needs",
    "/food-pantry",
    "/emergency-aid",
    "/financial-wellness",
    "/care-team",
    "/case-management",
    "/international-students",
    "/undocumented-students",
    "/transfer",
    "/registrar",
]

# ISO 639-1 two-letter language codes used to detect translated portal duplicates
# like /es/financial-aid or /zh-hans/page. We keep the original English page and
# drop the translated variant.
_LANG_CODES = {
    "aa", "ab", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az",
    "ba", "be", "bg", "bh", "bi", "bm", "bn", "bo", "br", "bs",
    "ca", "ce", "ch", "co", "cr", "cs", "cu", "cv", "cy",
    "da", "de", "dv", "dz",
    "ee", "el", "eo", "es", "et", "eu",
    "fa", "ff", "fi", "fj", "fo", "fr", "fy",
    "ga", "gd", "gl", "gn", "gu", "gv",
    "ha", "he", "hi", "ho", "hr", "ht", "hu", "hy", "hz",
    "ia", "id", "ie", "ig", "ii", "ik", "io", "is", "it", "iu",
    "ja", "jv",
    "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn", "ko", "kr", "ks", "ku", "kv", "kw", "ky",
    "la", "lb", "lg", "li", "ln", "lo", "lt", "lu", "lv",
    "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my",
    "na", "nb", "nd", "ne", "ng", "nl", "nn", "no", "nr", "nv", "ny",
    "oc", "oj", "om", "or", "os",
    "pa", "pi", "pl", "ps", "pt",
    "qu",
    "rm", "rn", "ro", "ru", "rw",
    "sa", "sc", "sd", "se", "sg", "si", "sk", "sl", "sm", "sn", "so", "sq", "sr", "ss", "st", "su", "sv", "sw",
    "ta", "te", "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty",
    "ug", "uk", "ur", "uz",
    "ve", "vi", "vo",
    "wa", "wo",
    "xh",
    "yi", "yo",
    "za", "zh", "zu",
}


# Checks if a single URL should be excluded from the mapped output.
def _is_excluded_url(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    # Whole subdomain exclusion
    for sub in EXCLUDED_SUBDOMAINS:
        if host == sub or host.endswith("." + sub):
            return True

    # Path fragment exclusion
    for frag in EXCLUDED_PATH_FRAGMENTS:
        if frag in path:
            return True

    # Translated portal duplicate: path starts with /xx/ or /xx-yy/ where xx is a lang code
    parts = path.strip("/").split("/")
    if parts:
        first = parts[0]
        # Match "es", "zh-hans", "pt-br", etc.
        lang_base = first.split("-")[0]
        if lang_base in _LANG_CODES and len(parts) > 1:
            return True

    return False


# Filters a set of URLs, removing excluded ones. Returns (kept, excluded_count).
def filter_urls(urls):
    kept = set()
    excluded = 0
    for url in urls:
        if _is_excluded_url(url):
            excluded += 1
        else:
            kept.add(url)
    return kept, excluded


OUTPUT_FILE = Path(__file__).resolve().parent / "mapped_pages.json"


# Custom session that actually enforces a timeout on every request.
# requests.Session doesn't have a built-in timeout property, so if you just do
# session.timeout = 10 it does nothing. This subclass injects a default timeout
# into every request so we never accidentally wait forever on a hung server.
class _TimeoutSession(requests.Session):
    def __init__(self, timeout=10):
        super().__init__()
        self._default_timeout = timeout

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", self._default_timeout)
        return super().request(*args, **kwargs)


# Builds a session with our User-Agent and timeout baked in.
# Every request through this session gets connection pooling, our UA header,
# and a real enforced timeout without having to pass them in every single call.
def _build_session(timeout=10):
    session = _TimeoutSession(timeout=timeout)
    session.headers.update({"User-Agent": USER_AGENT})
    return session

# Normalizes the starting host and strips a leading "www." for root-domain matching.
def get_root_host(url):
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# Checks if a hostname belongs to the same domain we started with (or one of its subdomains).
def is_allowed_host(host, root_host, include_subdomains=True):
    host = (host or "").lower()
    root_host = (root_host or "").lower()

    if not host or not root_host:
        return False

    if include_subdomains:
        return host == root_host or host.endswith("." + root_host)

    return host == root_host


# Converts relative links to absolute URLs and removes fragments/query strings/noise.
def clean_and_join(base_url, href):
    full_url = urljoin(base_url, href)
    parsed = urlparse(full_url)

    if parsed.scheme not in {"http", "https"}:
        return None

    # Normalize http to https so we don't discover both variants of the same page.
    clean_url = f"https://{parsed.netloc}{parsed.path}"
    lower_path = parsed.path.lower()
    if any(lower_path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return None

    return clean_url.rstrip("/") or clean_url


# Extracts allowed in-domain links from an HTML document.
def extract_same_domain_links(base_url, html, include_subdomains=True):
    root_host = get_root_host(base_url)
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for tag in soup.find_all("a", href=True):
        normalized = clean_and_join(base_url, tag["href"])
        if not normalized:
            continue

        link_host = urlparse(normalized).netloc
        if is_allowed_host(link_host, root_host, include_subdomains=include_subdomains):
            links.add(normalized)

    return links


# Looks for sitemaps in the usual places (sitemap.xml, robots.txt) and collects every
# page URL it can find. Handles both regular sitemaps and sitemap indexes that point
# to other sitemaps. Returns an empty set if the site doesn't have one.
def fetch_sitemap_urls(base_url, session=None, include_subdomains=True):
    session = session or _build_session()
    base_clean = base_url.rstrip("/")
    candidates = [f"{base_clean}/sitemap.xml", f"{base_clean}/sitemap_index.xml"]

    try:
        robots = session.get(f"{base_clean}/robots.txt")
        if robots.ok:
            for line in robots.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    if sitemap_url:
                        candidates.append(sitemap_url)
    except requests.RequestException:
        pass

    seen_sitemaps = set()
    collected_urls = set()
    root_host = get_root_host(base_url)

    for sitemap_url in candidates:
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        try:
            response = session.get(sitemap_url)
            response.raise_for_status()
        except requests.RequestException:
            continue

        xml = BeautifulSoup(response.text, "xml")
        loc_tags = [loc.get_text(strip=True) for loc in xml.find_all("loc")]
        if not loc_tags:
            continue

        # If this is a sitemap index, fetch each child sitemap and collect page locs.
        if xml.find("sitemapindex"):
            for child_sitemap in loc_tags:
                if child_sitemap in seen_sitemaps:
                    continue
                seen_sitemaps.add(child_sitemap)
                try:
                    child_resp = session.get(child_sitemap)
                    child_resp.raise_for_status()
                except requests.RequestException:
                    continue

                child_xml = BeautifulSoup(child_resp.text, "xml")
                for loc in child_xml.find_all("loc"):
                    page = clean_and_join(base_url, loc.get_text(strip=True))
                    if not page:
                        continue

                    page_host = urlparse(page).netloc
                    if is_allowed_host(page_host, root_host, include_subdomains=include_subdomains):
                        collected_urls.add(page)
        else:
            # Regular sitemap: collect page locs directly.
            for loc in loc_tags:
                page = clean_and_join(base_url, loc)
                if not page:
                    continue

                page_host = urlparse(page).netloc
                if is_allowed_host(page_host, root_host, include_subdomains=include_subdomains):
                    collected_urls.add(page)

    return collected_urls


# Crawls a domain starting from the homepage using breadth-first search.
# Pre-seeds the queue with likely benefit hub paths so BFS finds relevant content
# quickly on large domains. Sitemap URLs go into `results` (discovered for free) but
# NOT into `visited`, so BFS can still reach them organically. Excluded URLs are
# filtered out during BFS so max_pages doesn't get wasted on junk. Tracks a `queued`
# set alongside `visited` so each URL is enqueued exactly once (nav bars and footers
# repeat the same links on every page).
def bfs_crawl(base_url, preseed=None, session=None, include_subdomains=True,
              max_pages=None, delay=0.3):
    session = session or _build_session()

    # Preseed (sitemap URLs) should already be filtered by map_domain before
    # reaching here, so we accept them directly.
    results = set(preseed or set())

    visited = set()                   # URLs we've fetched
    queued = set()                    # URLs ever added to queue (prevents re-enqueue)
    queue = deque()

    # If the homepage itself is excluded (e.g. entire subdomain blocked), abort early.
    if _is_excluded_url(base_url):
        print(f"   Homepage {base_url} is excluded. Skipping BFS.")
        return results, 0

    queue.append(base_url)
    queued.add(base_url)

    # Seed benefit hub URLs alongside the homepage. Pages that don't exist (404)
    # fail fast and get skipped. Pages that do exist give BFS a huge head start.
    base_clean = base_url.rstrip("/")
    for path in BENEFIT_HUB_PATHS:
        hub_url = base_clean + path
        if hub_url not in queued:
            queue.append(hub_url)
            queued.add(hub_url)

    pages_fetched = 0
    links_kept = 0
    links_excluded = 0
    domain_label = urlparse(base_url).netloc.replace("www.", "")

    while queue and (max_pages is None or pages_fetched < max_pages):
        current_url = queue.popleft()

        # Don't fetch the same page twice.
        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            resp = session.get(current_url)
            resp.raise_for_status()
        except requests.RequestException:
            continue

        pages_fetched += 1
        results.add(current_url)

        # Progress log every 25 pages so long crawls don't look hung.
        if pages_fetched % 25 == 0:
            short_path = (urlparse(current_url).path or "/")[:40]
            print(f"   [{domain_label}] Crawled {pages_fetched} | "
                  f"Queue: {len(queue)} | Kept: {links_kept} | "
                  f"Excluded: {links_excluded} | Current: {short_path}")

        new_links = extract_same_domain_links(
            base_url, resp.text, include_subdomains=include_subdomains
        )

        for link in new_links:
            # Skip if already fetched or already in queue.
            if link in visited or link in queued:
                continue
            # Pre-filter junk so it never enters the queue or counts toward max_pages.
            if _is_excluded_url(link):
                links_excluded += 1
                continue
            results.add(link)
            queue.append(link)
            queued.add(link)
            links_kept += 1

        if delay > 0:
            time.sleep(delay)

    return results, pages_fetched


# Runs the full discovery pipeline for a single domain. First tries the sitemap to get
# a head start for free, then BFS crawls from the homepage to find anything the sitemap
# missed. Returns everything we found in one result dict.
def map_domain(url, include_subdomains=True, max_pages=None, delay=0.3):
    print(f"Mapping {url}...")
    session = _build_session()

    try:
        # Step 1: Try to grab the sitemap for a free head start.
        sitemap_urls_raw = fetch_sitemap_urls(url, session=session, include_subdomains=include_subdomains)
        sitemap_raw_count = len(sitemap_urls_raw)

        # Filter junk from sitemap URLs before passing to BFS.
        sitemap_urls, sitemap_filtered = filter_urls(sitemap_urls_raw)
        sitemap_count = len(sitemap_urls)

        if sitemap_raw_count:
            if sitemap_filtered:
                print(f"   Sitemap found. Pre-seeded {sitemap_count} URLs ({sitemap_filtered} filtered out).")
            else:
                print(f"   Sitemap found. Pre-seeded {sitemap_count} URLs.")
        else:
            print("   No sitemap found. BFS will do all discovery.")

        # Step 2: BFS from homepage. Sitemap URLs are pre-seeded into results but can
        # still be visited for their outgoing links if BFS reaches them naturally.
        all_urls, pages_fetched = bfs_crawl(
            base_url=url,
            preseed=sitemap_urls,
            session=session,
            include_subdomains=include_subdomains,
            max_pages=max_pages,
            delay=delay,
        )

        crawl_found = len(all_urls) - sitemap_count
        print(f"   BFS fetched {pages_fetched} pages, discovered {crawl_found} additional URLs.")

        # Safety net: catch any excluded URLs that slipped through via preseed.
        all_urls, excluded_count = filter_urls(all_urls)
        if excluded_count:
            print(f"   Filtered out {excluded_count} sitemap URL(s).")

        return {
            "status": "success",
            "domain": url,
            "include_subdomains": include_subdomains,
            "sitemap_count": sitemap_count,
            "crawl_pages_fetched": pages_fetched,
            "crawl_additional": crawl_found,
            "filtered_out": excluded_count,
            "found_count": len(all_urls),
            "urls": sorted(all_urls),
        }
    except Exception as e:
        return {
            "status": "error",
            "domain": url,
            "include_subdomains": include_subdomains,
            "message": str(e),
        }

# Returns the current time in UTC ISO format for consistent metadata timestamps.
def _timestamp_utc():
    return datetime.now(timezone.utc).isoformat()

# Builds the default JSON structure used when starting a new mapped_pages file.
def _empty_mapped_payload():
    return {
        "schema_version": 2,
        "updated_at": _timestamp_utc(),
        "domain_count": 0,
        "domains": {},
    }

# Reads an existing output file and makes sure it's in the current multi-domain format.
# If someone has an old single-domain file from before, this wraps it into the new shape.
def _load_mapped_payload(raw_text):

    if not raw_text.strip():
        return _empty_mapped_payload()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return _empty_mapped_payload()

    if isinstance(data, dict) and isinstance(data.get("domains"), dict):
        data.setdefault("schema_version", 2)
        data.setdefault("updated_at", _timestamp_utc())
        data["domain_count"] = len(data["domains"])
        return data

    # Backward compatibility: legacy single-domain output -> wrap into domains map.
    if isinstance(data, dict) and data.get("domain"):
        wrapped = _empty_mapped_payload()
        wrapped["domains"][data["domain"]] = data
        wrapped["domain_count"] = 1
        return wrapped

    return _empty_mapped_payload()

# Locks the output file before we read/write so multiple workers don't step on each other.
# Works on both Windows (msvcrt) and Linux/Mac (fcntl).
@contextmanager
def _exclusive_file_lock(path):

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield handle
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

# Saves or updates a single domain's results into the shared output file.
# Handles the lock-read-modify-write cycle so it's safe to call from multiple threads.
def upsert_domain_result(result, output_path=OUTPUT_FILE):
    output_path = Path(output_path)

    with _exclusive_file_lock(output_path) as handle:
        handle.seek(0)
        payload = _load_mapped_payload(handle.read())

        domain_key = result.get("domain") or f"unknown_{len(payload['domains']) + 1}"
        result_with_timestamp = dict(result)
        result_with_timestamp["updated_at"] = _timestamp_utc()
        payload["domains"][domain_key] = result_with_timestamp

        payload["domains"] = dict(sorted(payload["domains"].items()))
        payload["domain_count"] = len(payload["domains"])
        payload["updated_at"] = _timestamp_utc()

        handle.seek(0)
        handle.truncate()
        json.dump(payload, handle, indent=2)
        handle.flush()

# Maps a list of domains, optionally in parallel, and writes each result to the output file
# as soon as it finishes. Falls back to one-at-a-time if there's only one domain.
def map_domains_batch(domains, include_subdomains=True, workers=1,
                      max_pages=None, delay=0.3, output_path=OUTPUT_FILE):

    workers = max(1, min(workers, len(domains)))

    if workers == 1:
        for domain in domains:
            result = map_domain(domain, include_subdomains=include_subdomains,
                                max_pages=max_pages, delay=delay)
            upsert_domain_result(result, output_path=output_path)
            _print_result_summary(result, output_path)
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(map_domain, domain, include_subdomains,
                            max_pages, delay): domain
            for domain in domains
        }
        for future in as_completed(futures):
            result = future.result()
            upsert_domain_result(result, output_path=output_path)
            _print_result_summary(result, output_path)

# Prints a quick summary after each domain finishes so you can see progress in the terminal
def _print_result_summary(result, output_path):
    if result["status"] == "success":
        print(
            f"Success ({result['domain']}). "
            f"Sitemap: {result['sitemap_count']} | "
            f"BFS: {result['crawl_additional']} new from {result['crawl_pages_fetched']} fetched | "
            f"Total: {result['found_count']} URLs."
        )
        print(f"Saved/updated {output_path}")

        print("Top 5 examples:")
        for u in result["urls"][:5]:
            print(f" - {u}")
    else:
        print(f"Failed ({result.get('domain', 'unknown')}): {result['message']}")

# Sets up all the command-line flags so you can control domains, concurrency, crawl depth, etc.
def _parse_args():
    parser = argparse.ArgumentParser(description="Map one or more domains into a shared mapped_pages.json file.")
    parser.add_argument(
        "domains",
        nargs="*",
        help="Domain URLs to map (e.g., https://www.utrgv.edu).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Number of domains to map concurrently (0 = auto).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help="Upper safety limit for worker auto-tuning.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Max pages to fetch per domain during BFS (default: unlimited).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="Seconds to wait between requests during BFS (default: 0.3).",
    )
    parser.add_argument(
        "--no-subdomains",
        action="store_true",
        help="Restrict mapping to the exact host only.",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "foreground", "background"],
        default="auto",
        help="Run mode: auto backgrounds multi-domain batches.",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="Optional log file path for background mode.",
    )
    parser.add_argument(
        "--run-batch",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_FILE),
        help="Output JSON path (default: mapper/mapped_pages.json next to this script).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    targets = args.domains or ["https://www.utrgv.edu"]
    include_subdomains = not args.no_subdomains
    output_file = Path(args.output)
    max_workers = max(1, args.max_workers)
    resolved_workers = resolve_worker_count(
        domain_count=len(targets),
        requested_workers=args.workers,
        max_workers=max_workers,
    )

    run_in_background = (not args.run_batch) and should_run_in_background(args.mode, len(targets))
    if run_in_background:
        pid, log_path = launch_background(
            script_path=Path(__file__).resolve(),
            domains=targets,
            requested_workers=args.workers,
            max_workers=max_workers,
            include_subdomains=include_subdomains,
            output_path=output_file,
            max_pages=args.max_pages,
            delay=args.delay,
            log_file=args.log_file,
        )
        print(f"Started background mapper process PID {pid}.")
        print(f"Logs: {log_path}")
        print(f"Output file: {output_file}")
        raise SystemExit(0)

    print(f"Running mapper with {resolved_workers} worker(s).")

    map_domains_batch(
        domains=targets,
        include_subdomains=include_subdomains,
        workers=resolved_workers,
        max_pages=args.max_pages,
        delay=args.delay,
        output_path=output_file,
    )
