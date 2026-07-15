import json
import os
import sys
import threading
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .store import Store


RGBColor = tuple[int, int, int]


@dataclass(frozen=True)
class LightAction:
    service: str
    rgb_color: RGBColor | None = None


def decide_light_action(active_states: list[dict], local_time: time,
                        camera_color: RGBColor = (255, 0, 0),
                        mic_color: RGBColor = (0, 255, 0),
                        night_color: RGBColor = (255, 160, 0)) -> LightAction:
    if any(state["camera_active"] for state in active_states):
        return LightAction("turn_on", camera_color)
    if any(state["mic_active"] for state in active_states):
        return LightAction("turn_on", mic_color)
    if local_time.hour >= 18 or local_time.hour < 1:
        return LightAction("turn_on", night_color)
    return LightAction("turn_off")


def parse_rgb_color(value: str, variable_name: str) -> RGBColor:
    try:
        parts = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise ValueError(f"{variable_name} must be three comma-separated integers") from error
    if len(parts) != 3 or any(part < 0 or part > 255 for part in parts):
        raise ValueError(f"{variable_name} must contain three values from 0 to 255")
    return parts


def parse_brightness(value: str) -> int | None:
    if not value:
        return None
    try:
        brightness = int(value)
    except ValueError as error:
        raise ValueError("ON_AIR_HOMEASSISTANT_BRIGHTNESS must be an integer from 1 to 255") from error
    if brightness < 1 or brightness > 255:
        raise ValueError("ON_AIR_HOMEASSISTANT_BRIGHTNESS must be an integer from 1 to 255")
    return brightness


class HookRunner:
    def __init__(self, hooks=()):
        self.hooks = tuple(hooks)
        self._lock = threading.Lock()

    def run(self):
        with self._lock:
            for hook in self.hooks:
                try:
                    hook()
                except Exception as error:
                    name = getattr(hook, "name", hook.__class__.__name__)
                    print(f"On Air hook {name} failed: {error}", file=sys.stderr)


class HomeAssistantLightHook:
    name = "homeassistant_light"

    def __init__(self, store: Store, url: str, token: str, entity_id: str,
                 timezone_name: str = "America/Sao_Paulo",
                 camera_color: RGBColor = (255, 0, 0),
                 mic_color: RGBColor = (0, 255, 0),
                 night_color: RGBColor = (255, 160, 0),
                 brightness: int | None = None, timeout_seconds: float = 5.0,
                 now: Callable[[], datetime] | None = None):
        self.store = store
        self.url = url.rstrip("/")
        self.token = token
        self.entity_id = entity_id
        self.timezone = ZoneInfo(timezone_name)
        self.camera_color = camera_color
        self.mic_color = mic_color
        self.night_color = night_color
        self.brightness = brightness
        self.timeout_seconds = timeout_seconds
        self._now = now or (lambda: datetime.now(self.timezone))

    @classmethod
    def from_environment(cls, store: Store, environ: Mapping[str, str]):
        url = environ.get("ON_AIR_HOMEASSISTANT_URL", "").strip()
        token = environ.get("ON_AIR_HOMEASSISTANT_TOKEN", "").strip()
        entity_id = environ.get("ON_AIR_HOMEASSISTANT_LIGHT_ENTITY_ID", "").strip()
        missing = [name for name, value in (
            ("ON_AIR_HOMEASSISTANT_URL", url),
            ("ON_AIR_HOMEASSISTANT_TOKEN", token),
            ("ON_AIR_HOMEASSISTANT_LIGHT_ENTITY_ID", entity_id),
        ) if not value]
        if missing:
            raise ValueError(f"homeassistant_light requires: {', '.join(missing)}")
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError("ON_AIR_HOMEASSISTANT_URL must be an http:// or https:// URL")
        if not entity_id.startswith("light."):
            raise ValueError("ON_AIR_HOMEASSISTANT_LIGHT_ENTITY_ID must be a light entity ID")

        timezone_name = environ.get(
            "ON_AIR_HOMEASSISTANT_TIMEZONE", "America/Sao_Paulo"
        ).strip()
        camera_color = parse_rgb_color(
            environ.get("ON_AIR_HOMEASSISTANT_CAMERA_COLOR", "255,0,0"),
            "ON_AIR_HOMEASSISTANT_CAMERA_COLOR",
        )
        mic_color = parse_rgb_color(
            environ.get("ON_AIR_HOMEASSISTANT_MIC_COLOR", "0,255,0"),
            "ON_AIR_HOMEASSISTANT_MIC_COLOR",
        )
        night_color = parse_rgb_color(
            environ.get("ON_AIR_HOMEASSISTANT_NIGHT_COLOR", "255,160,0"),
            "ON_AIR_HOMEASSISTANT_NIGHT_COLOR",
        )
        brightness = parse_brightness(
            environ.get("ON_AIR_HOMEASSISTANT_BRIGHTNESS", "")
        )
        try:
            timeout_seconds = float(environ.get(
                "ON_AIR_HOMEASSISTANT_TIMEOUT_SECONDS", "5"
            ))
        except ValueError as error:
            raise ValueError(
                "ON_AIR_HOMEASSISTANT_TIMEOUT_SECONDS must be a positive number"
            ) from error
        if timeout_seconds <= 0:
            raise ValueError("ON_AIR_HOMEASSISTANT_TIMEOUT_SECONDS must be a positive number")

        return cls(store, url, token, entity_id, timezone_name, camera_color,
                   mic_color, night_color, brightness, timeout_seconds)

    def __call__(self):
        active_states = self.store.states()
        local_time = self._now().astimezone(self.timezone).time()
        action = decide_light_action(active_states, local_time,
                                     self.camera_color, self.mic_color,
                                     self.night_color)
        service_data = {"entity_id": self.entity_id}
        if action.rgb_color is not None:
            if action.service == "turn_on":
                self._call_service("turn_on", {"entity_id": self.entity_id})
            service_data["rgb_color"] = list(action.rgb_color)
            if self.brightness is not None:
                service_data["brightness"] = self.brightness
        self._call_service(action.service, service_data)

    def _call_service(self, service: str, service_data: dict):
        request = urllib.request.Request(
            f"{self.url}/api/services/light/{service}",
            data=json.dumps(service_data).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            response.read()


def hooks_from_environment(store: Store,
                           environ: Mapping[str, str] | None = None) -> list:
    environ = environ if environ is not None else os.environ
    names = [name.strip() for name in environ.get("ON_AIR_HOOKS", "").split(",")
             if name.strip()]
    hooks = []
    for name in names:
        if name == "homeassistant_light":
            hooks.append(HomeAssistantLightHook.from_environment(store, environ))
        else:
            raise ValueError(f"unknown hook in ON_AIR_HOOKS: {name}")
    return hooks
