"""SQLite storage for detection sessions and individual detections."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "traffic.db"

_local = threading.local()


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db():
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            mode             TEXT NOT NULL,              -- 'video' | 'live'
            source           TEXT,
            status           TEXT NOT NULL DEFAULT 'running',
            created_at       TEXT NOT NULL,
            finished_at      TEXT,
            frames_processed INTEGER NOT NULL DEFAULT 0,
            detections_count INTEGER NOT NULL DEFAULT 0,
            summary          TEXT NOT NULL DEFAULT '{}', -- JSON: class -> count
            result_video     TEXT,                       -- URL of annotated video
            meta             TEXT NOT NULL DEFAULT '{}'  -- JSON: fps, size, etc.
        );
        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            frame_index INTEGER NOT NULL,
            time_offset REAL NOT NULL DEFAULT 0,
            class_name  TEXT NOT NULL,
            confidence  REAL NOT NULL,
            x1 REAL, y1 REAL, x2 REAL, y2 REAL
        );
        CREATE INDEX IF NOT EXISTS idx_detections_session ON detections(session_id);

        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            type        TEXT NOT NULL,        -- 'no_helmet' | 'plate'
            image_path  TEXT NOT NULL,        -- URL to cropped image
            confidence  REAL NOT NULL,
            x1 REAL, y1 REAL, x2 REAL, y2 REAL,
            frame_index INTEGER NOT NULL,
            time_offset REAL NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
        """
    )
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_session(mode: str, source: str, meta: dict | None = None) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO sessions (mode, source, created_at, meta) VALUES (?,?,?,?)",
        (mode, source, _now(), json.dumps(meta or {})),
    )
    conn.commit()
    return cur.lastrowid


def update_progress(session_id: int, frames: int, detections: int, summary: dict):
    conn = _conn()
    conn.execute(
        "UPDATE sessions SET frames_processed=?, detections_count=?, summary=? WHERE id=?",
        (frames, detections, json.dumps(summary), session_id),
    )
    conn.commit()


def finish_session(session_id: int, status: str = "completed",
                   frames: int | None = None, detections: int | None = None,
                   summary: dict | None = None, result_video: str | None = None,
                   meta: dict | None = None):
    conn = _conn()
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return
    conn.execute(
        """UPDATE sessions SET status=?, finished_at=?, frames_processed=?,
           detections_count=?, summary=?, result_video=?, meta=? WHERE id=?""",
        (
            status, _now(),
            frames if frames is not None else row["frames_processed"],
            detections if detections is not None else row["detections_count"],
            json.dumps(summary if summary is not None else json.loads(row["summary"])),
            result_video if result_video is not None else row["result_video"],
            json.dumps(meta if meta is not None else json.loads(row["meta"])),
            session_id,
        ),
    )
    conn.commit()


def add_detections(session_id: int, boxes: list, frame_index: int, time_offset: float):
    if not boxes:
        return
    conn = _conn()
    conn.executemany(
        """INSERT INTO detections
           (session_id, frame_index, time_offset, class_name, confidence, x1, y1, x2, y2)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            (session_id, frame_index, time_offset, b["class_name"], b["confidence"],
             b["x1"], b["y1"], b["x2"], b["y2"])
            for b in boxes
        ],
    )
    conn.commit()


def _row_to_session(row) -> dict:
    d = dict(row)
    d["summary"] = json.loads(d.get("summary") or "{}")
    d["meta"] = json.loads(d.get("meta") or "{}")
    return d


def list_sessions(mode: str | None = None, limit: int = 100) -> list:
    conn = _conn()
    if mode:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE mode=? ORDER BY id DESC LIMIT ?",
            (mode, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_session(r) for r in rows]


def get_session(session_id: int) -> dict | None:
    row = _conn().execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return _row_to_session(row) if row else None


def get_detections(session_id: int, limit: int = 3000) -> list:
    rows = _conn().execute(
        "SELECT * FROM detections WHERE session_id=? ORDER BY frame_index, id LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def add_event(session_id: int, kind: str, image_path: str, confidence: float,
              x1: float, y1: float, x2: float, y2: float,
              frame_index: int, time_offset: float) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO events
           (session_id, type, image_path, confidence, x1, y1, x2, y2,
            frame_index, time_offset, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, kind, image_path, confidence, x1, y1, x2, y2,
         frame_index, time_offset, _now()),
    )
    conn.commit()
    return cur.lastrowid


def list_events(session_id: int | None = None, kind: str | None = None,
                limit: int = 200) -> list:
    conn = _conn()
    where, args = [], []
    if session_id is not None:
        where.append("session_id=?")
        args.append(session_id)
    if kind:
        where.append("type=?")
        args.append(kind)
    sql = "SELECT * FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def session_event_counts(session_id: int) -> dict:
    rows = _conn().execute(
        "SELECT type, COUNT(*) AS n FROM events WHERE session_id=? GROUP BY type",
        (session_id,),
    ).fetchall()
    return {r["type"]: r["n"] for r in rows}


def delete_event(event_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    return dict(row)


def delete_session_events(session_id: int) -> list:
    conn = _conn()
    rows = conn.execute("SELECT * FROM events WHERE session_id=?", (session_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: int) -> dict | None:
    sess = get_session(session_id)
    if sess is None:
        return None
    conn = _conn()
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    return sess


def global_stats() -> dict:
    conn = _conn()
    row = conn.execute(
        """SELECT COUNT(*) AS sessions,
                  COALESCE(SUM(frames_processed),0) AS frames,
                  COALESCE(SUM(detections_count),0) AS detections
           FROM sessions"""
    ).fetchone()
    class_totals: dict = {}
    for r in conn.execute("SELECT summary FROM sessions"):
        for name, count in json.loads(r["summary"] or "{}").items():
            class_totals[name] = class_totals.get(name, 0) + count
    event_totals = {r["type"]: r["n"] for r in
                    conn.execute("SELECT type, COUNT(*) AS n FROM events GROUP BY type")}
    recent = list_sessions(limit=5)
    return {
        "sessions": row["sessions"],
        "frames": row["frames"],
        "detections": row["detections"],
        "class_totals": dict(sorted(class_totals.items(), key=lambda kv: -kv[1])),
        "event_totals": event_totals,
        "recent": recent,
    }
