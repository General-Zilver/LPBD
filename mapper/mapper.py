import json
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
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    target = "https://www.utrgv.edu"
    result = map_domain(target, include_subdomains=True)

    if result["status"] == "success":
        print(
            f"Success ({result['discovery_method']}). "
            f"Found {result['found_count']} benefit pages from {result['raw_count']} discovered URLs."
        )

        with open("mapped_pages.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print("Saved to mapped_pages.json")

        print("\nTop 5 examples:")
        for u in result["urls"][:5]:
            print(f" - {u}")
    else:
        print(f"Failed: {result['message']}")
