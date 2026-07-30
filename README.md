# WallFlow

Self-hosted 4K nature wallpaper rotator and server. Downloads wallpapers
from the Wallhaven API, rotates them once they've actually been viewed (or
hit a maximum age), and serves them over HTTP as a network wallpaper source
(Windows slideshow, Android TV screensaver backdrop, etc.).

## Before you start

Copy [`server/config.example.yaml`](server/config.example.yaml) to your
config folder as `config.yaml`, and fill in your Wallhaven API key
(https://wallhaven.cc/settings/account).

## Usage

### docker-compose

```yaml
services:
  wallflow:
    image: ghcr.io/hb64/wallflow:latest
    container_name: wallflow
    environment:
      - TZ=Europe/Amsterdam
    ports:
      - 8080:8080
    volumes:
      - /path/to/config:/config
      - /path/to/database:/database
      - /path/to/wallpapers:/wallpapers
      - /path/to/logs:/logs
    restart: unless-stopped
```

### docker run

```bash
docker run -d \
  --name wallflow \
  -e TZ=Europe/Amsterdam \
  -p 8080:8080 \
  -v /path/to/config:/config \
  -v /path/to/database:/database \
  -v /path/to/wallpapers:/wallpapers \
  -v /path/to/logs:/logs \
  --restart unless-stopped \
  ghcr.io/hb64/wallflow:latest
```

The web UI (tag management, wallpaper browser) is available at
`http://localhost:8080/`.

## Parameters

| Parameter | Function |
|---|---|
| `TZ` | Timezone, e.g. `Europe/Amsterdam` |
| `-p 8080:8080` | Web UI and wallpaper HTTP server |
| `-v /path/to/config:/config` | `config.yaml` (Wallhaven API key + settings) |
| `-v /path/to/database:/database` | Persistent SQLite database |
| `-v /path/to/wallpapers:/wallpapers` | Downloaded wallpapers (shared over the network to other devices) |
| `-v /path/to/logs:/logs` | Log files |

## Android TV screensaver app

A ready-built APK is available on the [Releases page](../../releases) -
download and install it, no build tools required. Open the app and point it
at this server's address.

If you no longer want a given release listed, remove it yourself under
Releases > select the release > Delete.

## Troubleshooting

**Port conflict** - change the host port, e.g. `-p 8180:8080`.

**No wallpapers appearing** - check that your Wallhaven API key in
`config.yaml` is correct, and that the container can reach `wallhaven.cc`.
