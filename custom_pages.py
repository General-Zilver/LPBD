# custom_pages.py -- Manages custom pages (user-added URLs) for scraping.
# These are individual URLs the user wants monitored, separate from the
# domain-based crawler flow. Stored in custom_pages.json.
# Usage: python custom_pages.py add https://example.com/aid
#        python custom_pages.py remove https://example.com/aid
#        python custom_pages.py list

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
CUSTOM_PAGES_FILE = PROJECT_ROOT / "custom_pages.json"


# Loads custom pages from disk. Returns [] if file doesn't exist.
# On first call, auto-migrates any old kind='page' entries from the
# native host DB so nothing gets lost.
def load_custom_pages():
    _migrate_from_db()
    if not CUSTOM_PAGES_FILE.exists():
        return []
    data = json.loads(CUSTOM_PAGES_FILE.read_text(encoding="utf-8"))
    return data.get("pages", [])


# Writes the pages list to custom_pages.json.
def save_custom_pages(pages):
    CUSTOM_PAGES_FILE.write_text(
        json.dumps({"pages": pages}, indent=2),
        encoding="utf-8",
    )


# Adds a URL if it isn't already tracked.
def add_page(url):
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"

    pages = load_custom_pages()
    if any(p["url"] == url for p in pages):
        print(f"Already tracked: {url}")
        return

    pages.append({
        "url": url,
        "added_at": datetime.now().isoformat(),
        "last_scraped": None,
        "status": "pending",
    })
    save_custom_pages(pages)
    print(f"Added: {url}")


# Removes a URL by exact match.
def remove_page(url):
    url = url.strip()
    pages = load_custom_pages()
    before = len(pages)
    pages = [p for p in pages if p["url"] != url]
    if len(pages) == before:
        print(f"Not found: {url}")
        return
    save_custom_pages(pages)
    print(f"Removed: {url}")


# Prints all tracked custom pages with status and timestamps.
def list_pages():
    pages = load_custom_pages()
    if not pages:
        print("No custom pages tracked.")
        print(f"Add one with: python custom_pages.py add <url>")
        return

    print(f"Custom pages ({len(pages)}):\n")
    for p in pages:
        scraped = p.get("last_scraped") or "never"
        print(f"  [{p['status']}] {p['url']}")
        print(f"         added: {p['added_at']}  |  last scraped: {scraped}")


# Updates a single page's status and optionally its last_scraped time.
def update_page_status(url, status, scraped_at=None):
    pages = load_custom_pages()
    for p in pages:
        if p["url"] == url:
            p["status"] = status
            if scraped_at:
                p["last_scraped"] = scraped_at
            break
    save_custom_pages(pages)


# One-time import of kind='page' rows from the native host DB.
# Only runs if custom_pages.json doesn't exist yet, so it won't
# overwrite anything the user already set up manually.
def _migrate_from_db():
    if CUSTOM_PAGES_FILE.exists():
        return

    db_candidates = [
        PROJECT_ROOT / "native_host" / "local_benefits.db",
        PROJECT_ROOT / "local_benefits.db",
    ]
    for db_path in db_candidates:
        if db_path.exists():
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            try:
                rows = conn.execute(
                    "SELECT DISTINCT value FROM web_history WHERE kind = 'page'"
                ).fetchall()
                if rows:
                    pages = [{
                        "url": row[0],
                        "added_at": datetime.now().isoformat(),
                        "last_scraped": None,
                        "status": "pending",
                    } for row in rows]
                    save_custom_pages(pages)
                    print(f"Migrated {len(pages)} custom page(s) from native host DB.")
            finally:
                conn.close()
            return


def main():
    parser = argparse.ArgumentParser(
        description="Manage custom pages for scraping."
    )
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="Add a custom page URL")
    add_p.add_argument("url", help="Full URL to track")

    rm_p = sub.add_parser("remove", help="Remove a custom page URL")
    rm_p.add_argument("url", help="URL to remove")

    sub.add_parser("list", help="List all custom pages")

    args = parser.parse_args()

    if args.command == "add":
        add_page(args.url)
    elif args.command == "remove":
        remove_page(args.url)
    elif args.command == "list":
        list_pages()
    else:
        list_pages()


if __name__ == "__main__":
    main()
