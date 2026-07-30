# WallFlow Screensaver

Android TV screensaver (Daydream) that displays wallpapers from a WallFlow
HTTP server as a backdrop, with a crossfade every 30 seconds.

## Requirements

- Android Studio (recent version, with Android SDK 34 and JDK 17)
- Your Android TV device and the WallFlow server on the same network
- The WallFlow HTTP server running and reachable, e.g. `192.168.178.75:8180`

## Open and build

1. Open this folder (`android-app/`) in Android Studio: **File > Open**.
2. Let Android Studio run the Gradle sync (may take a few minutes the first
   time, downloads the required SDK components).
3. Build the APK via **Build > Build Bundle(s) / APK(s) > Build APK(s)**, or
   run it directly on a connected/paired TV device via **Run > Run 'app'**.

The built APK ends up at:
`app/build/outputs/apk/debug/app-debug.apk`

## Installing on the TV device

Via ADB (the device needs "ADB debugging" enabled under
Settings > Device Preferences > Developer options):

```
adb connect <device-ip>:5555
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Setup

1. Open the "WallFlow Screensaver" app on the TV device (it's in your apps).
2. Under "WallFlow server", enter the address, e.g. `192.168.178.75:8180`
   (without `http://`, that's added automatically).
3. Use "Open screensaver settings" to jump straight to Android's screensaver
   settings, or go there manually via Settings > Device Preferences >
   Screensaver, and choose "WallFlow Screensaver" as the active screensaver.

## Features

- Automatic crossfade to a new random wallpaper every 30 seconds.
- D-pad left/right: browse back/forward through already-shown wallpapers, or
  fetch a new random one past the end of history.
- D-pad center/OK: delete the currently shown wallpaper (calls `DELETE` on
  the server) and move to the next one.
- Back: exit the screensaver.
- In-app "Manage tags" screen: view, add or remove include/exclude tags
  against the server's `/tags` API - changes apply immediately, no rebuild
  or restart of the server needed.
- In-app "Manage wallpapers" screen: grid of thumbnails with a delete button
  per tile.
- "Open screensaver settings" jumps directly into Android's screensaver
  settings where possible (falls back to the general Settings screen on
  devices that don't support a direct deep link).
- English and Dutch strings (`values/strings.xml` + `values-nl/strings.xml`);
  Android picks the right one based on the device's system language.

## How it works

- `WallFlowDreamService.kt` is the actual screensaver: fetches the file list
  via `GET /wallpapers` on start, then shows images via
  `GET /wallpapers/<filename>`, with D-pad navigation and delete handled via
  `dispatchKeyEvent`.
- `SettingsActivity.kt` + `dream_prefs.xml` make up the settings screen
  (server address via `EditTextPreference`/SharedPreferences, plus entries
  that launch `TagsActivity`, `GalleryActivity`, and the screensaver-settings
  shortcut).
- `TagsActivity.kt` / `GalleryActivity.kt` talk to the same `/tags` and
  `/wallpapers` HTTP endpoints as the server's own web UI (`/ui`).
- The app uses plain HTTP (no HTTPS), hence
  `android:usesCleartextTraffic="true"` in the manifest - fine for use on
  your own LAN.

## Customizing

- Switch interval: `INTERVAL_MS` in `WallFlowDreamService.kt` (currently
  30000 = 30s).
- Crossfade duration: `FADE_DURATION_MS` in the same file (currently 1500 =
  1.5s).
