"""Lightweight SQLite storage for processing-station metadata."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence


class Database:
    """Simple SQLite-backed metadata store.

    The schema mirrors the PROCESSING_STATION.md design with sessions,
    camera assets, stitched outputs, and detected events. Each call opens a
    short-lived connection to keep the FastAPI dependency simple.
    """

    def __init__(self, path: Path | str = Path("data/processing_station.db")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS camera_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    camera_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    codec TEXT,
                    fps REAL,
                    bitrate_mbps REAL,
                    offset_ms INTEGER,
                    UNIQUE(session_id, camera_id, path)
                );
                CREATE TABLE IF NOT EXISTS stitched_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    layout TEXT,
                    path_fullres TEXT,
                    path_proxy TEXT,
                    checksum_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    type TEXT NOT NULL,
                    t_start_ms INTEGER NOT NULL,
                    t_end_ms INTEGER NOT NULL,
                    confidence REAL,
                    source TEXT,
                    payload_json TEXT
                );
                """
            )
            conn.commit()
        self._initialized = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def upsert_session(self, session_id: str, started_at: str, notes: str | None = None) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, started_at, notes) VALUES (?, ?, ?)",
                (session_id, started_at, notes),
            )
            conn.commit()

    def add_camera_asset(
        self,
        session_id: str,
        camera_id: str,
        path: str,
        codec: str | None,
        fps: float | None,
        bitrate_mbps: float | None,
        offset_ms: int | None,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO camera_assets
                (session_id, camera_id, path, codec, fps, bitrate_mbps, offset_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, camera_id, path, codec, fps, bitrate_mbps, offset_ms),
            )
            conn.commit()

    def add_stitched_asset(
        self,
        session_id: str,
        layout: str,
        path_fullres: str,
        path_proxy: str | None,
        checksum_sha256: str | None,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stitched_assets (session_id, layout, path_fullres, path_proxy, checksum_sha256)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, layout, path_fullres, path_proxy, checksum_sha256),
            )
            conn.commit()

    def add_events(
        self,
        session_id: str,
        events: Iterable[tuple[str, int, int, float | None, str | None, str | None]],
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO events (session_id, type, t_start_ms, t_end_ms, confidence, source, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                events,
            )
            conn.commit()

    def sessions(self) -> list[sqlite3.Row]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.started_at, s.notes,
                    COUNT(DISTINCT c.id) AS camera_assets,
                    COUNT(DISTINCT st.id) AS stitched_assets,
                    COUNT(DISTINCT e.id) AS events
                FROM sessions s
                LEFT JOIN camera_assets c ON s.id = c.session_id
                LEFT JOIN stitched_assets st ON s.id = st.session_id
                LEFT JOIN events e ON s.id = e.session_id
                GROUP BY s.id
                ORDER BY s.started_at DESC
                """
            ).fetchall()
        return rows

    def session_events(self, session_id: str) -> list[sqlite3.Row]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY t_start_ms",
                (session_id,),
            ).fetchall()
        return rows

    def search_events(self, query: str, session_id: str | None = None) -> list[sqlite3.Row]:
        self.initialize()
        like_query = f"%{query.lower()}%"
        sql = (
            "SELECT * FROM events WHERE lower(type || ' ' || COALESCE(payload_json, '')) LIKE ?"
            " ORDER BY t_start_ms"
        )
        params: Sequence[str | None] = [like_query]
        if session_id:
            sql = sql.replace("WHERE", "WHERE session_id = ? AND")
            params = [session_id, like_query]
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return rows

    def latest_stitched_for_session(self, session_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM stitched_assets
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return row
