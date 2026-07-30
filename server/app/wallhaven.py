"""
wallhaven.py

Haalt wallpapers op van de Wallhaven API en downloadt ze.

De include/exclude-tags worden NIET meer hardcoded hier bewaard, maar per
zoekopdracht vers ingelezen via tags_store.py (/config/tags.json). Zo is een
tag toevoegen of verwijderen via de HTTP-server (/tags) direct actief, zonder
rebuild of herstart.
"""

from pathlib import Path
import random
import requests

import tags_store


class WallhavenClient:
    BASE_URL = "https://wallhaven.cc/api/v1/search"

    def __init__(self, api_key):
        self.api_key = api_key

        # Tags en 'categories' zeggen niets over illustratie vs. echte foto -
        # bepaalde kunst-/fanart-platforms leveren toch nog steeds resultaten
        # op binnen categorie "general". Op basis van de source-URL weren we
        # die alsnog, en geven we bekende goede fotografie-bronnen voorrang.
        self.blocked_sources = [
            "artstation.com",
            "pixiv.net",
            "deviantart.com",
            "x.com",
            "twitter.com",
            "behance.net",
        ]

        self.preferred_sources = [
            "reddit.com/r/earthporn",
        ]

    def _source_blocked(self, source: str) -> bool:
        source = (source or "").lower()
        return any(domain in source for domain in self.blocked_sources)

    def _source_preferred(self, source: str) -> bool:
        source = (source or "").lower()
        return any(domain in source for domain in self.preferred_sources)

    @staticmethod
    def _quote_if_multiword(tag: str) -> str:
        """
        Wallhaven behandelt een spatie in 'q' als scheiding tussen losse
        verplichte termen. Een tag als "man made" zou zonder quotes
        uiteenvallen in -man (uitsluiten) + made (een losse, VERPLICHTE term)
        - met als gevolg vrijwel altijd 0 resultaten. Tags met een spatie
        moeten dus tussen aanhalingstekens.
        """
        return f'"{tag}"' if " " in tag else tag

    def _build_query(self, tag: str, exclude_tags):
        """
        Wallhaven behandelt spaties in 'q' als AND: hoe meer termen, hoe
        kleiner de kans dat 1 afbeelding ze allemaal heeft (met alle 12
        include-tags tegelijk kom je op 0 resultaten). Daarom per zoekopdracht
        maar 1 include-tag combineren met de excludes.
        """
        tag_str = self._quote_if_multiword(tag)
        exclude = " ".join(f"-{self._quote_if_multiword(t)}" for t in exclude_tags)
        return f"{tag_str} {exclude}"

    def test_connection(self):
        """Checkt of de API key geldig is en Wallhaven bereikbaar is."""
        try:
            response = requests.get(
                self.BASE_URL,
                params={"apikey": self.api_key, "page": 1},
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def search(self, page=1, sorting="random", purity="100"):
        include_tags, exclude_tags = tags_store.get_tags()
        tag = random.choice(include_tags)

        params = {
            "apikey": self.api_key,
            "q": self._build_query(tag, exclude_tags),
            "sorting": sorting,
            "purity": purity,
            "page": page,
            "atleast": "3840x2160",
            # Categorie is los van tags: "100" = alleen general (geen anime/
            # people-categorie), zodat tekeningen/illustraties niet via een
            # niet-getagde anime-afbeelding alsnog binnenkomen.
            "categories": "100",
        }

        response = requests.get(self.BASE_URL, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        wallpapers = []

        for item in data.get("data", []):
            source = item.get("source", "")

            if self._source_blocked(source):
                continue

            # Portret (hoger dan breed) is ongeschikt als desktop/tv-achter-
            # grond, ongeacht de 'portrait'-tag (die gaat over de inhoud, niet
            # de orientatie). Bredere/vierkante afbeeldingen blijven wel goed.
            if item["dimension_y"] > item["dimension_x"]:
                continue

            path = item["path"]

            wallpapers.append(
                {
                    "id": item["id"],
                    "url": path,
                    "extension": Path(path).suffix.lower().lstrip("."),
                    "preferred": self._source_preferred(source),
                }
            )

        # Wallpapers van voorkeursbronnen (bijv. r/EarthPorn) naar voren,
        # met behoud van de onderlinge volgorde (stable sort).
        wallpapers.sort(key=lambda w: not w["preferred"])

        return wallpapers

    def download(self, wallpaper: dict, dest_dir) -> Path:
        """
        Downloadt 1 wallpaper (dict met id/url/extension, zoals uit search())
        naar dest_dir. Schrijft eerst naar een .part-bestand en hernoemt pas
        na een succesvolle download, zodat er nooit een half bestand meetelt.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{wallpaper['id']}.{wallpaper['extension']}"
        dest_path = dest_dir / filename
        tmp_path = dest_dir / f"{filename}.part"

        response = requests.get(wallpaper["url"], stream=True, timeout=60)
        response.raise_for_status()

        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                f.write(chunk)

        tmp_path.rename(dest_path)

        return dest_path
