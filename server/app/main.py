from datetime import datetime, timedelta
from pathlib import Path
import time
import yaml
import requests
import schedule

import db
import httpserver
import settings_store
from wallhaven import WallhavenClient

CONFIG_FILE = "/config/config.yaml"

LOG_DIR = Path("/logs")
LOG_FILE = LOG_DIR / "wallflow.log"

WALLPAPER_DIR = Path("/wallpapers")

DEFAULT_MAX_WALLPAPERS = 100
DEFAULT_MIN_DWELL_DAYS = 3        # bestand blijft altijd minimaal dit aantal dagen met rust
DEFAULT_MAX_RETENTION_DAYS = 30   # vangnet: forceer rotatie als atime-detectie niet blijkt te werken
DEFAULT_CHECK_INTERVAL_HOURS = 24  # laag houden i.v.m. netwerkbelasting
DEFAULT_HTTP_PORT = 8080          # voor de screensaver-app (Android TV e.d.)
ATIME_BUFFER_MINUTES = 5          # marge tegen ruis vlak na het downloaden
SEARCH_DELAY_SECONDS = 1.5        # pauze tussen zoekopdrachten, tegen Wallhaven's rate limit


def log(message: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"

    print(line, flush=True)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_wallpapers():
    WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)

    files = []

    for ext in ("*.jpg", "*.jpeg", "*.png"):
        files.extend(WALLPAPER_DIR.glob(ext))

    return sorted(files)


def check_rotation(conn, min_dwell_days: int, max_retention_days: int):
    """
    Bepaalt welke wallpapers geroteerd (verwijderd + vervangen) mogen worden.

    Een wallpaper komt in aanmerking als:
    - hij minstens min_dwell_days oud is (vangnet, ongeacht atime), EN
    - de atime na de downloaddatum ligt (dus aantoonbaar geopend/getoond),
      OF hij ouder is dan max_retention_days (vangnet als atime-tracking
      niet blijkt te werken op deze share).
    """
    now = datetime.now()
    min_dwell = timedelta(days=min_dwell_days)
    max_retention = timedelta(days=max_retention_days)
    atime_buffer = timedelta(minutes=ATIME_BUFFER_MINUTES)

    rotatable_ids = []

    for row in db.get_active_wallpapers(conn):
        file_path = WALLPAPER_DIR / row["filename"]

        if not file_path.exists():
            # Handmatig verwijderd of anderszins verdwenen -> opschonen in db.
            db.mark_rotated(conn, row["wallhaven_id"])
            log(f"Bestand ontbreekt, db opgeschoond: {row['filename']}")
            continue

        downloaded_at = datetime.fromisoformat(row["downloaded_at"])
        age = now - downloaded_at

        if age < min_dwell:
            continue  # nog te vers, sowieso met rust laten

        atime = datetime.fromtimestamp(file_path.stat().st_atime)
        db.update_atime(conn, row["wallhaven_id"], atime.isoformat())

        seen = atime > (downloaded_at + atime_buffer)
        expired = age > max_retention

        if seen or expired:
            reason = "gezien (atime)" if seen else "max. bewaartermijn bereikt"
            log(f"Wallpaper {row['filename']} komt in aanmerking voor rotatie ({reason})")
            rotatable_ids.append(row["wallhaven_id"])

    return rotatable_ids


def rotate_wallpaper(conn, wallhaven_id: str):
    row = db.get_wallpaper(conn, wallhaven_id)

    if row is None:
        return

    file_path = WALLPAPER_DIR / row["filename"]
    file_path.unlink(missing_ok=True)

    db.mark_rotated(conn, wallhaven_id)
    log(f"Verwijderd: {row['filename']}")


def fill_wallpapers(client: WallhavenClient, conn, needed: int, max_attempts: int = 80):
    """Downloadt tot 'needed' nieuwe, nog niet eerder geziene wallpapers.

    Elke aanroep van search() gebruikt een nieuwe willekeurige tag, dus een
    leeg resultaat betekent alleen dat DIE ene tag/pagina niks opleverde -
    niet dat er niks meer te vinden is. Daarom bij een leeg resultaat gewoon
    doorgaan naar de volgende poging (nieuwe tag), in plaats van meteen
    stoppen.

    Tussen elke zoekopdracht zit een korte pauze (SEARCH_DELAY_SECONDS) om
    Wallhaven's rate limit te respecteren. Bij een 429 (rate limit bereikt)
    stopt deze cyclus meteen i.p.v. door te blijven proberen - dat lost het
    toch niet op en vult alleen het logbestand.
    """
    downloaded = 0
    attempt = 0

    while downloaded < needed and attempt < max_attempts:
        attempt += 1

        try:
            results = client.search(page=1)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 429:
                log(
                    f"Wallhaven rate limit bereikt (poging {attempt}) - "
                    "cyclus wordt hier gestopt, volgende poging bij de eerstvolgende cyclus."
                )
                break
            # Bewust geen {e} loggen: de foutmelding van requests bevat de
            # volledige request-URL inclusief de apikey.
            log(f"Zoeken op Wallhaven mislukt (poging {attempt}): HTTP-fout (status {status})")
            time.sleep(SEARCH_DELAY_SECONDS)
            continue
        except requests.RequestException:
            log(f"Zoeken op Wallhaven mislukt (poging {attempt}): verbindingsfout")
            time.sleep(SEARCH_DELAY_SECONDS)
            continue

        if not results:
            log(f"Geen (bruikbare) resultaten bij poging {attempt}, volgende tag proberen.")
            time.sleep(SEARCH_DELAY_SECONDS)
            continue

        for wp in results:
            if downloaded >= needed:
                break

            if db.is_known(conn, wp["id"]):
                continue  # al eerder gedownload (actief of al geroteerd)

            try:
                path = client.download(wp, WALLPAPER_DIR)
                db.add_wallpaper(conn, wp["id"], path.name, wp["extension"])
                downloaded += 1
                log(f"Gedownload: {path.name}")
            except requests.RequestException:
                log(f"Download mislukt voor {wp['id']}: verbindingsfout")

        time.sleep(SEARCH_DELAY_SECONDS)

    return downloaded


