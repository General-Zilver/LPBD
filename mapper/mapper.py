import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Keywords that indicate pages likely related to student benefits/resources.
KEYWORDS_TO_KEEP = [
    "aid", "grant", "scholarship", "loan", "work-study",
    "health", "clinic", "wellness", "counseling", "support",
    "service", "resource", "pantry", "transportation",
    "discount", "free", "waiver", "stipend", "funding",
    "eligibility", "deadline", "apply", "benefit", "housing",
]

KEYWORDS_TO_IGNORE = [
    "news", "event", "calendar", "archive", "athletics",
    "staff", "faculty", "directory", "profile", "minutes",
    "policy", "handbook", "login", "auth", "twitter", "facebook", "instagram",
]

# File types to skip while collecting URLs so crawl scope stays page-focused.
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
}

OUTPUT_FILE = Path(__file__).resolve().parent / "mapped_pages.json"


# Normalizes the starting host and strips a leading "www." for root-domain matching.
def get_root_host(url):
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# Checks whether a host is the root domain or one of its subdomains.
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

    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
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


# Tries common sitemap locations (plus robots.txt) and returns allowed page URLs.
def fetch_sitemap_urls(base_url, timeout=10, include_subdomains=True):
    base_clean = base_url.rstrip("/")
    candidates = [f"{base_clean}/sitemap.xml", f"{base_clean}/sitemap_index.xml"]

    try:
        robots = requests.get(f"{base_clean}/robots.txt", timeout=timeout)
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
            response = requests.get(sitemap_url, timeout=timeout)
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
                    child_resp = requests.get(child_sitemap, timeout=timeout)
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


# Performs a bounded 2-level crawl: homepage links, then links from those pages.
def minimal_depth2_crawl(
    base_url,
    timeout=8,
    max_home_links=60,
    max_second_pages=30,
    include_subdomains=True,
):
    discovered = set()

    # Level 0 -> Level 1: collect links on the homepage.
    home_resp = requests.get(base_url, timeout=timeout)
    home_resp.raise_for_status()
    level1_links = sorted(
        extract_same_domain_links(base_url, home_resp.text, include_subdomains=include_subdomains)
    )[:max_home_links]
    discovered.update(level1_links)

    # Level 1 -> Level 2: collect links from each first-level page.
    for page_url in level1_links[:max_second_pages]:
        try:
            resp = requests.get(page_url, timeout=timeout)
            resp.raise_for_status()
            discovered.update(
                extract_same_domain_links(base_url, resp.text, include_subdomains=include_subdomains)
            )
        except requests.RequestException:
            continue

    return discovered


# Applies keyword include/exclude rules to keep only relevant benefit-oriented URLs.
def filter_relevant(urls):
    relevant = []
    for page_url in urls:
        page_url_lower = page_url.lower()
        if any(keyword in page_url_lower for keyword in KEYWORDS_TO_KEEP):
            if not any(ignore in page_url_lower for ignore in KEYWORDS_TO_IGNORE):
                relevant.append(page_url)
    return sorted(relevant)


# Orchestrates discovery: sitemap first, then bounded crawl fallback, then filtering.
def map_domain(url, include_subdomains=True):
    print(f"Mapping {url}...")

    try:
        sitemap_urls = fetch_sitemap_urls(url, include_subdomains=include_subdomains)
        if sitemap_urls:
            source = "sitemap"
            raw_urls = sitemap_urls
            print(f"   Sitemap found. Collected {len(raw_urls)} URLs.")
        else:
            source = "minimal_depth2_crawl"
            print("   No sitemap found. Running bounded 2-level crawl...")
            raw_urls = minimal_depth2_crawl(url, include_subdomains=include_subdomains)
            print(f"   Crawl collected {len(raw_urls)} URLs.")

        relevant_urls = filter_relevant(raw_urls)

        return {
            "status": "success",
            "domain": url,
            "include_subdomains": include_subdomains,
            "discovery_method": source,
            "raw_count": len(raw_urls),
            "found_count": len(relevant_urls),
            "urls": relevant_urls,
        }
    except Exception as e:
        return {
            "status": "error",
            "domain": url,
            "include_subdomains": include_subdomains,
            "message": str(e),
        }


def _timestamp_utc():
    # Returns the current time in UTC ISO format for consistent metadata timestamps.
    return datetime.now(timezone.utc).isoformat()


def _empty_mapped_payload():
    # Builds the default JSON structure used when starting a new mapped_pages file.
    return {
        "schema_version": 2,
        "updated_at": _timestamp_utc(),
        "domain_count": 0,
        "domains": {},
    }


def _load_mapped_payload(raw_text):
    # Reads existing JSON text and normalizes it into the shared multi-domain schema.
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


@contextmanager
def _exclusive_file_lock(path):
    # Opens and locks the output file so concurrent writers do not corrupt shared JSON.
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


def upsert_domain_result(result, output_path=OUTPUT_FILE):
    # Creates or updates a single domain section in the shared mapped_pages JSON file.
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


def map_domains_batch(domains, include_subdomains=True, workers=1, output_path=OUTPUT_FILE):
    # Maps many domains and writes each completed result into one shared output file.
    workers = max(1, min(workers, len(domains)))

    if workers == 1:
        for domain in domains:
            result = map_domain(domain, include_subdomains=include_subdomains)
            upsert_domain_result(result, output_path=output_path)
            _print_result_summary(result, output_path)
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(map_domain, domain, include_subdomains): domain
            for domain in domains
        }
        for future in as_completed(futures):
            result = future.result()
            upsert_domain_result(result, output_path=output_path)
            _print_result_summary(result, output_path)


def _print_result_summary(result, output_path):
    # Prints a concise per-domain summary after each mapping job finishes.
    if result["status"] == "success":
        print(
            f"Success ({result['domain']} | {result['discovery_method']}). "
            f"Found {result['found_count']} benefit pages from {result['raw_count']} discovered URLs."
        )
        print(f"Saved/updated {output_path}")

        print("Top 5 examples:")
        for u in result["urls"][:5]:
            print(f" - {u}")
    else:
        print(f"Failed ({result.get('domain', 'unknown')}): {result['message']}")


def _parse_args():
    # Defines command-line options for domain list, concurrency, scope, and output file.
    parser = argparse.ArgumentParser(description="Map one or more domains into a shared mapped_pages.json file.")
    parser.add_argument(
        "domains",
        nargs="*",
        help="Domain URLs to map (e.g., https://www.utrgv.edu).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of domains to map concurrently.",
    )
    parser.add_argument(
        "--no-subdomains",
        action="store_true",
        help="Restrict mapping to the exact host only.",
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

    map_domains_batch(
        domains=targets,
        include_subdomains=include_subdomains,
        workers=args.workers,
        output_path=output_file,
    )
