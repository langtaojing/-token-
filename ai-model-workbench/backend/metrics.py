"""Real usage and connectivity measurements for the admin dashboard."""

from __future__ import annotations

import math
import socket
import statistics
from datetime import timedelta
from time import perf_counter
from urllib.parse import urlparse

from .store import connect, now, today


def usage_snapshot() -> dict:
    since = (now() - timedelta(hours=24)).isoformat()
    with connect() as db:
        users = db.execute("SELECT COUNT(*) AS n FROM users WHERE active = 1").fetchone()["n"]
        rows = db.execute(
            """SELECT c.status, c.total_tokens, c.latency_ms, c.model, c.created_at, u.username
               FROM calls c JOIN users u ON u.id = c.user_id
               WHERE c.created_at >= ? ORDER BY c.id DESC""",
            (since,),
        ).fetchall()
        per_user = db.execute(
            """SELECT u.username, u.daily_requests, u.daily_tokens,
                      COUNT(c.id) AS requests, COALESCE(SUM(c.total_tokens), 0) AS tokens
               FROM users u LEFT JOIN calls c ON c.user_id = u.id AND c.day = ? AND c.status = 'success'
               WHERE u.active = 1 GROUP BY u.id ORDER BY tokens DESC""",
            (today(),),
        ).fetchall()
    values = sorted(row["latency_ms"] for row in rows if row["status"] == "success" and row["latency_ms"] > 0)
    p95 = values[math.ceil(len(values) * 0.95) - 1] if values else None
    return {
        "active_users": users,
        "last_24h": {
            "calls": len(rows),
            "success": sum(row["status"] == "success" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows),
            "pending": sum(row["status"] == "pending" for row in rows),
            "tokens": sum(row["total_tokens"] for row in rows if row["status"] == "success"),
            "avg_latency_ms": round(statistics.mean(values)) if values else None,
            "p95_latency_ms": p95,
            "latency_samples": len(values),
        },
        "per_user_today": [dict(row) for row in per_user],
        "recent_calls": [dict(row) for row in rows[:20]],
    }


def tcp_probe(target_url: str, attempts: int = 5) -> dict:
    parsed = urlparse(target_url)
    host = parsed.hostname
    if not host:
        return {"status": "unconfigured", "attempts": 0, "failed": 0, "avg_connect_ms": None}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    samples: list[float] = []
    failed = 0
    for _ in range(attempts):
        started = perf_counter()
        try:
            with socket.create_connection((host, port), timeout=3):
                samples.append((perf_counter() - started) * 1000)
        except OSError:
            failed += 1
    return {
        "status": "ok" if failed == 0 else "degraded" if failed < attempts else "down",
        "target": host,
        "attempts": attempts,
        "failed": failed,
        "probe_failure_rate_pct": round(failed * 100 / attempts, 1),
        "avg_connect_ms": round(statistics.mean(samples)) if samples else None,
        "note": "TCP 连通探测失败率，不是网络层丢包率",
    }


def initialize_samples() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS network_samples (
            id INTEGER PRIMARY KEY, sampled_at TEXT NOT NULL,
            target TEXT NOT NULL, attempts INTEGER NOT NULL,
            failed INTEGER NOT NULL, avg_connect_ms INTEGER,
            status TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_network_samples_time ON network_samples(sampled_at)")


def save_network_sample(target_url: str) -> dict:
    initialize_samples()
    result = tcp_probe(target_url)
    with connect() as db:
        db.execute(
            """INSERT INTO network_samples(sampled_at,target,attempts,failed,avg_connect_ms,status)
               VALUES(?,?,?,?,?,?)""",
            (now().isoformat(), result.get("target", ""), result["attempts"], result["failed"], result["avg_connect_ms"], result["status"]),
        )
        db.execute("DELETE FROM network_samples WHERE sampled_at < ?", ((now() - timedelta(days=30)).isoformat(),))
    return result


def network_history(limit: int = 48) -> list[dict]:
    initialize_samples()
    with connect() as db:
        rows = db.execute(
            """SELECT sampled_at,target,attempts,failed,avg_connect_ms,status
               FROM network_samples ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]
