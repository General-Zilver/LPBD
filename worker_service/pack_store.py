import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).with_name("worker_state.db")


# Open the shared SQLite database and ensure the pack cache table exists.
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pack_store (
            domain TEXT PRIMARY KEY,
            pack_json TEXT NOT NULL,
            pack_hash TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS domain_lock (
            domain TEXT PRIMARY KEY,
            locked_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


# Compute the next Sunday 11:59:59 PM timestamp for weekly pack expiration.
def next_sunday_235959_timestamp(now_ts: float) -> float:
    now_dt = datetime.fromtimestamp(now_ts)
    days_until_sunday = 6 - now_dt.weekday()
    sunday = (now_dt + timedelta(days=days_until_sunday)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    if sunday.timestamp() < now_ts:
        sunday = sunday + timedelta(days=7)
    return sunday.timestamp()


# Remove expired weekly packs before handling new requests.
def purge_expired_packs(now_ts: Optional[float] = None) -> None:
    current = now_ts or time.time()
    with _connect() as conn:
        conn.execute("DELETE FROM pack_store WHERE expires_at < ?", (current,))
        conn.commit()


# Load a cached domain pack if it is still present in the shared store.
def get_pack(domain: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT domain, pack_json, pack_hash, fetched_at, expires_at FROM pack_store WHERE domain = ?",
            (domain,),
        ).fetchone()

    if not row:
        return None

    return {
        "domain": row["domain"],
        "pack": json.loads(row["pack_json"]),
        "pack_hash": row["pack_hash"],
        "fetched_at": row["fetched_at"],
        "expires_at": row["expires_at"],
    }


# Upsert the current weekly pack snapshot for a domain.
def save_pack(
    domain: str,
    pack_pages: List[Dict[str, Any]],
    pack_hash: str,
    fetched_at: float,
    expires_at: float,
) -> None:
    payload = json.dumps(pack_pages, ensure_ascii=True)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO pack_store (domain, pack_json, pack_hash, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                pack_json = excluded.pack_json,
                pack_hash = excluded.pack_hash,
                fetched_at = excluded.fetched_at,
                expires_at = excluded.expires_at
            """,
            (domain, payload, pack_hash, fetched_at, expires_at),
        )
        conn.commit()


# Acquire a short-lived domain rebuild lock to avoid duplicate pack rebuilds.
def acquire_domain_lock(domain: str, timeout_s: float = 15.0, poll_ms: int = 100) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with _connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO domain_lock (domain, locked_at) VALUES (?, ?)",
                    (domain, time.time()),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                pass
        time.sleep(max(1, poll_ms) / 1000.0)
    return False


# Release the domain rebuild lock after rebuilding or on failure.
def release_domain_lock(domain: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM domain_lock WHERE domain = ?", (domain,))
        conn.commit()
