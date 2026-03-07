import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path(__file__).with_name("worker_state.db")


# Open the shared SQLite database and ensure metadata table exists.
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata_store (
            domain TEXT NOT NULL,
            url TEXT NOT NULL,
            pack_hash TEXT,
            etag TEXT,
            last_modified TEXT,
            text_hash TEXT,
            last_checked_at REAL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (domain, url)
        )
        """
    )
    conn.commit()
    return conn


# Read stored version metadata for a specific page.
def get_page_metadata(domain: str, url: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT domain, url, pack_hash, etag, last_modified, text_hash, last_checked_at, updated_at
            FROM metadata_store
            WHERE domain = ? AND url = ?
            """,
            (domain, url),
        ).fetchone()

    if not row:
        return None

    return dict(row)


# Insert or update the latest validators/hash info for a page.
def upsert_page_metadata(
    domain: str,
    url: str,
    *,
    pack_hash: Optional[str],
    etag: Optional[str],
    last_modified: Optional[str],
    text_hash: Optional[str],
    last_checked_at: float,
) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO metadata_store (
                domain, url, pack_hash, etag, last_modified, text_hash, last_checked_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain, url) DO UPDATE SET
                pack_hash = excluded.pack_hash,
                etag = excluded.etag,
                last_modified = excluded.last_modified,
                text_hash = excluded.text_hash,
                last_checked_at = excluded.last_checked_at,
                updated_at = excluded.updated_at
            """,
            (domain, url, pack_hash, etag, last_modified, text_hash, last_checked_at, now),
        )
        conn.commit()
