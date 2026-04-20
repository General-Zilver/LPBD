# scrape_all.py — Auto-starts the uvicorn worker, reads mapped URLs from
# mapped_pages.json, scrapes each domain's pages via the local API, then
# scrapes custom pages individually with force_refresh, and shuts down.
# Usage: python scrape_all.py
#        python scrape_all.py --max-pages 5

import argparse
import json
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from custom_pages import load_custom_pages, update_page_status


# Duplicates writes to both a terminal stream and a log file.
class _Tee:
    def __init__(self, original, log_file):
        self.original = original
        self.log_file = log_file

    def write(self, data):
        self.original.write(data)
        self.log_file.write(data)

    def flush(self):
        self.original.flush()
        self.log_file.flush()


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = PROJECT_ROOT / "mapped_pages.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "scraped_output"


# Spins up uvicorn as a subprocess and polls until it's responding.
def start_server(port):
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "worker_service.scrape:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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


BATCH_SIZE = 100


# Sends one batch of URLs to the scrape API and returns the JSON response.
def _scrape_batch(domain_url, url_list, api_url, timeout_s=30):
    payload = {
        "domain": domain_url,
        "pages": [{"url": u} for u in url_list],
        "mode": "fetch_if_changed",
        # force_refresh=True bypasses the pack_store cache read so each
        # batch gets its own URLs processed.
        # client_has_pack=False tells the worker we want full page content
        # returned for every URL, not just a changed/unchanged summary.
        # scrape_all.py writes fresh output files on every run and doesn't
        # retain prior pack state.
        "options": {
            "force_refresh": True,
            "client_has_pack": False,
            "timeout_s": timeout_s,
            "rate_limit_ms": 300,
        },
    }
    resp = requests.post(api_url, json=payload, timeout=600)
    resp.raise_for_status()
    return resp.json()


# Scrapes a domain in batches of BATCH_SIZE URLs. Accumulates all changed
# pages across batches, then writes one output file per domain. Old files for
# the same domain are removed first so stale data doesn't pile up.
def scrape_domain(domain_url, url_list, api_url, output_dir, timeout_s=30):
    batches = [url_list[i:i + BATCH_SIZE]
               for i in range(0, len(url_list), BATCH_SIZE)]
    num_batches = len(batches)
    total_scraped = 0
    total_unchanged = 0
    total_errors = 0
    all_changed_pages = []

    print(f"  Processing {len(url_list)} URLs in {num_batches} batch(es)...")

    for batch_num, batch_urls in enumerate(batches, 1):
        if num_batches > 1:
            print(f"  Batch {batch_num}/{num_batches}: {len(batch_urls)} pages...")

        result = _scrape_batch(domain_url, batch_urls, api_url,
                               timeout_s=timeout_s)

        scraped = len(result["changed_pages"])
        unchanged = len(result["unchanged_urls"])
        errors = len(result["errors"])
        total_scraped += scraped
        total_unchanged += unchanged
        total_errors += errors
        all_changed_pages.extend(result["changed_pages"])

        if num_batches > 1:
            print(f"    Scraped: {scraped} | Unchanged: {unchanged} | Errors: {errors}")

        if result["errors"]:
            for err in result["errors"]:
                print(f"    - {err['url']}: {err['error']}")

    # Write one consolidated file per domain and remove old ones.
    if all_changed_pages:
        _remove_old_domain_files(domain_url, output_dir)
        merged_result = {
            "domain": domain_url,
            "checked_at": datetime.now().isoformat(),
            "cache_hit": False,
            "changed_pages": all_changed_pages,
            "unchanged_urls": [],
            "errors": [],
        }
        filepath = save_results(domain_url, merged_result, output_dir)
        print(f"  Saved to: {filepath}")

    return total_scraped, total_unchanged, total_errors


