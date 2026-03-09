# map.py — Reads domains from the extension's SQLite DB, clears old mappings,
# and runs the mapper on every collected domain to produce a fresh mapped_pages.json.
# Usage: python map.py
#        python map.py --max-pages 100 --delay 0.5

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# The mapper uses relative imports (from batch_workers import ...) so it
# needs its own directory on sys.path.
sys.path.insert(0, str(PROJECT_ROOT / "mapper"))

from mapper import map_domains_batch  # noqa: E402


# Looks for local_benefits.db in native_host/ first, then the project root.
def find_db():
    candidates = [
        PROJECT_ROOT / "native_host" / "local_benefits.db",
        PROJECT_ROOT / "local_benefits.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


# Pulls all unique domain values the extension has stored in web_history.
def read_domains(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT DISTINCT value FROM web_history WHERE kind = 'domain'"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


# Turns a bare domain like "utrgv.edu" into "https://utrgv.edu".
# Doesn't force www because the DB has subdomains like my.utrgv.edu too.
def domain_to_url(bare):
    bare = bare.strip()
    if bare.startswith("http://") or bare.startswith("https://"):
        return bare
    return f"https://{bare}"


def main():
    parser = argparse.ArgumentParser(description="Map domains collected by the browser extension.")
    parser.add_argument("--db", type=Path, default=None, help="Path to local_benefits.db")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "mapped_pages.json",
                        help="Output path for mapped_pages.json")
    parser.add_argument("--max-pages", type=int, default=500, help="Max pages to crawl per domain")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests in seconds")
    args = parser.parse_args()

    print("=== LPBD Domain Mapper ===\n")

    db_path = args.db or find_db()
    if not db_path or not db_path.exists():
        print("Error: local_benefits.db not found.")
        print("The browser extension hasn't collected any domains yet.")
        print("Browse some .edu/.gov sites with the extension active first.")
        sys.exit(1)

    print(f"Reading domains from {db_path}...")
    domains = read_domains(db_path)

    if not domains:
        print("No domains found in the database.")
        print("Browse some .edu/.gov sites with the extension active first.")
        sys.exit(1)

    print(f"Found {len(domains)} domain(s): {', '.join(domains)}\n")

    urls = [domain_to_url(d) for d in domains]
    print("URLs to map:")
    for url in urls:
        print(f"  - {url}")
    print()

    if args.output.exists():
        args.output.unlink()
        print(f"Cleared old {args.output.name}\n")

    print(f"Mapping with max_pages={args.max_pages}, delay={args.delay}s ...\n")
    map_domains_batch(
        domains=urls,
        include_subdomains=True,
        workers=1,
        max_pages=args.max_pages,
        delay=args.delay,
        output_path=args.output,
    )

    if args.output.exists():
        with open(args.output) as f:
            data = json.load(f)
        total_urls = sum(
            len(d.get("urls", [])) for d in data.get("domains", {}).values()
        )
        print(f"\n=== Mapping Complete ===")
        print(f"Domains mapped: {data.get('domain_count', 0)}")
        print(f"Total URLs discovered: {total_urls}")
        print(f"Output: {args.output}")
    else:
        print("\nWarning: No output file was produced.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
