import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, time, timedelta, timezone
from unittest.mock import Mock, call

from on_air_server.app import Application, handler_for
from on_air_server.hooks import HomeAssistantLightHook, LightAction, decide_light_action
from on_air_server.store import Store


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(f"{self.temporary.name}/test.sqlite3", timeout_seconds=300)
        self.app = Application(self.store, "secret")
        self.start = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self):
        self.temporary.cleanup()

    def event(self, event_type="in-meeting", mic=True, camera=False, at=None):
        return self.store.record_event("alice", event_type, mic, camera, at or self.start)

    def test_records_and_finishes_meeting(self):
        self.event()
        self.event(at=self.start + timedelta(minutes=3), camera=True)
        self.event("finished-meeting", mic=False, camera=False,
                   at=self.start + timedelta(minutes=5))
        meeting = self.store.meetings("alice")[0]
        self.assertEqual(meeting["duration_seconds"], 300)
        self.assertEqual(meeting["mic_seconds"], 300)
        self.assertEqual(meeting["camera_seconds"], 120)
        self.assertEqual(meeting["end_reason"], "finished-meeting")

    def test_expires_stale_meeting(self):
        self.event(camera=True)
        self.store.expire_stale(self.start + timedelta(minutes=6))
        meeting = self.store.meetings("alice")[0]
        self.assertEqual(meeting["end_reason"], "timeout")
        self.assertEqual(meeting["duration_seconds"], 300)
        self.assertEqual(meeting["camera_seconds"], 300)

    def test_validation_and_authentication(self):
        self.assertFalse(self.app.authorized("Bearer nope"))
        self.assertTrue(self.app.authorized("Bearer secret"))
        with self.assertRaisesRegex(ValueError, "booleans"):
            self.app.event({"username": "alice", "event_type": "in-meeting",
                            "mic_active": 1, "camera_active": False})

    def test_light_decision_camera_is_red_at_any_time(self):
        self.assertEqual(
            decide_light_action([{"mic_active": True, "camera_active": True}], time(12, 0)),
            LightAction("turn_on", (255, 0, 0)),
        )

    def test_light_decision_mic_without_camera_is_green(self):
        mic_only = [{"mic_active": True, "camera_active": False}]
        self.assertEqual(
            decide_light_action(mic_only, time(12, 0)),
            LightAction("turn_on", (0, 255, 0)),
        )
        self.assertEqual(
            decide_light_action(mic_only, time(18, 0)),
            LightAction("turn_on", (0, 255, 0)),
        )

    def test_light_decision_camera_wins_over_mic(self):
        states = [
            {"mic_active": True, "camera_active": False},
            {"mic_active": True, "camera_active": True},
        ]
        self.assertEqual(
            decide_light_action(states, time(18, 0)),
            LightAction("turn_on", (255, 0, 0)),
        )

    def test_light_decision_night_boundaries_without_active_meeting(self):
        night = LightAction("turn_on", (255, 160, 0))
        off = LightAction("turn_off")
        self.assertEqual(decide_light_action([], time(17, 59, 59)), off)
        self.assertEqual(decide_light_action([], time(18, 0)), night)
        self.assertEqual(decide_light_action([], time(0, 59, 59)), night)
        self.assertEqual(decide_light_action([], time(1, 0)), off)

    def test_home_assistant_hook_checks_all_active_meetings(self):
        self.event(camera=False)
        self.store.record_event("bob", "in-meeting", False, True, self.start)
        hook = HomeAssistantLightHook(
            self.store,
            "http://home-assistant.invalid:8123",
            "not-a-real-token",
            "light.living_room_bathroom_lights",
            now=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )
        hook._call_service = Mock()

        hook()

        self.assertEqual(hook._call_service.call_args_list, [
            call(
                "turn_on",
                {"entity_id": "light.living_room_bathroom_lights"},
            ),
            call(
                "turn_on",
                {"entity_id": "light.living_room_bathroom_lights",
                 "rgb_color": [255, 0, 0]},
            ),
        ])

    def test_home_assistant_hook_primes_without_brightness_then_sets_color(self):
        self.event(camera=True)
        hook = HomeAssistantLightHook(
            self.store,
            "http://home-assistant.invalid:8123",
            "not-a-real-token",
            "light.living_room_bathroom_lights",
            brightness=123,
            now=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )
        hook._call_service = Mock()

        hook()

        self.assertEqual(hook._call_service.call_args_list, [
            call(
                "turn_on",
                {"entity_id": "light.living_room_bathroom_lights"},
            ),
            call(
                "turn_on",
                {"entity_id": "light.living_room_bathroom_lights",
                 "rgb_color": [255, 0, 0], "brightness": 123},
            ),
        ])

    def test_home_assistant_hook_turn_off_is_single_call(self):
        hook = HomeAssistantLightHook(
            self.store,
            "http://home-assistant.invalid:8123",
            "not-a-real-token",
            "light.living_room_bathroom_lights",
            now=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )
        hook._call_service = Mock()

        hook()

        hook._call_service.assert_called_once_with(
            "turn_off",
            {"entity_id": "light.living_room_bathroom_lights"},
        )

    def test_expiry_runs_hooks(self):
        hook = Mock()
        app = Application(self.store, hooks=[hook])
        self.event(camera=True)

        count = app.expire_stale(self.start + timedelta(minutes=6))

        self.assertEqual(count, 1)
        hook.assert_called_once_with()

    def test_hook_failure_does_not_fail_event_post(self):
        def failing_hook():
            raise RuntimeError("test hook failure")

        app = Application(self.store, "secret", [failing_hook])
        payload = json.dumps({
            "username": "alice",
            "event_type": "in-meeting",
            "mic_active": True,
            "camera_active": False,
            "timestamp": self.start.isoformat(),
        }).encode("utf-8")
        handler = object.__new__(handler_for(app))
        handler.path = "/api/v1/events"
        handler.headers = {
            "Authorization": "Bearer secret",
            "Content-Length": str(len(payload)),
        }
        handler.rfile = io.BytesIO(payload)
        handler.send_json = Mock()

        errors = io.StringIO()
        with redirect_stderr(errors):
            handler.do_POST()

        handler.send_json.assert_called_once()
        status, body = handler.send_json.call_args.args
        self.assertEqual(status, 202)
        self.assertTrue(body["in_meeting"])
        self.assertIn("test hook failure", errors.getvalue())
        self.assertEqual(len(self.store.meetings("alice")), 1)


if __name__ == "__main__":
    unittest.main()
