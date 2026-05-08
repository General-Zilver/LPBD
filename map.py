# map.py — Reads domains from the extension's SQLite DB, clears old mappings,
# and runs the mapper on every collected domain to produce a fresh mapped_pages.json.
# Usage: python map.py
#        python map.py --max-pages 100 --delay 0.5

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent

# The mapper uses relative imports (from batch_workers import ...) so it
# needs its own directory on sys.path.
sys.path.insert(0, str(PROJECT_ROOT / "mapper"))

from mapper import map_domains_batch  # noqa: E402


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


# Canonicalizes collected hosts so www/non-www variants do not map twice.
def canonical_domain(value):
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        host = urlparse(raw).netloc
    else:
        host = raw.split("/", 1)[0]
    host = host.split("@")[-1].split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


# Pulls all unique canonical domain values the extension has stored in web_history.
def read_domains(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT DISTINCT value FROM web_history WHERE kind = 'domain'"
        ).fetchall()
        domains = {canonical_domain(row[0]) for row in rows}
        return sorted(d for d in domains if d)
    finally:
        conn.close()


def compact_domain_rows(db_path, domains):
    if not domains:
        return 0

    keep_values = set(domains)
    aliases = sorted({alias for d in domains for alias in (d, f"www.{d}")})
    placeholders = ",".join("?" for _ in aliases)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            f"""
            SELECT value, COUNT(value), MIN(seen_at), MAX(request_id)
            FROM web_history
            WHERE kind = 'domain' AND lower(value) IN ({placeholders})
            GROUP BY value
            """,
            aliases,
        ).fetchall()

        if not rows:
            return 0

        existing_count = sum(count for value, count, _seen_at, _request_id in rows if canonical_domain(value) in keep_values)
        conn.execute(
            f"DELETE FROM web_history WHERE kind = 'domain' AND lower(value) IN ({placeholders})",
            aliases,
        )
        for domain in sorted(keep_values):
            matching = [row for row in rows if canonical_domain(row[0]) == domain]
            if not matching:
                continue
            seen_at = min(row[2] for row in matching if row[2])
            request_id = next((row[3] for row in matching if row[3]), None)
            conn.execute(
                """
                INSERT INTO web_history (request_id, kind, value, seen_at)
                VALUES (?, 'domain', ?, ?)
                """,
                (request_id, domain, seen_at),
            )
        conn.commit()
        return max(0, existing_count - len(keep_values))
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
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = open(log_dir / "map.log", "w", encoding="utf-8")
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
    parser = argparse.ArgumentParser(description="Map domains collected by the browser extension.")
    parser.add_argument("--db", type=Path, default=None, help="Path to local_benefits.db")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "mapped_pages.json",
                        help="Output path for mapped_pages.json")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Max pages to crawl per domain (default: unlimited)")
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

    removed_duplicates = compact_domain_rows(db_path, domains)
    if removed_duplicates:
        print(f"Compacted {removed_duplicates} duplicate domain row(s) in {db_path.name}.")

    print(f"Found {len(domains)} domain(s): {', '.join(domains)}\n")

    urls = [domain_to_url(d) for d in domains]
    print("URLs to map:")
    for url in urls:
        print(f"  - {url}")
    print()

    if args.output.exists():
        args.output.unlink()
        print(f"Cleared old {args.output.name}\n")

    limit_display = args.max_pages if args.max_pages is not None else "unlimited"
    print(f"Mapping with max_pages={limit_display}, delay={args.delay}s ...\n")
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

        # Remove domains that produced 0 URLs from output and database
        if isinstance(data.get("domains"), dict):
            empty = [k for k, v in data["domains"].items() if len(v.get("urls", [])) == 0]
            for k in empty:
                del data["domains"][k]
            if empty:
                data["domain_count"] = len(data["domains"])
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                print(f"\nPruned {len(empty)} domain(s) with 0 URLs: {', '.join(empty)}")

                # Also remove them from the database so they are skipped next time
                bare_domains = [url.replace("https://", "").replace("http://", "") for url in empty]
                conn = sqlite3.connect(str(db_path))
                try:
                    conn.executemany(
                        "DELETE FROM web_history WHERE kind = 'domain' AND value = ?",
                        [(d,) for d in bare_domains],
                    )
                    conn.commit()
                    print(f"Removed {len(bare_domains)} empty domain(s) from {db_path.name}")
                finally:
                    conn.close()

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
