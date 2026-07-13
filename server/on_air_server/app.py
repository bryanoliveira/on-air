import hmac
import json
import os
import re
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .store import Store, parse_timestamp


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


class Application:
    def __init__(self, store: Store, api_token: str = ""):
        self.store = store
        self.api_token = api_token

    def authorized(self, authorization: str | None) -> bool:
        if not self.api_token:
            return True
        expected = f"Bearer {self.api_token}"
        return bool(authorization and hmac.compare_digest(authorization, expected))

    def event(self, payload: dict) -> dict:
        required = {"username", "event_type", "mic_active", "camera_active"}
        if not required.issubset(payload):
            raise ValueError(f"missing required fields: {', '.join(sorted(required - payload.keys()))}")
        if not isinstance(payload["username"], str) or not USERNAME_PATTERN.fullmatch(payload["username"]):
            raise ValueError("username must be 1-128 letters, digits, or . _ @ -")
        if payload["event_type"] not in ("in-meeting", "finished-meeting"):
            raise ValueError("event_type must be in-meeting or finished-meeting")
        if type(payload["mic_active"]) is not bool or type(payload["camera_active"]) is not bool:
            raise ValueError("mic_active and camera_active must be booleans")
        occurred_at = parse_timestamp(payload.get("timestamp"))
        return self.store.record_event(payload["username"], payload["event_type"],
                                       payload["mic_active"], payload["camera_active"], occurred_at)


def handler_for(application: Application):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OnAir/1.0"

        def send_json(self, status: int, value: dict | list):
            body = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authenticate(self) -> bool:
            if application.authorized(self.headers.get("Authorization")):
                return True
            self.send_json(401, {"error": "unauthorized"})
            return False

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self.send_json(200, {"status": "ok"})
                return
            if not self.authenticate():
                return
            query = parse_qs(parsed.query)
            username = query.get("username", [None])[0]
            if parsed.path == "/api/v1/state":
                self.send_json(200, {"users": application.store.states()})
            elif parsed.path == "/api/v1/meetings":
                try:
                    limit = min(max(int(query.get("limit", ["100"])[0]), 1), 1000)
                except ValueError:
                    self.send_json(400, {"error": "limit must be an integer"})
                    return
                self.send_json(200, {"meetings": application.store.meetings(username, limit)})
            elif parsed.path == "/api/v1/summary":
                self.send_json(200, application.store.summary(username))
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/v1/events":
                self.send_json(404, {"error": "not found"})
                return
            if not self.authenticate():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16_384:
                    raise ValueError("request body must be between 1 and 16384 bytes")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
                result = application.event(payload)
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
                return
            self.send_json(202, result)

        def log_message(self, format, *args):
            print(f"{self.address_string()} - {format % args}")

    return Handler


def main():
    database_path = os.environ.get("ON_AIR_DATABASE", "/data/on-air.sqlite3")
    timeout = int(os.environ.get("ON_AIR_TIMEOUT_SECONDS", "300"))
    host = os.environ.get("ON_AIR_HOST", "0.0.0.0")
    port = int(os.environ.get("ON_AIR_PORT", "8080"))
    store = Store(database_path, timeout)
    application = Application(store, os.environ.get("ON_AIR_API_TOKEN", ""))
    server = ThreadingHTTPServer((host, port), handler_for(application))

    stop = threading.Event()
    def cleanup():
        while not stop.wait(30):
            store.expire_stale()
    threading.Thread(target=cleanup, name="meeting-cleanup", daemon=True).start()

    def shutdown(_signum, _frame):
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"On Air server listening on {host}:{port}")
    server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    main()