def run_cycle(client: WallhavenClient, conn, settings: dict, rotation_defaults: dict):
    log("Rotatiecyclus gestart.")

    # Bij elke cyclus vers inlezen (i.p.v. de waarden van bij het opstarten),
    # zodat een wijziging via /ui direct bij de eerstvolgende cyclus actief
    # is, zonder herstart van de container.
    rotation = settings_store.get_settings(rotation_defaults)

    rotatable = check_rotation(
        conn,
        min_dwell_days=rotation["min_dwell_days"],
        max_retention_days=rotation["max_retention_days"],
    )

    for wallhaven_id in rotatable:
        rotate_wallpaper(conn, wallhaven_id)

    needed = settings["max_wallpapers"] - db.count_active(conn)

    if needed > 0:
        # Als er in 1 cyclus veel wallpapers tegelijk over de min_dwell-grens
        # komen (en dus geroteerd worden), moet er in diezelfde cyclus ook
        # genoeg ruimte zijn om ze weer aan te vullen - anders daalt het
        # actieve aantal per saldo. 200 pogingen bleek te veel (rate limit),
        # dus nu een lager aantal gecombineerd met een pauze tussen pogingen.
        fill_wallpapers(client, conn, needed)

    log(
        f"Cyclus klaar. Actieve wallpapers: {db.count_active(conn)}/{settings['max_wallpapers']} "
        f"(min_dwell={rotation['min_dwell_days']}d, max_retention={rotation['max_retention_days']}d)"
    )


def scheduled_job(client: WallhavenClient, conn, settings: dict, rotation_defaults: dict):
    """Wrapper rond run_cycle die de scheduler blijft draaien, ook na een fout."""
    try:
        run_cycle(client, conn, settings, rotation_defaults)
    except Exception as e:
        log(f"Onverwachte fout tijdens cyclus: {e}")


if __name__ == "__main__":

    config = load_config()

    wallflow_config = config.get("wallflow", {})
    settings = {
        "max_wallpapers": wallflow_config.get("max_wallpapers", DEFAULT_MAX_WALLPAPERS),
        "min_dwell_days": wallflow_config.get("min_dwell_days", DEFAULT_MIN_DWELL_DAYS),
        "max_retention_days": wallflow_config.get("max_retention_days", DEFAULT_MAX_RETENTION_DAYS),
        "check_interval_hours": wallflow_config.get("check_interval_hours", DEFAULT_CHECK_INTERVAL_HOURS),
        "http_port": wallflow_config.get("http_port", DEFAULT_HTTP_PORT),
    }

    # Startwaarden voor min_dwell_days/max_retention_days komen uit
    # config.yaml. Ze worden meteen weggeschreven naar settings.json (als dat
    # nog niet bestaat), zodat het gedrag bij deze upgrade niet verandert -
    # pas een wijziging via /ui wijkt daarna af van config.yaml.
    rotation_defaults = {
        "min_dwell_days": settings["min_dwell_days"],
        "max_retention_days": settings["max_retention_days"],
    }
    settings_store.get_settings(rotation_defaults)

    log("========================================")
    log("WallFlow starting...")
    log("Configuration loaded.")

    WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
    httpserver.start_server(WALLPAPER_DIR, port=settings["http_port"], rotation_defaults=rotation_defaults)
    log(f"HTTP-server gestart op poort {settings['http_port']} (/wallpapers).")

    client = WallhavenClient(
        api_key=config["wallhaven"]["api_key"]
    )

    if client.test_connection():
        log("Wallhaven connection successful.")
    else:
        log("Wallhaven connection failed (blijft periodiek opnieuw proberen).")

    with db.get_connection() as conn:
        wallpapers = get_wallpapers()
        log(f"Wallpapers aanwezig op schijf: {len(wallpapers)}")
        log(f"Actief volgens database: {db.count_active(conn)}/{settings['max_wallpapers']}")

        # Direct 1 cyclus bij opstarten, daarna periodiek.
        scheduled_job(client, conn, settings, rotation_defaults)

        schedule.every(settings["check_interval_hours"]).hours.do(
            scheduled_job, client, conn, settings, rotation_defaults
        )

        log(f"Volgende checks elke {settings['check_interval_hours']} uur.")
        log("Waiting for jobs...")
        log("========================================")

        while True:
            schedule.run_pending()
            time.sleep(60)
