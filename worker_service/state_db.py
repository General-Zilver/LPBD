import os
import sqlite3
import tempfile
from pathlib import Path

DB_FILE_NAME = "worker_state.db"
OVERRIDE_ENV = "LPBD_WORKER_DB"


def _directory_is_writable(base_dir: Path) -> bool:
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    probe = base_dir / ".lpbd_write_probe.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _sqlite_path_is_writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    try:
        conn = sqlite3.connect(path)
        try:
            # Fast writeability probe with no persistent data changes.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def _candidate_paths() -> list[Path]:
    candidates = []

    override = os.getenv(OVERRIDE_ENV, "").strip()
    if override:
        candidates.append(Path(override).expanduser())

    # Prefer temp dir first; it's usually writable even in managed/synced folders.
    candidates.append(Path(tempfile.gettempdir()) / "LPBD" / DB_FILE_NAME)

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "LPBD" / DB_FILE_NAME)

    home = Path.home()
    candidates.append(home / "AppData" / "Local" / "LPBD" / DB_FILE_NAME)
    return candidates


def get_worker_db_path() -> Path:
    for db_path in _candidate_paths():
        if not _directory_is_writable(db_path.parent):
            continue
        if _sqlite_path_is_writable(db_path):
            return db_path

    # Last-resort fallback if all preferred writable locations fail.
    return Path(DB_FILE_NAME).resolve()
