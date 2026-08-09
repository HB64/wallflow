"""
settings_store.py

Beheert instelbare rotatie-parameters in /config/settings.json, zodat ze via
de HTTP-server (/settings) aangepast kunnen worden zonder rebuild of herstart
van de container.

main.py leest deze waarden bij elke cyclus opnieuw, dus een wijziging via de
webpagina (/ui) is direct bij de eerstvolgende cyclus actief.

Bij eerste gebruik (bestand bestaat nog niet) wordt het bestand aangemaakt
met de waarden die op dat moment uit config.yaml komen (zie main.py), zodat
het gedrag niet stilzwijgend verandert bij het invoeren van deze feature -
pas als je zelf iets aanpast via /ui wijkt het af van config.yaml.
"""

import json
import threading
from pathlib import Path

SETTINGS_FILE = Path("/config/settings.json")

_lock = threading.Lock()

# Toegestane instellingen, met hun grenzen (in dagen).
LIMITS = {
    "min_dwell_days": (1, 90),
    "max_retention_days": (1, 365),
}


def _ensure_file(defaults: dict):
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _write_unlocked({key: defaults[key] for key in LIMITS})


def _read_unlocked(defaults: dict):
    _ensure_file(defaults)
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in LIMITS:
        data.setdefault(key, defaults[key])
    return data


def _write_unlocked(data):
    tmp = SETTINGS_FILE.with_suffix(".json.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(SETTINGS_FILE)


def get_settings(defaults: dict) -> dict:
    """
    Retourneert de huidige instellingen zoals ze nu op schijf staan.
    'defaults' (uit config.yaml) wordt alleen gebruikt om het bestand te
    initialiseren bij de allereerste aanroep.
    """
    with _lock:
        data = _read_unlocked(defaults)
        return {key: data[key] for key in LIMITS}


def update_settings(updates: dict, defaults: dict) -> dict:
    """
    Werkt 1 of meer instellingen bij. Onbekende velden worden genegeerd.
    Raised ValueError bij een ongeldige of niet-toegestane waarde.
    """
    with _lock:
        data = _read_unlocked(defaults)

        for key, value in updates.items():
            if key not in LIMITS:
                continue

            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"'{key}' moet een geheel getal zijn")

            low, high = LIMITS[key]
            if not (low <= value <= high):
                raise ValueError(f"'{key}' moet tussen {low} en {high} liggen")

            data[key] = value

        _write_unlocked(data)
        return {key: data[key] for key in LIMITS}
