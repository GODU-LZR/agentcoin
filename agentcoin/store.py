from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agentcoin.models import TaskEnvelope, utc_after, utc_now


class NodeStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inbox (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY,
                    target_url TEXT NOT NULL,
                    auth_token TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS peer_cards (
                    peer_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def add_task(self, task: TaskEnvelope) -> None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks
                (id, kind, sender, priority, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.kind,
                    task.sender,
                    task.priority,
                    task.status,
                    json.dumps(task.payload, ensure_ascii=False),
                    task.created_at,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, kind, sender, priority, status, payload_json, created_at, updated_at
                FROM tasks
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "sender": row["sender"],
                    "priority": row["priority"],
                    "status": row["status"],
                    "payload": json.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def receive_inbox(self, sender: str, payload: dict[str, Any]) -> str:
        message_id = str(payload.get("id") or f"inbox-{utc_now()}")
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO inbox (id, sender, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, sender, json.dumps(payload, ensure_ascii=False), utc_now()),
            )
            conn.commit()
            return message_id
        finally:
            conn.close()

    def queue_outbox(self, message_id: str, target_url: str, auth_token: str | None, payload: dict[str, Any]) -> None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO outbox
                (id, target_url, auth_token, payload_json, status, attempts, next_attempt_at, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', 0, ?, NULL, ?, ?)
                """,
                (message_id, target_url, auth_token, json.dumps(payload, ensure_ascii=False), now, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def get_pending_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM outbox
                WHERE status = 'pending'
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC
                LIMIT ?
                """,
                (utc_now(), limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def mark_outbox_delivered(self, message_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE outbox SET status = 'delivered', updated_at = ? WHERE id = ?",
                (utc_now(), message_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_outbox_failed(self, message_id: str, attempts: int, error: str) -> None:
        delay_seconds = min(2 ** min(attempts, 6), 60)
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE outbox
                SET attempts = ?, last_error = ?, next_attempt_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (attempts, error[:500], utc_after(delay_seconds), utc_now(), message_id),
            )
            conn.commit()
        finally:
            conn.close()

    def stats(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            inbox_count = conn.execute("SELECT COUNT(*) FROM inbox").fetchone()[0]
            outbox_pending = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'pending'").fetchone()[0]
            outbox_delivered = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'delivered'").fetchone()[0]
            peer_cards = conn.execute("SELECT COUNT(*) FROM peer_cards").fetchone()[0]
            return {
                "tasks": task_count,
                "inbox": inbox_count,
                "outbox_pending": outbox_pending,
                "outbox_delivered": outbox_delivered,
                "peer_cards": peer_cards,
            }
        finally:
            conn.close()

    def save_peer_card(self, peer_id: str, source_url: str, card: dict[str, Any]) -> None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO peer_cards
                (peer_id, source_url, card_json, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (peer_id, source_url, json.dumps(card, ensure_ascii=False), now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def list_peer_cards(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT peer_id, source_url, card_json, fetched_at, updated_at
                FROM peer_cards
                ORDER BY peer_id ASC
                """
            ).fetchall()
            return [
                {
                    "peer_id": row["peer_id"],
                    "source_url": row["source_url"],
                    "card": json.loads(row["card_json"]),
                    "fetched_at": row["fetched_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()
