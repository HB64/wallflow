"""
db.py

SQLite-opslag voor WallFlow.

Houdt per wallpaper bij:
- wallhaven_id   : uniek ID van Wallhaven (voorkomt duplicaten, ook na rotatie)
- filename       : bestandsnaam in /wallpapers
- extension      : bestandsextensie
- downloaded_at  : wanneer het bestand is gedownload
- last_known_atime : laatst gemeten "last accessed" tijd van het bestand
- status         : 'active' (staat in /wallpapers) of 'rotated' (verwijderd)
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

DATABASE_FILE = "/database/wallflow.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallpapers (
    wallhaven_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    last_known_atime TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);
"""


def init_db(path: str = DATABASE_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


@contextmanager
def get_connection(path: str = DATABASE_FILE):
    conn = init_db(path)
    try:
        yield conn
    finally:
        conn.close()


def is_known(conn: sqlite3.Connection, wallhaven_id: str) -> bool:
    """True als dit ID ooit al gedownload is (active of rotated) -> voorkomt duplicaten."""
    row = conn.execute(
        "SELECT 1 FROM wallpapers WHERE wallhaven_id = ?", (wallhaven_id,)
    ).fetchone()
    return row is not None


def add_wallpaper(conn: sqlite3.Connection, wallhaven_id: str, filename: str, extension: str):
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO wallpapers (wallhaven_id, filename, extension, downloaded_at, last_known_atime, status)
        VALUES (?, ?, ?, ?, NULL, 'active')
        """,
        (wallhaven_id, filename, extension, now),
    )
    conn.commit()


def get_wallpaper(conn: sqlite3.Connection, wallhaven_id: str):
    return conn.execute(
        "SELECT * FROM wallpapers WHERE wallhaven_id = ?", (wallhaven_id,)
    ).fetchone()


def get_active_wallpapers(conn: sqlite3.Connection):
    """Alle wallpapers die momenteel in /wallpapers staan."""
    return conn.execute(
        "SELECT * FROM wallpapers WHERE status = 'active'"
    ).fetchall()


def count_active(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM wallpapers WHERE status = 'active'"
    ).fetchone()
    return row[0]


def update_atime(conn: sqlite3.Connection, wallhaven_id: str, atime_iso: str):
    conn.execute(
        "UPDATE wallpapers SET last_known_atime = ? WHERE wallhaven_id = ?",
        (atime_iso, wallhaven_id),
    )
    conn.commit()


def mark_rotated(conn: sqlite3.Connection, wallhaven_id: str):
    conn.execute(
        "UPDATE wallpapers SET status = 'rotated' WHERE wallhaven_id = ?",
        (wallhaven_id,),
    )
    conn.commit()
