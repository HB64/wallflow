"""
db.py

SQLite-opslag voor WallFlow.

Houdt per wallpaper bij:
- wallhaven_id   : uniek ID van Wallhaven (voorkomt duplicaten, ook na rotatie)
- filename       : bestandsnaam in /wallpapers
- extension      : bestandsextensie
- downloaded_at  : wanneer het bestand is gedownload
- last_known_atime : laatst gemeten "last accessed" tijd van het bestand
  (LET OP: dit is bestandssysteem-atime, en dus ook "vals" te triggeren door
  bijv. een Windows-diavoorstelling die het bestand periodiek leest zonder dat
  er bewust naar gekeken wordt. Wordt om die reden niet meer gebruikt voor
  rotatiebeslissingen - alleen last_shown_at telt daarvoor nog echt.)
- last_shown_at  : wanneer de Android-app expliciet meldde dat deze wallpaper
  daadwerkelijk als achtergrond getoond is (via POST /wallpapers/<naam>/seen).
  Dit is de betrouwbare "bewust gezien"-graadmeter voor rotatie.
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
    last_shown_at TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);
"""


def _migrate(conn: sqlite3.Connection):
    """Voegt last_shown_at toe aan een bestaande database van vóór deze
    kolom bestond. ALTER TABLE ADD COLUMN faalt als de kolom er al is -
    dat wordt hier stilzwijgend genegeerd."""
    try:
        conn.execute("ALTER TABLE wallpapers ADD COLUMN last_shown_at TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # kolom bestaat al


def init_db(path: str = DATABASE_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    _migrate(conn)
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


def get_wallpaper_by_filename(conn: sqlite3.Connection, filename: str):
    """Zoekt op bestandsnaam i.p.v. wallhaven_id - handig voor endpoints die,
    net als /wallpapers/<naam>, alleen de bestandsnaam kennen."""
    return conn.execute(
        "SELECT * FROM wallpapers WHERE filename = ?", (filename,)
    ).fetchone()


def mark_shown(conn: sqlite3.Connection, filename: str) -> bool:
    """Zet last_shown_at op nu, voor de wallpaper met deze bestandsnaam.
    Wordt aangeroepen door de Android-app zodra een achtergrond daadwerkelijk
    getoond wordt - dit is de betrouwbare "bewust gezien"-melding voor
    rotatiebeslissingen (zie main.py: check_rotation). True als het bestand
    bekend was, False als niet (bijv. al geroteerd of onbekende naam)."""
    now = datetime.now().isoformat()
    cursor = conn.execute(
        "UPDATE wallpapers SET last_shown_at = ? WHERE filename = ?",
        (now, filename),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_rotated(conn: sqlite3.Connection, wallhaven_id: str):
    conn.execute(
        "UPDATE wallpapers SET status = 'rotated' WHERE wallhaven_id = ?",
        (wallhaven_id,),
    )
    conn.commit()
