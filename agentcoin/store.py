from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

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
                    required_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    locked_by TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    completed_at TEXT,
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
            self._ensure_column(conn, "tasks", "required_capabilities_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "tasks", "locked_by", "TEXT")
            self._ensure_column(conn, "tasks", "lease_token", "TEXT")
            self._ensure_column(conn, "tasks", "lease_expires_at", "TEXT")
            self._ensure_column(conn, "tasks", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tasks", "result_json", "TEXT")
            self._ensure_column(conn, "tasks", "completed_at", "TEXT")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def add_task(self, task: TaskEnvelope) -> None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks
                (id, kind, sender, priority, status, payload_json, required_capabilities_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.kind,
                    task.sender,
                    task.priority,
                    task.status,
                    json.dumps(task.payload, ensure_ascii=False),
                    json.dumps(task.required_capabilities, ensure_ascii=False),
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
                SELECT id, kind, sender, priority, status, payload_json, required_capabilities_json,
                       locked_by, lease_token, lease_expires_at, attempts, result_json, completed_at,
                       created_at, updated_at
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
                    "required_capabilities": json.loads(row["required_capabilities_json"] or "[]"),
                    "locked_by": row["locked_by"],
                    "lease_token": row["lease_token"],
                    "lease_expires_at": row["lease_expires_at"],
                    "attempts": row["attempts"],
                    "result": json.loads(row["result_json"]) if row["result_json"] else None,
                    "completed_at": row["completed_at"],
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
            queued_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'queued'").fetchone()[0]
            leased_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'leased'").fetchone()[0]
            completed_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'").fetchone()[0]
            inbox_count = conn.execute("SELECT COUNT(*) FROM inbox").fetchone()[0]
            outbox_pending = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'pending'").fetchone()[0]
            outbox_delivered = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'delivered'").fetchone()[0]
            peer_cards = conn.execute("SELECT COUNT(*) FROM peer_cards").fetchone()[0]
            return {
                "tasks": task_count,
                "tasks_queued": queued_tasks,
                "tasks_leased": leased_tasks,
                "tasks_completed": completed_tasks,
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

    def claim_task(
        self,
        worker_id: str,
        worker_capabilities: list[str] | None = None,
        lease_seconds: int = 60,
    ) -> dict[str, Any] | None:
        worker_capabilities = worker_capabilities or []
        now = utc_now()
        lease_expires_at = utc_after(lease_seconds)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id, kind, sender, priority, status, payload_json, required_capabilities_json,
                       locked_by, lease_token, lease_expires_at, attempts, result_json, completed_at,
                       created_at, updated_at
                FROM tasks
                WHERE status IN ('queued', 'leased')
                ORDER BY priority DESC, created_at ASC
                """
            ).fetchall()

            selected: sqlite3.Row | None = None
            for row in rows:
                required = json.loads(row["required_capabilities_json"] or "[]")
                lease_expired = not row["lease_expires_at"] or row["lease_expires_at"] <= now
                available = row["status"] == "queued" or lease_expired
                if not available:
                    continue
                if required and not set(required).issubset(set(worker_capabilities)):
                    continue
                selected = row
                break

            if not selected:
                conn.commit()
                return None

            lease_token = str(uuid4())
            conn.execute(
                """
                UPDATE tasks
                SET status = 'leased',
                    locked_by = ?,
                    lease_token = ?,
                    lease_expires_at = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (worker_id, lease_token, lease_expires_at, now, selected["id"]),
            )
            conn.commit()
            claimed = dict(selected)
            claimed["status"] = "leased"
            claimed["locked_by"] = worker_id
            claimed["lease_token"] = lease_token
            claimed["lease_expires_at"] = lease_expires_at
            claimed["attempts"] = int(selected["attempts"]) + 1
            return {
                "id": claimed["id"],
                "kind": claimed["kind"],
                "sender": claimed["sender"],
                "priority": claimed["priority"],
                "status": claimed["status"],
                "payload": json.loads(claimed["payload_json"]),
                "required_capabilities": json.loads(claimed["required_capabilities_json"] or "[]"),
                "locked_by": claimed["locked_by"],
                "lease_token": claimed["lease_token"],
                "lease_expires_at": claimed["lease_expires_at"],
                "attempts": claimed["attempts"],
                "created_at": claimed["created_at"],
                "updated_at": now,
            }
        finally:
            conn.close()

    def renew_task_lease(self, task_id: str, worker_id: str, lease_token: str, lease_seconds: int = 60) -> bool:
        conn = self._connect()
        try:
            updated = conn.execute(
                """
                UPDATE tasks
                SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                """,
                (utc_after(lease_seconds), utc_now(), task_id, worker_id, lease_token),
            ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()

    def ack_task(
        self,
        task_id: str,
        worker_id: str,
        lease_token: str,
        success: bool,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        requeue: bool = False,
    ) -> bool:
        now = utc_now()
        conn = self._connect()
        try:
            if success:
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'completed',
                        result_json = ?,
                        completed_at = ?,
                        locked_by = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                    """,
                    (json.dumps(result or {}, ensure_ascii=False), now, now, task_id, worker_id, lease_token),
                ).rowcount
            elif requeue:
                payload_update = {"error": error_message} if error_message else {}
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'queued',
                        result_json = ?,
                        locked_by = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                    """,
                    (json.dumps(payload_update, ensure_ascii=False), now, task_id, worker_id, lease_token),
                ).rowcount
            else:
                failure = {"error": error_message} if error_message else {"error": "task failed"}
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        result_json = ?,
                        completed_at = ?,
                        locked_by = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                    """,
                    (json.dumps(failure, ensure_ascii=False), now, now, task_id, worker_id, lease_token),
                ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()
