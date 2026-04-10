# scrape_all.py — Auto-starts the uvicorn worker, reads mapped URLs from
# mapped_pages.json, scrapes each domain's pages via the local API, saves
# the output, then shuts down the server.
# Usage: python scrape_all.py
#        python scrape_all.py --max-pages 5
#        python scrape_all.py --all

import argparse
import json
import sqlite3
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = PROJECT_ROOT / "mapped_pages.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "scraped_output"


# Reads custom pages (kind='page') from the native host DB.
# These are full URLs the user explicitly added via the extension popup,
# and they bypass the mapper entirely.
def load_custom_pages():
    candidates = [
        PROJECT_ROOT / "native_host" / "local_benefits.db",
        PROJECT_ROOT / "local_benefits.db",
    ]
    for path in candidates:
        if path.exists():
            conn = sqlite3.connect(str(path))
            try:
                rows = conn.execute(
                    "SELECT DISTINCT value FROM web_history WHERE kind = 'page'"
                ).fetchall()
                return [row[0] for row in rows]
            finally:
                conn.close()
    return []


# Spins up uvicorn as a subprocess and polls until it's responding.
def start_server(port):
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "worker_service.scrape:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    for attempt in range(10):
        time.sleep(1)
        try:
            r = requests.get(f"{base_url}/docs", timeout=2)
            if r.ok:
                return proc
        except requests.ConnectionError:
            pass
    proc.kill()
    raise RuntimeError(f"Scrape worker failed to start on port {port} after 10s")


# Cleans up the uvicorn process, force-kills if it doesn't stop in time.
def stop_server(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# Reads mapped_pages.json and returns {domain: [url_list]} for every
# successfully mapped domain. Handles both schema v1 and v2.
def load_mapped_pages(path):
    with open(path) as f:
        data = json.load(f)

    if "domains" in data and isinstance(data["domains"], dict):
        return {
            domain: info.get("urls", [])
            for domain, info in data["domains"].items()
            if info.get("status") == "success"
        }

    if "urls" in data and "domain" in data:
        return {data["domain"]: data["urls"]}

    raise ValueError("Unrecognized mapped_pages.json format")


# POSTs a domain's page list to the scrape API and returns the JSON response.
def scrape_domain(domain_url, url_list, api_url, timeout_s=30):
    payload = {
        "domain": domain_url,
        "pages": [{"url": u} for u in url_list],
        "mode": "fetch_if_changed",
        "options": {
            "force_refresh": False,
            "client_has_pack": False,
            "timeout_s": timeout_s,
            "rate_limit_ms": 300,
        },
    }
    resp = requests.post(api_url, json=payload, timeout=600)
    resp.raise_for_status()
    return resp.json()


# Writes one consolidated text file per domain with all the scraped page content.
def save_results(domain_url, result, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

    host = urlparse(domain_url).netloc.replace(".", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"scraped_{host}_{stamp}.txt"

    lines = [
        f"Domain: {result['domain']}",
        f"Checked at: {result['checked_at']}",
        f"Cache hit: {result['cache_hit']}",
        f"Pages scraped: {len(result['changed_pages'])}",
        f"Unchanged: {len(result['unchanged_urls'])}",
        f"Errors: {len(result['errors'])}",
        "=" * 60,
    ]

    for page in result["changed_pages"]:
        lines.append(f"\n--- {page['url']} ---")
        lines.append(f"Title: {page['title']}")
        lines.append(f"Hash: {page['text_hash']}")
        lines.append("")
        wrapped = textwrap.fill(page["normalized_text"], width=80)
        lines.append(wrapped)
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Scrape all mapped domain pages.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="Path to mapped_pages.json")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="Directory for scraped output files")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Limit pages to scrape per domain (default: all)")
    parser.add_argument("--all", action="store_true",
                        help="(Deprecated, now the default) Scrape all mapped pages")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port for the scrape worker")
    args = parser.parse_args()

    print("=== LPBD Scraper ===\n")

    if not args.input.exists():
        print(f"Error: {args.input} not found.")
        print("Run `python map.py` first to discover domain URLs.")
        sys.exit(1)

    mapped = load_mapped_pages(args.input)
    if not mapped:
        print("No successfully mapped domains found. Nothing to scrape.")
        sys.exit(1)

    # Merge in custom pages from the native host DB (user-added URLs)
    custom_pages = load_custom_pages()
    if custom_pages:
        for page_url in custom_pages:
            domain = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
            if domain not in mapped:
                mapped[domain] = []
            if page_url not in mapped[domain]:
                mapped[domain].append(page_url)
        print(f"Added {len(custom_pages)} custom page(s) from native host DB.")

    total_urls = sum(len(urls) for urls in mapped.values())
    print(f"Loaded {len(mapped)} domain(s) with {total_urls} total URLs.")

    if args.max_pages:
        print(f"Using --max-pages {args.max_pages} per domain.\n")
    else:
        print("Scraping ALL mapped pages.\n")

    print(f"Starting scrape worker on 127.0.0.1:{args.port}...")
    server = start_server(args.port)
    print("Server ready.\n")

    api_url = f"http://127.0.0.1:{args.port}/scrape"
    total_scraped = 0
    total_errors = 0

    try:
        for i, (domain, urls) in enumerate(mapped.items(), 1):
            if args.max_pages:
                urls = urls[:args.max_pages]

            print(f"[{i}/{len(mapped)}] Scraping {domain} ({len(urls)} pages)...")

            try:
                result = scrape_domain(domain, urls, api_url)

                scraped = len(result["changed_pages"])
                unchanged = len(result["unchanged_urls"])
                errors = len(result["errors"])
                total_scraped += scraped
                total_errors += errors

                print(f"  Scraped: {scraped} | Unchanged: {unchanged} | Errors: {errors}")

                if result["errors"]:
                    for err in result["errors"]:
                        print(f"    - {err['url']}: {err['error']}")

                if result["changed_pages"]:
                    filepath = save_results(domain, result, args.output_dir)
                    print(f"  Saved to: {filepath}\n")
                else:
                    print(f"  No new content to save.\n")

            except Exception as exc:
                print(f"  Failed: {exc}\n")
                total_errors += 1

        print(f"=== Scraping Complete ===")
        print(f"Domains processed: {len(mapped)}")
        print(f"Total pages scraped: {total_scraped}")
        if total_errors:
            print(f"Total errors: {total_errors}")
        print(f"Output directory: {args.output_dir}")

    finally:
        print("\nShutting down scrape worker...", end=" ")
        stop_server(server)
        print("done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
