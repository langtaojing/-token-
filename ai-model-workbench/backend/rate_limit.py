"""Small SQLite backed rate limiter for public authentication endpoints."""

from __future__ import annotations

import sqlite3
import time

from .store import connect


def initialize() -> None:
    with connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY, client_ip TEXT NOT NULL,
            action TEXT NOT NULL, created_at INTEGER NOT NULL
            )"""
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_auth_attempts ON auth_attempts(client_ip, action, created_at)")


def check_and_record(client_ip: str, action: str, limit: int, window_seconds: int = 3600) -> bool:
    now = int(time.time())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM auth_attempts WHERE created_at < ?", (now - window_seconds,))
        count = db.execute(
            "SELECT COUNT(*) FROM auth_attempts WHERE client_ip = ? AND action = ? AND created_at >= ?",
            (client_ip, action, now - window_seconds),
        ).fetchone()[0]
        if count >= limit:
            return False
        db.execute("INSERT INTO auth_attempts(client_ip, action, created_at) VALUES (?, ?, ?)", (client_ip, action, now))
    return True
