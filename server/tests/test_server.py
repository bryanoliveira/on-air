import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from on_air_server.app import Application
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


if __name__ == "__main__":
    unittest.main()
