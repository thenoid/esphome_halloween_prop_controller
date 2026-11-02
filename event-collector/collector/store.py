import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .protocol import Event


def utc_now() -> str:
    return timestamp(datetime.now(timezone.utc))


def timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone, e.g. 2026-10-31T18:00:00Z")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Store:
    """One serialized connection; all calls run outside the UDP event loop."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise RuntimeError("Unsupported database schema; use a compatible collector version")
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    received_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    event TEXT NOT NULL,
                    item INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    sender_ip TEXT NOT NULL,
                    sender_port INTEGER NOT NULL,
                    raw_packet TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_time ON events(received_at);
                CREATE INDEX IF NOT EXISTS events_source_id ON events(source, id);
                PRAGMA user_version=1;
            """)

    def close(self):
        with self.lock:
            self.db.close()

    def insert(self, message: Event, received_at: str, sender: tuple):
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO events (received_at,source,event,item,reason,sender_ip,sender_port,raw_packet) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (received_at, message.source, message.event, message.item, message.reason,
                 sender[0], sender[1], message.raw_packet),
            )

    def purge(self, days: int):
        if not days:
            return 0
        cutoff = timestamp(datetime.now(timezone.utc) - timedelta(days=days))
        with self.lock, self.db:
            return self.db.execute("DELETE FROM events WHERE received_at < ?", (cutoff,)).rowcount

    @staticmethod
    def where(filters: dict):
        clauses, args = [], []
        for name in ("source", "event", "item", "reason"):
            if filters.get(name) is not None:
                clauses.append(f"{name} = ?")
                args.append(filters[name])
        for name, column, operator in (
            ("since", "received_at", ">="), ("until", "received_at", "<"),
            ("after_id", "id", ">"), ("before_id", "id", "<"),
        ):
            if filters.get(name) is not None:
                clauses.append(f"{column} {operator} ?")
                args.append(filters[name])
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), args

    def events(self, filters: dict, limit: int, order: str):
        where, args = self.where(filters)
        direction = "ASC" if order == "asc" else "DESC"
        with self.lock:
            rows = self.db.execute(
                f"SELECT * FROM events{where} ORDER BY id {direction} LIMIT ?", (*args, limit + 1)
            ).fetchall()
        events = [dict(row) for row in rows[:limit]]
        return {
            "events": events, "has_more": len(rows) > limit,
            "next_after_id": events[-1]["id"] if events and order == "asc" else None,
            "next_before_id": events[-1]["id"] if events and order == "desc" else None,
        }

    def summary(self, filters: dict):
        where, args = self.where(filters)
        with self.lock:
            rows = self.db.execute(
                f"SELECT source,event,item,COUNT(*) AS count,MIN(received_at) AS first_received_at,"
                f"MAX(received_at) AS last_received_at FROM events{where} "
                "GROUP BY source,event,item ORDER BY source,event,item", args,
            ).fetchall()
        return {"total": sum(row["count"] for row in rows), "groups": [dict(row) for row in rows]}

    def controllers(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT source,COUNT(*) AS event_count,MIN(received_at) AS first_received_at,"
                "MAX(received_at) AS last_received_at FROM events GROUP BY source ORDER BY source"
            ).fetchall()
        return [dict(row) for row in rows]

    def status(self):
        with self.lock:
            return dict(self.db.execute(
                "SELECT COUNT(*) AS stored_events,MIN(received_at) AS oldest_received_at,"
                "MAX(received_at) AS newest_received_at,MAX(id) AS latest_id FROM events"
            ).fetchone())
