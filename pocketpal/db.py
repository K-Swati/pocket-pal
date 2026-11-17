"""SQLite storage for staff accounts, settings, the audit log and usage metadata.

Privacy rule: nothing in here ever stores what people said. Usage events hold only metadata
(category, route, flags, provider, latency) and a salted hash of an anonymous device id.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('super_admin', 'admin', 'viewer')),
    pw_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    token_version INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_login REAL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor_id INTEGER,
    actor_email TEXT,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    device TEXT,
    category TEXT,
    route TEXT,
    flags TEXT,
    provider TEXT,
    latency_ms INTEGER
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocked_devices (
    device TEXT PRIMARY KEY,
    reason TEXT,
    blocked_by TEXT,
    ts REAL NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "off_topic_mode": "redirect",   # "redirect": allow light small talk, decline tasks. "strict": support conversation only.
    "classifier_enabled": True,     # second, model-based check on each message (in addition to the rules in code)
    "breathing_tool_enabled": True, # offer the guided breathing exercise when someone sounds anxious
    "max_reply_sentences": 4,
    "maintenance_message": "",      # when set, chat replies with this message instead of talking
}
SETTING_TYPES = {"off_topic_mode": str, "classifier_enabled": bool, "breathing_tool_enabled": bool,
                 "max_reply_sentences": int, "maintenance_message": str}


def default_path() -> str:
    data = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    data.mkdir(parents=True, exist_ok=True)
    return str(data / "pocketpal.db")


class DB:
    def __init__(self, path: Optional[str] = None):
        self.path = path or default_path()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> Optional[dict]:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def run(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return cur.lastrowid

    # ---- settings ----
    def settings(self) -> dict[str, Any]:
        out = dict(DEFAULT_SETTINGS)
        for r in self.q("SELECT key, value FROM settings"):
            if r["key"] in out:
                out[r["key"]] = json.loads(r["value"])
        return out

    def set_setting(self, key: str, value: Any) -> None:
        self.run("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))

    # ---- audit ----
    def audit(self, actor: Optional[dict], action: str, target: str = "", detail: Optional[dict] = None) -> None:
        self.run("INSERT INTO audit_log(ts, actor_id, actor_email, action, target, detail) VALUES (?,?,?,?,?,?)",
                 (time.time(), actor["id"] if actor else None, actor["email"] if actor else None, action, target,
                  json.dumps(detail or {})))

    # ---- usage metadata ----
    def event(self, kind: str, device: Optional[str], category: str = "", route: str = "", flags: tuple = (),
              provider: str = "", latency_ms: int = 0) -> None:
        self.run("INSERT INTO events(ts, kind, device, category, route, flags, provider, latency_ms) VALUES (?,?,?,?,?,?,?,?)",
                 (time.time(), kind, device, category, route, ",".join(flags), provider, latency_ms))

    def is_blocked(self, device: Optional[str]) -> bool:
        return bool(device) and self.one("SELECT 1 AS x FROM blocked_devices WHERE device = ?", (device,)) is not None