# Removes previous scraped output files for a domain so we don't accumulate stale data.
def _remove_old_domain_files(domain_url, output_dir):
    host = urlparse(domain_url).netloc.replace(".", "_")
    output_dir = Path(output_dir)
    for old_file in output_dir.glob(f"scraped_{host}_*.txt"):
        old_file.unlink()



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


# Scrapes each custom page one at a time with force_refresh so they always
# get re-fetched regardless of the worker's weekly cache. The worker's
# change detection still prevents re-saving if the content is identical.
def scrape_custom_pages(custom_pages, api_url, output_dir, timeout_s=30):
    scraped = 0
    errors = 0

    for entry in custom_pages:
        url = entry["url"]
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        print(f"  Custom: {url}...")

        payload = {
            "domain": domain,
            "pages": [{"url": url}],
            "mode": "fetch_if_changed",
            "options": {
                "force_refresh": True,
                "client_has_pack": False,
                "timeout_s": timeout_s,
                "rate_limit_ms": 300,
            },
        }

        try:
            resp = requests.post(api_url, json=payload, timeout=600)
            resp.raise_for_status()
            result = resp.json()

            has_errors = bool(result.get("errors"))
            has_content = bool(result.get("changed_pages"))

            if has_content:
                filepath = save_results(domain, result, output_dir)
                print(f"    Saved to: {filepath}")
                scraped += 1
            elif has_errors:
                for err in result["errors"]:
                    print(f"    Error: {err.get('error', err)}")
                errors += 1
            else:
                print(f"    Unchanged (no new content).")

            if has_errors:
                update_page_status(url, "error")
            else:
                update_page_status(url, "scraped",
                                   scraped_at=datetime.now().isoformat())

        except Exception as exc:
            print(f"    Failed: {exc}")
            update_page_status(url, "error")
            errors += 1

    return scraped, errors


def main():
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = open(log_dir / "scrape_all.log", "w", encoding="utf-8")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = _Tee(original_stdout, log_file)
    sys.stderr = _Tee(original_stderr, log_file)

    try:
        _main_inner()
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()


def _main_inner():
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

    # Load mapped domains (may not exist if user only has custom pages)
    mapped = {}
    if args.input.exists():
        mapped = load_mapped_pages(args.input)

    # Load custom pages from custom_pages.json
    custom = load_custom_pages()

    if not mapped and not custom:
        print("Nothing to scrape.")
        print("Run `python map.py` to discover domain URLs,")
        print("or `python custom_pages.py add <url>` to add a custom page.")
        sys.exit(1)

    if mapped:
        total_urls = sum(len(urls) for urls in mapped.values())
        print(f"Loaded {len(mapped)} domain(s) with {total_urls} total URLs.")
    if custom:
        print(f"Loaded {len(custom)} custom page(s).")

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
        # Phase 1: scrape mapped domains in batches
        if mapped:
            for i, (domain, urls) in enumerate(mapped.items(), 1):
                if args.max_pages:
                    urls = urls[:args.max_pages]

                print(f"[{i}/{len(mapped)}] Scraping {domain} ({len(urls)} pages)...")

                try:
                    scraped, unchanged, errors = scrape_domain(
                        domain, urls, api_url, args.output_dir,
                    )
                    total_scraped += scraped
                    total_errors += errors

                    print(f"  Total: Scraped {scraped} | Unchanged: {unchanged} | Errors: {errors}\n")

                except Exception as exc:
                    print(f"  Failed: {exc}\n")
                    total_errors += 1

        # Phase 2: scrape custom pages individually with force_refresh
        if custom:
            print(f"\n--- Custom Pages ({len(custom)}) ---\n")
            cp_scraped, cp_errors = scrape_custom_pages(
                custom, api_url, args.output_dir,
            )
            total_scraped += cp_scraped
            total_errors += cp_errors

        print(f"\n=== Scraping Complete ===")
        if mapped:
            print(f"Domains processed: {len(mapped)}")
        if custom:
            print(f"Custom pages processed: {len(custom)}")
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
