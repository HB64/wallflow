"""
httpserver.py

Lichte HTTP-server die de wallpapers-map serveert, zodat andere apparaten
(zoals een Android TV screensaver) de afbeeldingen via HTTP kunnen ophalen
in plaats van via SMB. Beheert daarnaast de include/exclude-tags (via
tags_store.py), zodat je die kunt aanpassen zonder rebuild of herstart.

Endpoints:
- GET    /wallpapers        -> JSON lijst van bestandsnamen
- GET    /wallpapers/<naam> -> de afbeelding zelf
- DELETE /wallpapers/<naam> -> verwijdert het bestand (bijv. vanuit de
  screensaver-app). WallFlow's eigen rotatiecyclus merkt vanzelf dat het
  bestand weg is en blokkeert dat ID voorgoed (zie main.py: check_rotation).

- GET    /tags                    -> {"include": [...], "exclude": [...]}
- POST   /tags/include            -> body {"tag": "boats"}, voegt toe
- POST   /tags/exclude            -> body {"tag": "boats"}, voegt toe
- DELETE /tags/include/<tag>      -> verwijdert tag
- DELETE /tags/exclude/<tag>      -> verwijdert tag
  Wijzigingen zijn direct actief bij de eerstvolgende zoekopdracht, geen
  rebuild of herstart van de container nodig.

- GET    /ui  -> eenvoudige webpagina om tags te beheren en wallpapers te
  bekijken/verwijderen, rechtstreeks vanuit de browser (geen curl nodig).
- GET    /    -> landingspagina met een link naar /ui.

Let op: geen authenticatie - bedoeld voor gebruik binnen je eigen LAN.
"""

import json
import mimetypes
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import tags_store

# Verbindingen die een client voortijdig afbreekt (browser-tab gesloten,
# screensaver die al naar de volgende afbeelding is gewisseld, enz.) zijn
# normaal gedrag - geen bug. Zonder deze lijst logt Python hier een volledige
# traceback voor, wat het log onnodig vervuilt.
BENIGN_DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Klein berglandschap-icoon (zelfde stijl als het Android app-icoon), als
# base64-svg zodat er geen los favicon-bestand of extra endpoint nodig is.
FAVICON_DATA_URI = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+"
    "PHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iMTIiIGZpbGw9IiMxYjFiMWYiLz48Y2lyY2xl"
    "IGN4PSI0NSIgY3k9IjE4IiByPSI3IiBmaWxsPSIjZjVjNTQyIi8+PHBhdGggZD0iTTIgNTIgTDIwIDI0"
    "IEwzMCAzNiBMNDIgMjAgTDYyIDUyIFoiIGZpbGw9IiM0YTkwZDkiLz48L3N2Zz4="
)

