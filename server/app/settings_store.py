"""
settings_store.py

Beheert instelbare parameters in /config/settings.json, zodat ze via de
HTTP-server (/settings) aangepast kunnen worden zonder rebuild of herstart
van de container.

main.py en wallhaven.py lezen deze waarden telkens opnieuw, dus een wijziging
via de webpagina (/ui) is direct actief bij de eerstvolgende cyclus/zoek-
opdracht.

Bij eerste gebruik (bestand bestaat nog niet) wordt het bestand aangemaakt
met de standaardwaarden hieronder. Voor min_dwell_days/max_retention_days
geeft main.py bij het opstarten de waarden uit config.yaml door als
'defaults', zodat het gedrag niet stilzwijgend verandert bij het invoeren
van deze feature - pas als je zelf iets aanpast via /ui wijkt het af van
config.yaml. Andere velden (zoals require_trusted_source) hebben geen
config.yaml-equivalent en gebruiken altijd hun eigen standaardwaarde hieronder
totdat je ze zelf aanpast.
"""

import json
import threading
from pathlib import Path

SETTINGS_FILE = Path("/config/settings.json")

_lock = threading.Lock()

# Per veld: het type (bepaalt validatie) en de standaardwaarde. Voor "int"
# ook de toegestane grenzen (in dagen).
FIELDS = {
    "min_dwell_days": {"type": "int", "min": 1, "max": 90, "default": 3},
    "max_retention_days": {"type": "int", "min": 1, "max": 365, "default": 30},
    "require_trusted_source": {"type": "bool", "default": False},
}


def _default_for(key: str, defaults: dict):
    if defaults and key in defaults:
        return defaults[key]
    return FIELDS[key]["default"]


def _ensure_file(defaults: dict):
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _write_unlocked({key: _default_for(key, defaults) for key in FIELDS})


def _read_unlocked(defaults: dict):
    _ensure_file(defaults)
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in FIELDS:
        data.setdefault(key, _default_for(key, defaults))
    return data


def _write_unlocked(data):
    tmp = SETTINGS_FILE.with_suffix(".json.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(SETTINGS_FILE)


def _coerce_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def get_settings(defaults: dict = None) -> dict:
    """
    Retourneert de huidige instellingen zoals ze nu op schijf staan.
    'defaults' wordt alleen gebruikt om het bestand te initialiseren bij de
    allereerste aanroep, en alleen voor velden die er expliciet in staan -
    voor de rest geldt het standaardwaarde uit FIELDS.
    """
    with _lock:
        data = _read_unlocked(defaults)
        return {key: data[key] for key in FIELDS}


def update_settings(updates: dict, defaults: dict = None) -> dict:
    """
    Werkt 1 of meer instellingen bij. Onbekende velden worden genegeerd.
    Raised ValueError bij een ongeldige of niet-toegestane waarde.
    """
    with _lock:
        data = _read_unlocked(defaults)

        for key, value in updates.items():
            if key not in FIELDS:
                continue

            spec = FIELDS[key]

            if spec["type"] == "bool":
                value = _coerce_bool(value)
            else:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"'{key}' moet een geheel getal zijn")

                low, high = spec["min"], spec["max"]
                if not (low <= value <= high):
                    raise ValueError(f"'{key}' moet tussen {low} en {high} liggen")

            data[key] = value

        _write_unlocked(data)
        return {key: data[key] for key in FIELDS}
