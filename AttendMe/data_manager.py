"""
Data persistence layer for AttendMe.

Uses SQLite for local storage and supports JSON export.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_FILENAME = "attendme.db"


# ── Database ──────────────────────────────────────────────────────────────────

class DataManager:
    """Manages SQLite storage for attention snapshots, whitelist, and ignore list."""

    def __init__(self, db_path: str | Path = DB_FILENAME):
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    # ── schema ────────────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                score       INTEGER NOT NULL,
                category    TEXT    NOT NULL,
                activity    TEXT    NOT NULL DEFAULT '',
                reasoning   TEXT    NOT NULL DEFAULT '',
                process     TEXT    NOT NULL DEFAULT '',
                window_title TEXT   NOT NULL DEFAULT '',
                ignored     INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_ts
                ON snapshots(timestamp);

            CREATE TABLE IF NOT EXISTS whitelist (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT NOT NULL,
                type    TEXT NOT NULL CHECK(type IN ('process', 'title')),
                UNIQUE(pattern, type)
            );

            CREATE TABLE IF NOT EXISTS ignore_list (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                process      TEXT    NOT NULL DEFAULT '',
                window_title TEXT    NOT NULL DEFAULT '',
                ignored_until TEXT   NOT NULL
            );
        """)
        self._conn.commit()

    # ── snapshots ─────────────────────────────────────────────────────────

    def add_snapshot(self, score: int, category: str, activity: str = "",
                     reasoning: str = "", process: str = "",
                     window_title: str = "", ignored: bool = False) -> int:
        cur = self._conn.execute(
            """INSERT INTO snapshots (score, category, activity, reasoning,
                                      process, window_title, ignored)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (score, category, activity, reasoning, process, window_title,
             int(ignored))
        )
        self._conn.commit()
        return cur.lastrowid

    def get_snapshots(self, since: datetime | None = None,
                      limit: int = 500) -> list[dict[str, Any]]:
        if since:
            rows = self._conn.execute(
                "SELECT * FROM snapshots WHERE timestamp >= ? ORDER BY id DESC LIMIT ?",
                (since.strftime("%Y-%m-%d %H:%M:%S"), limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM snapshots ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_recent_scores(self, minutes: int) -> list[dict[str, Any]]:
        since = datetime.now() - timedelta(minutes=minutes)
        return self.get_snapshots(since=since, limit=9999)

    # ── statistics ────────────────────────────────────────────────────────

    def get_today_stats(self) -> dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        row = self._conn.execute(
            """SELECT
                 COUNT(*)                          AS total_snapshots,
                 COALESCE(AVG(score), 0)           AS avg_score,
                 COALESCE(SUM(CASE WHEN score>=80 THEN 1 ELSE 0 END), 0) AS high_count,
                 COALESCE(SUM(CASE WHEN score>=40 AND score<80 THEN 1 ELSE 0 END), 0) AS mid_count,
                 COALESCE(SUM(CASE WHEN score<40 THEN 1 ELSE 0 END), 0)  AS low_count
               FROM snapshots
               WHERE timestamp >= ?""",
            (today,)
        ).fetchone()

        total = row["total_snapshots"] or 0
        # Count interruptions: transitions from high(>=80) to low(<40) between
        # consecutive snapshots
        interrupt_count = 0
        if total >= 2:
            scores = [r["score"] for r in self._conn.execute(
                "SELECT score FROM snapshots WHERE timestamp >= ? ORDER BY id",
                (today,)
            ).fetchall()]
            for i in range(1, len(scores)):
                if scores[i - 1] >= 80 and scores[i] < 40:
                    interrupt_count += 1

        # Approximate focus time: each snapshot represents ~4 seconds
        high_minutes = round(row["high_count"] * 4 / 60, 1)

        return {
            "total_snapshots": total,
            "avg_score": round(row["avg_score"], 1),
            "high_count": row["high_count"],
            "mid_count": row["mid_count"],
            "low_count": row["low_count"],
            "focus_minutes": high_minutes,
            "interruptions": interrupt_count,
        }

    def get_category_distribution(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT process, COUNT(*) AS cnt, AVG(score) AS avg_s
               FROM snapshots
               WHERE timestamp >= date('now', 'localtime')
                 AND process != ''
               GROUP BY process
               ORDER BY cnt DESC
               LIMIT 10"""
        ).fetchall()
        return [{"process": r["process"], "count": r["cnt"],
                 "avg_score": round(r["avg_s"], 1)} for r in rows]

    # ── whitelist ─────────────────────────────────────────────────────────

    def get_whitelist(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM whitelist").fetchall()
        return [dict(r) for r in rows]

    def add_whitelist(self, pattern: str, wl_type: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO whitelist (pattern, type) VALUES (?, ?)",
            (pattern, wl_type)
        )
        self._conn.commit()

    def remove_whitelist(self, pattern: str, wl_type: str) -> None:
        self._conn.execute(
            "DELETE FROM whitelist WHERE pattern=? AND type=?", (pattern, wl_type)
        )
        self._conn.commit()

    def is_whitelisted(self, process: str, window_title: str) -> bool:
        rows = self._conn.execute("SELECT pattern, type FROM whitelist").fetchall()
        for r in rows:
            target = process if r["type"] == "process" else window_title
            if r["pattern"].lower() in target.lower():
                return True
        return False

    # ── ignore list ───────────────────────────────────────────────────────

    def add_ignore(self, process: str, window_title: str,
                   duration_minutes: int = 5) -> None:
        until = datetime.now() + timedelta(minutes=duration_minutes)
        self._conn.execute(
            "INSERT INTO ignore_list (process, window_title, ignored_until) VALUES (?, ?, ?)",
            (process, window_title, until.strftime("%Y-%m-%d %H:%M:%S"))
        )
        self._conn.commit()

    def is_ignored(self, process: str, window_title: str) -> bool:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = self._conn.execute(
            """SELECT id FROM ignore_list
               WHERE process=? AND window_title=? AND ignored_until > ?""",
            (process, window_title, now)
        ).fetchone()
        return row is not None

    def cleanup_expired_ignores(self) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute("DELETE FROM ignore_list WHERE ignored_until <= ?", (now,))
        self._conn.commit()

    # ── export ────────────────────────────────────────────────────────────

    def export_json(self, filepath: str | Path) -> str:
        rows = self._conn.execute("SELECT * FROM snapshots ORDER BY id").fetchall()
        data = [dict(r) for r in rows]
        path = Path(filepath)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return str(path.resolve())

    def close(self) -> None:
        self._conn.close()