UI_HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WallFlow beheer</title>
<link rel="icon" type="image/svg+xml" href="__FAVICON__">
<style>
  * { box-sizing: border-box; }
  body { font-family: sans-serif; background:#1b1b1f; color:#eee; margin:0; padding:20px; }
  h1 { margin-top:0; font-size:22px; }
  h2 { border-bottom:1px solid #444; padding-bottom:6px; }
  .columns { display:flex; gap:30px; flex-wrap:wrap; }
  .column { flex:1 1 240px; min-width:0; }
  .chip-list { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }
  .chip { background:#333; border-radius:14px; padding:4px 10px; display:flex; align-items:center; gap:6px; font-size:14px; max-width:100%; }
  .chip span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .chip button { background:none; border:none; color:#f88; cursor:pointer; font-weight:bold; flex-shrink:0; }
  .add-row { display:flex; gap:6px; flex-wrap:wrap; }
  .add-row input { flex:1 1 140px; min-width:0; padding:8px; font-size:16px; border-radius:6px; border:1px solid #555; background:#222; color:#eee; }
  .add-row button { padding:8px 14px; font-size:15px; border-radius:6px; border:none; background:#4a90d9; color:#fff; cursor:pointer; white-space:nowrap; }
  .gallery { display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap:16px; margin-top:16px; }
  .tile { background:#25252b; border-radius:8px; overflow:hidden; }
  .tile img { width:100%; height:150px; object-fit:cover; display:block; }
  .tile .info { padding:8px; display:flex; justify-content:space-between; align-items:center; font-size:12px; gap:8px; }
  .tile .info span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .tile button { background:#c0392b; border:none; color:#fff; padding:6px 8px; font-size:13px; border-radius:4px; cursor:pointer; flex-shrink:0; }
  #status { margin:10px 0; min-height:20px; color:#8f8; }

  @media (max-width: 480px) {
    body { padding:12px; }
    .columns { gap:20px; }
  }
</style>
</head>
<body>
<h1>WallFlow beheer</h1>
<div id="status"></div>

<h2>Tags</h2>
<div class="columns">
  <div class="column">
    <h3>Include</h3>
    <div class="chip-list" id="include-list"></div>
    <div class="add-row">
      <input type="text" id="include-input" placeholder="nieuwe include-tag">
      <button onclick="addTag('include')">Toevoegen</button>
    </div>
  </div>
  <div class="column">
    <h3>Exclude</h3>
    <div class="chip-list" id="exclude-list"></div>
    <div class="add-row">
      <input type="text" id="exclude-input" placeholder="nieuwe exclude-tag">
      <button onclick="addTag('exclude')">Toevoegen</button>
    </div>
  </div>
</div>

<h2>Wallpapers</h2>
<div class="gallery" id="gallery"></div>

<script>
function showStatus(msg, isError) {
  var el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = isError ? '#f88' : '#8f8';
  setTimeout(function() { el.textContent = ''; }, 4000);
}

function renderChips(kind, tags) {
  var container = document.getElementById(kind + '-list');
  container.innerHTML = '';
  tags.forEach(function(tag) {
    var chip = document.createElement('div');
    chip.className = 'chip';
    var span = document.createElement('span');
    span.textContent = tag;
    var btn = document.createElement('button');
    btn.textContent = 'x';
    btn.title = 'Verwijderen';
    btn.onclick = function() { removeTag(kind, tag); };
    chip.appendChild(span);
    chip.appendChild(btn);
    container.appendChild(chip);
  });
}

function loadTags() {
  fetch('/tags').then(function(r) { return r.json(); }).then(function(data) {
    renderChips('include', data.include);
    renderChips('exclude', data.exclude);
  });
}

function addTag(kind) {
  var input = document.getElementById(kind + '-input');
  var tag = input.value.trim();
  if (!tag) { return; }
  fetch('/tags/' + kind, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag: tag })
  }).then(function(r) {
    if (!r.ok) { throw new Error('Toevoegen mislukt (status ' + r.status + ')'); }
    return r.json();
  }).then(function(data) {
    renderChips('include', data.include);
    renderChips('exclude', data.exclude);
    input.value = '';
    showStatus('Tag toegevoegd: ' + tag, false);
  }).catch(function(e) { showStatus(e.message, true); });
}

function removeTag(kind, tag) {
  fetch('/tags/' + kind + '/' + encodeURIComponent(tag), { method: 'DELETE' })
    .then(function(r) {
      if (!r.ok) { throw new Error('Verwijderen mislukt (status ' + r.status + ')'); }
      return r.json();
    }).then(function(data) {
      renderChips('include', data.include);
      renderChips('exclude', data.exclude);
      showStatus('Tag verwijderd: ' + tag, false);
    }).catch(function(e) { showStatus(e.message, true); });
}

function loadGallery() {
  fetch('/wallpapers').then(function(r) { return r.json(); }).then(function(data) {
    var gallery = document.getElementById('gallery');
    gallery.innerHTML = '';
    data.wallpapers.forEach(function(name) {
      var tile = document.createElement('div');
      tile.className = 'tile';

      var img = document.createElement('img');
      img.src = '/wallpapers/' + encodeURIComponent(name);
      img.loading = 'lazy';
      img.alt = name;

      var info = document.createElement('div');
      info.className = 'info';

      var label = document.createElement('span');
      label.textContent = name;

      var delBtn = document.createElement('button');
      delBtn.textContent = 'Verwijderen';
      delBtn.onclick = function() { deleteWallpaper(name, tile); };

      info.appendChild(label);
      info.appendChild(delBtn);
      tile.appendChild(img);
      tile.appendChild(info);
      gallery.appendChild(tile);
    });
  });
}

function deleteWallpaper(name, tile) {
  if (!confirm('Weet je zeker dat je "' + name + '" wilt verwijderen?')) { return; }
  fetch('/wallpapers/' + encodeURIComponent(name), { method: 'DELETE' })
    .then(function(r) {
      if (!r.ok && r.status !== 204) { throw new Error('Verwijderen mislukt (status ' + r.status + ')'); }
      tile.remove();
      showStatus('Verwijderd: ' + name, false);
    }).catch(function(e) { showStatus(e.message, true); });
}

loadTags();
loadGallery();
</script>
</body>
</html>
"""

LANDING_HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WallFlow</title>
<link rel="icon" type="image/svg+xml" href="__FAVICON__">
<style>
  * { box-sizing: border-box; }
  body { font-family: sans-serif; background:#1b1b1f; color:#eee; padding:40px; margin:0; }
  a { color:#4a90d9; font-size:18px; }
  .preview { margin-top:24px; max-width:480px; }
  .preview img {
    max-width:100%;
    width:100%;
    border-radius:10px;
    box-shadow:0 4px 16px rgba(0,0,0,0.5);
    display:block;
  }
  .preview .caption { color:#888; font-size:12px; margin-top:6px; }

  @media (max-width: 480px) {
    body { padding:20px; }
  }
</style>
</head>
<body>
<h1>WallFlow</h1>
<p><a href="/ui">Tags en wallpapers beheren</a></p>
__PREVIEW_BLOCK__
</body>
</html>
"""


def make_handler(wallpaper_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # geen aparte requestlogs, wallflow.log blijft leidend

        def _send_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _list_wallpapers(self):
            files = sorted(
                p.name for p in wallpaper_dir.iterdir()
                if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
            )
            self._send_json(200, {"wallpapers": files})

        def _resolve_safe_path(self, filename):
            """
            Retourneert het Path-object voor filename, of None als de naam
            ongeldig is (path traversal, verkeerd bestandstype). Stuurt in dat
            geval zelf al de foutrespons.
            """
            filename = unquote(filename)

            # Voorkom path traversal: alleen platte bestandsnamen zonder
            # sub-mappen, en alleen bestanden die echt in wallpaper_dir staan.
            if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
                self.send_error(400, "Ongeldige bestandsnaam")
                return None

            file_path = wallpaper_dir / filename

            if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                self.send_error(403, "Bestandstype niet toegestaan")
                return None

            if file_path.parent != wallpaper_dir:
                self.send_error(400, "Ongeldige bestandsnaam")
                return None

            return file_path

        def _serve_file(self, filename):
            file_path = self._resolve_safe_path(filename)

            if file_path is None:
                return

            if not file_path.is_file():
                self.send_error(404, "Niet gevonden")
                return

            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            data = file_path.read_bytes()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _delete_file(self, filename):
            file_path = self._resolve_safe_path(filename)

            if file_path is None:
                return

            if not file_path.is_file():
                self.send_error(404, "Niet gevonden")
                return

            file_path.unlink()
            self.send_response(204)
            self.end_headers()

        def _get_tags(self):
            include_tags, exclude_tags = tags_store.get_tags()
            self._send_json(200, {"include": include_tags, "exclude": exclude_tags})

        def _add_tag(self, kind):
            try:
                payload = self._read_json_body()
            except (ValueError, UnicodeDecodeError):
                self.send_error(400, "Ongeldige JSON-body")
                return

            tag = str(payload.get("tag", "")).strip()
            if not tag:
                self.send_error(400, "Veld 'tag' ontbreekt of is leeg")
                return

            try:
                include_tags, exclude_tags = tags_store.add_tag(kind, tag)
            except ValueError as e:
                self.send_error(400, str(e))
                return

            self._send_json(200, {"include": include_tags, "exclude": exclude_tags})

        def _remove_tag(self, kind, tag):
            tag = unquote(tag)
            if not tag:
                self.send_error(400, "Ongeldige tag")
                return

            removed = tags_store.remove_tag(kind, tag)
            if not removed:
                self.send_error(404, "Tag niet gevonden")
                return

            include_tags, exclude_tags = tags_store.get_tags()
            self._send_json(200, {"include": include_tags, "exclude": exclude_tags})

        def _serve_ui(self):
            html = UI_HTML.replace("__FAVICON__", FAVICON_DATA_URI)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_landing(self):
            files = [
                p.name for p in wallpaper_dir.iterdir()
                if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
            ]

            if files:
                preview_name = random.choice(files)
                preview_block = (
                    '<div class="preview">'
                    f'<img src="/wallpapers/{quote(preview_name)}" alt="{preview_name}">'
                    f'<p class="caption">{preview_name}</p>'
                    "</div>"
                )
            else:
                preview_block = "<p>Nog geen wallpapers beschikbaar.</p>"

            html = LANDING_HTML.replace("__FAVICON__", FAVICON_DATA_URI)
            html = html.replace("__PREVIEW_BLOCK__", preview_block)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path

            if path == "/":
                self._serve_landing()
                return

            if path in ("/ui", "/ui/"):
                self._serve_ui()
                return

            if path in ("/wallpapers", "/wallpapers/"):
                self._list_wallpapers()
                return

            if path.startswith("/wallpapers/"):
                filename = path[len("/wallpapers/"):]
                self._serve_file(filename)
                return

            if path == "/tags":
                self._get_tags()
                return

            self.send_error(404, "Niet gevonden")

        def do_POST(self):
            path = urlparse(self.path).path

            if path in ("/tags/include", "/tags/exclude"):
                kind = path.rsplit("/", 1)[-1]
                self._add_tag(kind)
                return

            self.send_error(404, "Niet gevonden")

        def do_DELETE(self):
            path = urlparse(self.path).path

            if path.startswith("/wallpapers/"):
                filename = path[len("/wallpapers/"):]
                self._delete_file(filename)
                return

            if path.startswith("/tags/include/"):
                self._remove_tag("include", path[len("/tags/include/"):])
                return

            if path.startswith("/tags/exclude/"):
                self._remove_tag("exclude", path[len("/tags/exclude/"):])
                return

            self.send_error(404, "Niet gevonden")

    return Handler


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """
    Als een client de verbinding voortijdig afbreekt tijdens het versturen
    van een respons, logt de standaard socketserver hiervoor een volledige
    traceback. Dat is geen bug (browser-tab dicht, screensaver al naar de
    volgende afbeelding), dus die specifieke gevallen onderdrukken we hier.
    """

    def handle_error(self, request, client_address):
        exc_value = sys.exc_info()[1]
        if isinstance(exc_value, BENIGN_DISCONNECT_ERRORS):
            return
        super().handle_error(request, client_address)


def start_server(wallpaper_dir: Path, port: int = 8080) -> ThreadingHTTPServer:
    """
    Start de server in een achtergrond-thread (non-blocking).
    Retourneert het server-object (voor eventuele shutdown).
    """
    handler_cls = make_handler(wallpaper_dir)
    server = _QuietThreadingHTTPServer(("0.0.0.0", port), handler_cls)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server
