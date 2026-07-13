# On Air

On Air is a self-hosted meeting presence system. A native macOS menubar app watches whether any microphone input or camera is in use and reports that state to a small HTTP service. The service exposes current presence and stores raw events plus derived meeting sessions in SQLite.

The project contains no hostnames, usernames, tokens, or other machine-specific values. Configure them locally in the menubar app and your server's `.env` file.

## How it works

- The Mac app polls CoreAudio and CoreMediaIO every 5 seconds.
- Any active microphone or camera starts a meeting. Thirty continuous seconds with neither device active ends it.
- While active, the app sends an `in-meeting` event every 3 minutes. It sends `finished-meeting` when activity ends or the app quits normally.
- The server closes an abandoned meeting 5 minutes after its last heartbeat.
- SQLite stores every event and a session record with total, microphone-active, and camera-active seconds.

This is intentionally a proxy. macOS does not expose meeting-app membership as a public system API, so a muted meeting with the camera off cannot be distinguished from no meeting. Likewise, recording and dictation apps can look like meetings.

## Deploy the server

Requirements: Docker Engine with the Compose plugin.

```sh
git clone https://github.com/YOUR_USERNAME/on-air.git
cd on-air
cp .env.example .env
```

Set a long random token in `.env`, then launch:

```sh
docker compose up -d --build
curl http://SERVER_ADDRESS:8080/healthz
```

The SQLite database lives in the named `on-air-data` volume. Put the service behind your existing HTTPS reverse proxy for use outside a trusted LAN; the bearer token does not encrypt plain HTTP traffic. To bind only to the local host for a reverse proxy, change the port mapping to `127.0.0.1:8080:8080`.

Back up the volume with your normal Docker-volume process. SQLite uses WAL mode, so use SQLite's backup command or stop the container before copying its database files.

## Build and run the Mac app

Requirements: macOS 13 or newer and Xcode Command Line Tools.

```sh
cd macos
./scripts/build-app.sh
cp -R ".build/On Air.app" /Applications/
open "/Applications/On Air.app"
```

The first launch opens Settings. Enter:

- Server URL: the origin only, for example `https://on-air.example.net` or `http://192.0.2.10:8080`
- Username: the stable name that other services should query
- API token: the value of `ON_AIR_API_TOKEN` in the server `.env`

The app is ad-hoc signed by the build script. macOS may require you to approve a locally built app in System Settings → Privacy & Security. To start it when you log in, add On Air under System Settings → General → Login Items.

The app only queries device-running state; it does not capture audio or video. Depending on the macOS version and attached virtual devices, reporting behavior may differ. Use **Send status now** in the menubar menu while testing your setup.

## API

All `/api/v1` endpoints require `Authorization: Bearer TOKEN` when `ON_AIR_API_TOKEN` is set. `/healthz` is intentionally public.

Create an event:

```sh
curl -X POST http://localhost:8080/api/v1/events \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "alice",
    "event_type": "in-meeting",
    "mic_active": true,
    "camera_active": false,
    "timestamp": "2026-07-13T12:00:00Z"
  }'
```

`timestamp` is optional and defaults to server receipt time. Valid event types are `in-meeting` and `finished-meeting`.

Query current active users:

```sh
curl -H 'Authorization: Bearer YOUR_TOKEN' http://localhost:8080/api/v1/state
```

Query meeting history (newest first):

```sh
curl -H 'Authorization: Bearer YOUR_TOKEN' \
  'http://localhost:8080/api/v1/meetings?username=alice&limit=100'
```

Query aggregates:

```sh
curl -H 'Authorization: Bearer YOUR_TOKEN' \
  'http://localhost:8080/api/v1/summary?username=alice'
```

The summary returns `meeting_count`, `meeting_seconds`, `mic_seconds`, and `camera_seconds`. Active sessions count toward `meeting_count`, but their unfinished duration is not included in `meeting_seconds` until they close. Activity time is estimated between heartbeats: each interval is attributed to the state reported by the preceding event, capped at the 5-minute timeout.

## Development

Run server tests without installing dependencies:

```sh
PYTHONPATH=server python3 -m unittest discover -s server/tests -v
```

Compile the macOS client:

```sh
swift build --package-path macos
```

Server configuration:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ON_AIR_API_TOKEN` | empty | Bearer token; empty disables authentication |
| `ON_AIR_DATABASE` | `/data/on-air.sqlite3` | SQLite file path |
| `ON_AIR_TIMEOUT_SECONDS` | `300` | Stale-session timeout |
| `ON_AIR_HOST` | `0.0.0.0` | Listen address |
| `ON_AIR_PORT` | `8080` | Listen port |

## License

MIT
