import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return utc_now()
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO 8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


class Store:
    def __init__(self, database_path: str, timeout_seconds: int = 300):
        self.database_path = database_path
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self.connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    last_seen_at TEXT NOT NULL,
                    end_reason TEXT,
                    mic_seconds REAL NOT NULL DEFAULT 0,
                    camera_seconds REAL NOT NULL DEFAULT 0,
                    last_mic_active INTEGER NOT NULL DEFAULT 0,
                    last_camera_active INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_meeting_per_user
                    ON meetings(username) WHERE ended_at IS NULL;
                CREATE INDEX IF NOT EXISTS meetings_username_started
                    ON meetings(username, started_at DESC);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER,
                    username TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('in-meeting', 'finished-meeting')),
                    mic_active INTEGER NOT NULL,
                    camera_active INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
                );
                CREATE INDEX IF NOT EXISTS events_username_occurred
                    ON events(username, occurred_at DESC);
                """
            )

    def _accrue(self, connection, meeting, until: datetime):
        last_seen = parse_timestamp(meeting["last_seen_at"])
        seconds = max(0.0, min((until - last_seen).total_seconds(), self.timeout_seconds))
        return (
            float(meeting["mic_seconds"]) + (seconds if meeting["last_mic_active"] else 0),
            float(meeting["camera_seconds"]) + (seconds if meeting["last_camera_active"] else 0),
        )

    def _expire_locked(self, connection, now: datetime) -> int:
        cutoff = now - timedelta(seconds=self.timeout_seconds)
        meetings = connection.execute(
            "SELECT * FROM meetings WHERE ended_at IS NULL AND last_seen_at < ?",
            (iso(cutoff),),
        ).fetchall()
        for meeting in meetings:
            ended_at = parse_timestamp(meeting["last_seen_at"]) + timedelta(seconds=self.timeout_seconds)
            mic_seconds, camera_seconds = self._accrue(connection, meeting, ended_at)
            connection.execute(
                """UPDATE meetings SET ended_at = ?, end_reason = 'timeout',
                   mic_seconds = ?, camera_seconds = ? WHERE id = ?""",
                (iso(ended_at), mic_seconds, camera_seconds, meeting["id"]),
            )
        return len(meetings)

    def expire_stale(self, now: datetime | None = None) -> int:
        with self._lock, self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = self._expire_locked(connection, now or utc_now())
            connection.commit()
            return count

    def record_event(self, username: str, event_type: str, mic_active: bool,
                     camera_active: bool, occurred_at: datetime) -> dict:
        received_at = utc_now()
        with self._lock, self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._expire_locked(connection, received_at)
            meeting = connection.execute(
                "SELECT * FROM meetings WHERE username = ? AND ended_at IS NULL",
                (username,),
            ).fetchone()

            if event_type == "in-meeting":
                if meeting is None:
                    cursor = connection.execute(
                        """INSERT INTO meetings
                           (username, started_at, last_seen_at, last_mic_active, last_camera_active)
                           VALUES (?, ?, ?, ?, ?)""",
                        (username, iso(occurred_at), iso(occurred_at), mic_active, camera_active),
                    )
                    meeting_id = cursor.lastrowid
                else:
                    meeting_id = meeting["id"]
                    mic_seconds, camera_seconds = self._accrue(connection, meeting, occurred_at)
                    connection.execute(
                        """UPDATE meetings SET last_seen_at = ?, mic_seconds = ?, camera_seconds = ?,
                           last_mic_active = ?, last_camera_active = ? WHERE id = ?""",
                        (iso(max(occurred_at, parse_timestamp(meeting["last_seen_at"]))),
                         mic_seconds, camera_seconds, mic_active, camera_active, meeting_id),
                    )
            else:
                meeting_id = meeting["id"] if meeting else None
                if meeting:
                    effective_end = max(occurred_at, parse_timestamp(meeting["last_seen_at"]))
                    mic_seconds, camera_seconds = self._accrue(connection, meeting, effective_end)
                    connection.execute(
                        """UPDATE meetings SET ended_at = ?, end_reason = 'finished-meeting',
                           mic_seconds = ?, camera_seconds = ? WHERE id = ?""",
                        (iso(effective_end), mic_seconds, camera_seconds, meeting_id),
                    )

            connection.execute(
                """INSERT INTO events
                   (meeting_id, username, event_type, mic_active, camera_active, occurred_at, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (meeting_id, username, event_type, mic_active, camera_active,
                 iso(occurred_at), iso(received_at)),
            )
            connection.commit()
            return {"meeting_id": meeting_id, "in_meeting": event_type == "in-meeting"}

    def states(self) -> list[dict]:
        self.expire_stale()
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT username, started_at, last_seen_at, last_mic_active, last_camera_active
                   FROM meetings WHERE ended_at IS NULL ORDER BY username"""
            ).fetchall()
        return [
            {"username": row["username"], "in_meeting": True,
             "mic_active": bool(row["last_mic_active"]),
             "camera_active": bool(row["last_camera_active"]),
             "started_at": row["started_at"], "last_seen_at": row["last_seen_at"]}
            for row in rows
        ]

    def meetings(self, username: str | None = None, limit: int = 100) -> list[dict]:
        self.expire_stale()
        where, parameters = ("WHERE username = ?", [username]) if username else ("", [])
        with self.connection() as connection:
            rows = connection.execute(
                f"""SELECT id, username, started_at, ended_at, last_seen_at, end_reason,
                    mic_seconds, camera_seconds,
                    CASE WHEN ended_at IS NULL THEN NULL
                         ELSE unixepoch(ended_at) - unixepoch(started_at) END AS duration_seconds
                    FROM meetings {where} ORDER BY started_at DESC LIMIT ?""",
                (*parameters, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self, username: str | None = None) -> dict:
        self.expire_stale()
        where, parameters = ("WHERE username = ?", [username]) if username else ("", [])
        with self.connection() as connection:
            row = connection.execute(
                f"""SELECT COUNT(*) AS meeting_count,
                    COALESCE(SUM(CASE WHEN ended_at IS NOT NULL
                        THEN unixepoch(ended_at) - unixepoch(started_at) ELSE 0 END), 0) AS meeting_seconds,
                    COALESCE(SUM(mic_seconds), 0) AS mic_seconds,
                    COALESCE(SUM(camera_seconds), 0) AS camera_seconds
                    FROM meetings {where}""",
                parameters,
            ).fetchone()
        return dict(row)
