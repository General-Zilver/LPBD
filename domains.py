# domains.py — Quick way to see what's in the native host DB and clear it.
# Usage: python domains.py              (lists all domains)
#        python domains.py --clear      (deletes all rows and confirms)
#        python domains.py --clear-domains  (deletes only domain rows)

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


# Same lookup as map.py -- checks native_host/ first, then project root.
def find_db():
    candidates = [
        PROJECT_ROOT / "native_host" / "local_benefits.db",
        PROJECT_ROOT / "local_benefits.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def list_domains(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT DISTINCT value FROM web_history WHERE kind = 'domain'"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def list_all(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT kind, value, seen_at FROM web_history ORDER BY seen_at DESC"
        ).fetchall()
        return rows
    finally:
        conn.close()


def clear_all(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM web_history").fetchone()[0]
        conn.execute("DELETE FROM web_history")
        conn.commit()
        return count
    finally:
        conn.close()


def clear_domains(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM web_history WHERE kind = 'domain'"
        ).fetchone()[0]
        conn.execute("DELETE FROM web_history WHERE kind = 'domain'")
        conn.commit()
        return count
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="View or clear the native host database.")
    parser.add_argument("--db", type=Path, default=None, help="Path to local_benefits.db")
    parser.add_argument("--all", action="store_true", help="Show all rows, not just domains")
    parser.add_argument("--clear", action="store_true", help="Delete ALL rows from web_history")
    parser.add_argument("--clear-domains", action="store_true",
                        help="Delete only domain rows from web_history")
    args = parser.parse_args()

    db_path = args.db or find_db()
    if not db_path or not db_path.exists():
        print("No native host database found (browser extension hasn't stored anything yet).\n")
        # Still show custom pages even without a DB
        from custom_pages import load_custom_pages
        custom = load_custom_pages()
        if custom:
            print(f"Custom pages ({len(custom)}):\n")
            for p in sorted(custom, key=lambda x: x["url"]):
                status = p["status"]
                scraped = p.get("last_scraped") or "never"
                print(f"  [{status}] {p['url']}  (last scraped: {scraped})")
        else:
            print("No custom pages tracked either.")
            print("Add one with: python custom_pages.py add <url>")
        return

    print(f"Database: {db_path}\n")

    if args.clear:
        count = clear_all(db_path)
        print(f"Deleted {count} row(s) from web_history.")
        return

    if args.clear_domains:
        count = clear_domains(db_path)
        print(f"Deleted {count} domain row(s) from web_history.")
        return

    if args.all:
        rows = list_all(db_path)
        if not rows:
            print("Database is empty.")
            return
        print(f"All entries ({len(rows)} rows):\n")
        for kind, value, seen_at in rows:
            print(f"  [{kind}] {value}  (seen: {seen_at})")
        return

    domains = list_domains(db_path)
    if not domains:
        print("No domains found.")
    else:
        print(f"Domains ({len(domains)}):\n")
        for d in sorted(domains):
            print(f"  {d}")

    # Also show custom pages from custom_pages.json
    from custom_pages import load_custom_pages
    custom = load_custom_pages()
    if custom:
        print(f"\nCustom pages ({len(custom)}):\n")
        for p in sorted(custom, key=lambda x: x["url"]):
            status = p["status"]
            scraped = p.get("last_scraped") or "never"
            print(f"  [{status}] {p['url']}  (last scraped: {scraped})")


if __name__ == "__main__":
    main()
