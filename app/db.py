"""SQLite-Zugriff.

Bewusst synchron gehalten: die Queries sind winzig (einzelne Zeilen bzw. ein
paar hundert Votes) und laufen im WAL-Modus im Mikrosekundenbereich. Ein
Thread-Lock schuetzt die eine gemeinsame Verbindung.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import DB_PATH

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS spectators (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routines (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    apparatus      TEXT NOT NULL,
    athlete        TEXT NOT NULL,
    club           TEXT NOT NULL DEFAULT '',
    start_value    REAL NOT NULL DEFAULT 10.0,
    status         TEXT NOT NULL DEFAULT 'prepared',
    official_score REAL,
    created_at     TEXT NOT NULL,
    opened_at      TEXT,
    closed_at      TEXT,
    scored_at      TEXT
);

CREATE TABLE IF NOT EXISTS votes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id   INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    spectator_id TEXT    NOT NULL REFERENCES spectators(id) ON DELETE CASCADE,
    deduction    REAL    NOT NULL,
    score        REAL    NOT NULL,
    diff         REAL,
    points       INTEGER,
    created_at   TEXT    NOT NULL,
    UNIQUE (routine_id, spectator_id)
);

CREATE INDEX IF NOT EXISTS idx_votes_routine ON votes(routine_id);
CREATE INDEX IF NOT EXISTS idx_votes_spectator ON votes(spectator_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with _lock:
        return connect().execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    with _lock:
        conn = connect()
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


# --------------------------------------------------------------------------
# Zuschauer
# --------------------------------------------------------------------------

def upsert_spectator(spectator_id: str, name: str) -> dict:
    ts = now()
    existing = query_one("SELECT * FROM spectators WHERE id = ?", (spectator_id,))
    if existing is None:
        execute(
            "INSERT INTO spectators (id, name, created_at, last_seen) VALUES (?,?,?,?)",
            (spectator_id, name, ts, ts),
        )
    else:
        execute(
            "UPDATE spectators SET name = ?, last_seen = ? WHERE id = ?",
            (name or existing["name"], ts, spectator_id),
        )
    row = query_one("SELECT * FROM spectators WHERE id = ?", (spectator_id,))
    return dict(row) if row else {}


def spectator_count() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM spectators")
    return int(row["c"]) if row else 0


# --------------------------------------------------------------------------
# Uebungen
# --------------------------------------------------------------------------

def create_routine(apparatus: str, athlete: str, club: str, start_value: float) -> dict:
    cur = execute(
        "INSERT INTO routines (apparatus, athlete, club, start_value, status, created_at)"
        " VALUES (?,?,?,?,'prepared',?)",
        (apparatus, athlete, club, start_value, now()),
    )
    return get_routine(int(cur.lastrowid))


def get_routine(routine_id: int) -> dict:
    row = query_one("SELECT * FROM routines WHERE id = ?", (routine_id,))
    return dict(row) if row else {}


def update_routine(routine_id: int, **fields: Any) -> dict:
    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        execute(f"UPDATE routines SET {cols} WHERE id = ?", (*fields.values(), routine_id))
    return get_routine(routine_id)


def delete_routine(routine_id: int) -> None:
    execute("DELETE FROM votes WHERE routine_id = ?", (routine_id,))
    execute("DELETE FROM routines WHERE id = ?", (routine_id,))


def list_routines(limit: int = 200) -> list[dict]:
    rows = query(
        "SELECT r.*, (SELECT COUNT(*) FROM votes v WHERE v.routine_id = r.id) AS vote_count"
        " FROM routines r ORDER BY r.id DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def active_routine() -> dict | None:
    row = query_one(
        "SELECT * FROM routines WHERE status IN ('open','closed') ORDER BY id DESC LIMIT 1"
    )
    return dict(row) if row else None


def current_routine() -> dict | None:
    """Aktive Uebung, sonst die zuletzt angelegte/gewertete."""
    row = query_one(
        "SELECT * FROM routines WHERE status IN ('open','closed') ORDER BY id DESC LIMIT 1"
    )
    if row is None:
        row = query_one("SELECT * FROM routines ORDER BY id DESC LIMIT 1")
    return dict(row) if row else None


def latest_scored_routine() -> dict | None:
    row = query_one(
        "SELECT * FROM routines WHERE status = 'scored'"
        " ORDER BY scored_at DESC, id DESC LIMIT 1"
    )
    return dict(row) if row else None


# --------------------------------------------------------------------------
# Votes
# --------------------------------------------------------------------------

def save_vote(routine_id: int, spectator_id: str, deduction: float, score: float) -> None:
    execute(
        "INSERT INTO votes (routine_id, spectator_id, deduction, score, created_at)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(routine_id, spectator_id) DO UPDATE SET"
        "   deduction  = excluded.deduction,"
        "   score      = excluded.score,"
        "   created_at = excluded.created_at,"
        "   diff = NULL, points = NULL",
        (routine_id, spectator_id, deduction, score, now()),
    )


def votes_for_routine(routine_id: int) -> list[dict]:
    rows = query(
        "SELECT v.*, s.name AS spectator_name FROM votes v"
        " JOIN spectators s ON s.id = v.spectator_id"
        " WHERE v.routine_id = ? ORDER BY v.score",
        (routine_id,),
    )
    return [dict(r) for r in rows]


def vote_of(routine_id: int, spectator_id: str) -> dict | None:
    row = query_one(
        "SELECT * FROM votes WHERE routine_id = ? AND spectator_id = ?",
        (routine_id, spectator_id),
    )
    return dict(row) if row else None


def vote_count(routine_id: int) -> int:
    row = query_one("SELECT COUNT(*) AS c FROM votes WHERE routine_id = ?", (routine_id,))
    return int(row["c"]) if row else 0


def apply_scores(results: list[tuple[float, int, int]]) -> None:
    """results = [(diff, points, vote_id), ...]"""
    with _lock:
        conn = connect()
        conn.executemany("UPDATE votes SET diff = ?, points = ? WHERE id = ?", results)
        conn.commit()


# --------------------------------------------------------------------------
# Leaderboard
# --------------------------------------------------------------------------

def leaderboard(limit: int = 50) -> list[dict]:
    rows = query(
        "SELECT s.id, s.name,"
        "       COALESCE(SUM(v.points), 0) AS total_points,"
        "       COUNT(v.points)            AS rated_votes,"
        "       SUM(CASE WHEN v.points >= 100 THEN 1 ELSE 0 END) AS bullseyes,"
        "       AVG(v.diff)                AS avg_diff"
        " FROM spectators s"
        " JOIN votes v ON v.spectator_id = s.id AND v.points IS NOT NULL"
        " GROUP BY s.id, s.name"
        " ORDER BY total_points DESC, avg_diff ASC, s.name ASC"
        " LIMIT ?",
        (limit,),
    )
    out = []
    for i, r in enumerate(rows, start=1):
        d = dict(r)
        d["rank"] = i
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Wettkampf zuruecksetzen
# --------------------------------------------------------------------------

def reset_competition(keep_spectators: bool = True) -> None:
    execute("DELETE FROM votes")
    execute("DELETE FROM routines")
    if not keep_spectators:
        execute("DELETE FROM spectators")
