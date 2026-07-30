"""
tags_store.py

Beheert de include/exclude-tags in /config/tags.json, zodat ze via de
HTTP-server aangepast kunnen worden zonder dat er een nieuwe image gebouwd
of de container herstart hoeft te worden.

wallhaven.py leest deze tags bij elke zoekopdracht opnieuw, dus een
wijziging via de HTTP-server is direct bij de eerstvolgende zoekactie actief.

Bij eerste gebruik (bestand bestaat nog niet) wordt het bestand aangemaakt
met de huidige standaardtags, zodat het gedrag niet verandert totdat je
zelf iets toevoegt of verwijdert.
"""

import json
import threading
from pathlib import Path

TAGS_FILE = Path("/config/tags.json")

_lock = threading.Lock()

DEFAULT_INCLUDE_TAGS = [
    "mountains",
    "hdr",
    "forests",
    "lakes",
    "rivers",
    "waterfalls",
    "valleys",
    "nature",
    "landscape",
    "national parks",
    "space",
    "galaxy",
    "stars",
    "night sky",
]

DEFAULT_EXCLUDE_TAGS = [
    "people",
    "person",
    "persons",
    "portrait",
    "girl",
    "boy",
    "man",
    "woman",
    "anime",
    "snow",
    "autumn",
    "winter",
    "bridges",
    "buildings",
    "roads",
    "cars",
    "trucks",
    "bikes",
    "motorcycles",
    "drawings",
    "animated",
    "houses",
    "industry",
    "man made",
    "cgi",
    "3d render",
    "digital art",
    "concept art",
    "video game",
    "screenshot",
    "movie",
    "film",
    "fantasy art",
]


def _ensure_file():
    if not TAGS_FILE.exists():
        TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _write_unlocked({"include": DEFAULT_INCLUDE_TAGS, "exclude": DEFAULT_EXCLUDE_TAGS})


def _read_unlocked():
    _ensure_file()
    with open(TAGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("include", [])
    data.setdefault("exclude", [])
    return data


def _write_unlocked(data):
    tmp = TAGS_FILE.with_suffix(".json.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(TAGS_FILE)


def get_tags():
    """Retourneert (include_tags, exclude_tags) zoals ze nu op schijf staan."""
    with _lock:
        data = _read_unlocked()
        return list(data["include"]), list(data["exclude"])


def add_tag(kind: str, tag: str):
    """Voegt een tag toe aan 'include' of 'exclude', indien nog niet aanwezig."""
    if kind not in ("include", "exclude"):
        raise ValueError("kind moet 'include' of 'exclude' zijn")

    tag = tag.strip()
    if not tag:
        raise ValueError("Lege tag")

    with _lock:
        data = _read_unlocked()
        if tag not in data[kind]:
            data[kind].append(tag)
            _write_unlocked(data)
        return list(data["include"]), list(data["exclude"])


def remove_tag(kind: str, tag: str) -> bool:
    """Verwijdert een tag uit 'include' of 'exclude'. True als hij er stond."""
    if kind not in ("include", "exclude"):
        raise ValueError("kind moet 'include' of 'exclude' zijn")

    with _lock:
        data = _read_unlocked()
        if tag in data[kind]:
            data[kind].remove(tag)
            _write_unlocked(data)
            return True
        return False
