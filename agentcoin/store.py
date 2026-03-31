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
                    workflow_id TEXT,
                    parent_task_id TEXT,
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    role TEXT NOT NULL DEFAULT 'worker',
                    branch TEXT NOT NULL DEFAULT 'main',
                    revision INTEGER NOT NULL DEFAULT 1,
                    merge_parent_ids_json TEXT NOT NULL DEFAULT '[]',
                    commit_message TEXT NOT NULL DEFAULT '',
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
                    acked INTEGER NOT NULL DEFAULT 0,
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
                CREATE TABLE IF NOT EXISTS delivery_receipts (
                    ack_id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS peer_cards (
                    peer_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_states (
                    workflow_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    finalized_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "tasks", "required_capabilities_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "tasks", "workflow_id", "TEXT")
            self._ensure_column(conn, "tasks", "parent_task_id", "TEXT")
            self._ensure_column(conn, "tasks", "depends_on_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "tasks", "role", "TEXT NOT NULL DEFAULT 'worker'")
            self._ensure_column(conn, "tasks", "branch", "TEXT NOT NULL DEFAULT 'main'")
            self._ensure_column(conn, "tasks", "revision", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "tasks", "merge_parent_ids_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "tasks", "commit_message", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "tasks", "locked_by", "TEXT")
            self._ensure_column(conn, "tasks", "lease_token", "TEXT")
            self._ensure_column(conn, "tasks", "lease_expires_at", "TEXT")
            self._ensure_column(conn, "tasks", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tasks", "result_json", "TEXT")
            self._ensure_column(conn, "tasks", "completed_at", "TEXT")
            self._ensure_column(conn, "inbox", "acked", "INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "sender": row["sender"],
            "priority": row["priority"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]),
            "required_capabilities": json.loads(row["required_capabilities_json"] or "[]"),
            "workflow_id": row["workflow_id"],
            "parent_task_id": row["parent_task_id"],
            "depends_on": json.loads(row["depends_on_json"] or "[]"),
            "role": row["role"],
            "branch": row["branch"],
            "revision": row["revision"],
            "merge_parent_ids": json.loads(row["merge_parent_ids_json"] or "[]"),
            "commit_message": row["commit_message"],
            "locked_by": row["locked_by"],
            "lease_token": row["lease_token"],
            "lease_expires_at": row["lease_expires_at"],
            "attempts": row["attempts"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

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
                (id, kind, sender, priority, status, payload_json, required_capabilities_json,
                 workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                 merge_parent_ids_json, commit_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.kind,
                    task.sender,
                    task.priority,
                    task.status,
                    json.dumps(task.payload, ensure_ascii=False),
                    json.dumps(task.required_capabilities, ensure_ascii=False),
                    task.workflow_id,
                    task.parent_task_id,
                    json.dumps(task.depends_on, ensure_ascii=False),
                    task.role,
                    task.branch,
                    task.revision,
                    json.dumps(task.merge_parent_ids, ensure_ascii=False),
                    task.commit_message,
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
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, result_json, completed_at,
                       created_at, updated_at
                FROM tasks
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._task_from_row(row) for row in rows]
        finally:
            conn.close()

    def receive_inbox(self, sender: str, payload: dict[str, Any]) -> tuple[str, bool]:
        message_id = str(payload.get("id") or f"inbox-{utc_now()}")
        conn = self._connect()
        try:
            existing = conn.execute("SELECT id FROM inbox WHERE id = ?", (message_id,)).fetchone()
            duplicate = existing is not None
            conn.execute(
                """
                INSERT OR REPLACE INTO inbox (id, sender, payload_json, acked, created_at)
                VALUES (?, ?, ?, COALESCE((SELECT acked FROM inbox WHERE id = ?), 0), ?)
                """,
                (message_id, sender, json.dumps(payload, ensure_ascii=False), message_id, utc_now()),
            )
            conn.commit()
            return message_id, duplicate
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

    def save_delivery_receipt(self, ack_id: str, message_id: str, sender: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO delivery_receipts (ack_id, message_id, sender, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (ack_id, message_id, sender, utc_now()),
            )
            conn.execute("UPDATE inbox SET acked = 1 WHERE id = ?", (message_id,))
            conn.commit()
        finally:
            conn.close()

    def has_delivery_receipt(self, ack_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM delivery_receipts WHERE ack_id = ?", (ack_id,)).fetchone()
            return row is not None
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
            inbox_acked = conn.execute("SELECT COUNT(*) FROM inbox WHERE acked = 1").fetchone()[0]
            outbox_pending = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'pending'").fetchone()[0]
            outbox_delivered = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'delivered'").fetchone()[0]
            delivery_receipts = conn.execute("SELECT COUNT(*) FROM delivery_receipts").fetchone()[0]
            peer_cards = conn.execute("SELECT COUNT(*) FROM peer_cards").fetchone()[0]
            workflow_states = conn.execute("SELECT COUNT(*) FROM workflow_states").fetchone()[0]
            return {
                "tasks": task_count,
                "tasks_queued": queued_tasks,
                "tasks_leased": leased_tasks,
                "tasks_completed": completed_tasks,
                "inbox": inbox_count,
                "inbox_acked": inbox_acked,
                "outbox_pending": outbox_pending,
                "outbox_delivered": outbox_delivered,
                "delivery_receipts": delivery_receipts,
                "peer_cards": peer_cards,
                "workflow_states": workflow_states,
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

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, kind, sender, priority, status, payload_json, required_capabilities_json,
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, result_json, completed_at,
                       created_at, updated_at
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            if not row:
                return None
            return self._task_from_row(row)
        finally:
            conn.close()

    def list_workflow_tasks(self, workflow_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, kind, sender, priority, status, payload_json, required_capabilities_json,
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, result_json, completed_at,
                       created_at, updated_at
                FROM tasks
                WHERE workflow_id = ?
                ORDER BY revision ASC, created_at ASC
                """,
                (workflow_id,),
            ).fetchall()
            return [self._task_from_row(row) for row in rows]
        finally:
            conn.close()

    def create_subtasks(self, parent_task_id: str, subtasks: list[TaskEnvelope]) -> list[dict[str, Any]]:
        parent = self.get_task(parent_task_id)
        if not parent:
            raise ValueError("parent task not found")
        workflow_id = parent["workflow_id"] or parent["id"]
        created: list[dict[str, Any]] = []
        for task in subtasks:
            if not task.workflow_id:
                task.workflow_id = workflow_id
            task.parent_task_id = parent_task_id
            if task.revision <= 1:
                task.revision = int(parent["revision"]) + 1
            if not task.commit_message:
                task.commit_message = f"spawn subtask from {parent_task_id}"
            self.add_task(task)
            created_task = self.get_task(task.id)
            if created_task:
                created.append(created_task)
        if parent["status"] in {"queued", "leased"}:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'completed',
                        result_json = ?,
                        completed_at = ?,
                        locked_by = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(
                            {
                                "fanout_count": len(created),
                                "spawned_task_ids": [task["id"] for task in created],
                            },
                            ensure_ascii=False,
                        ),
                        utc_now(),
                        utc_now(),
                        parent_task_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return created

    def create_merge_task(
        self,
        workflow_id: str,
        parent_task_ids: list[str],
        task: TaskEnvelope,
    ) -> dict[str, Any]:
        unique_parent_ids = list(dict.fromkeys(str(task_id) for task_id in parent_task_ids if str(task_id).strip()))
        if len(unique_parent_ids) < 2:
            raise ValueError("at least two parent_task_ids are required for merge")

        parents = self.list_workflow_tasks(workflow_id)
        parent_map = {item["id"]: item for item in parents}
        missing = [task_id for task_id in unique_parent_ids if task_id not in parent_map]
        if missing:
            raise ValueError(f"merge parents not found in workflow: {', '.join(missing)}")

        if not task.workflow_id:
            task.workflow_id = workflow_id
        task.parent_task_id = task.parent_task_id or unique_parent_ids[0]
        if not task.depends_on:
            task.depends_on = list(unique_parent_ids)
        task.merge_parent_ids = list(unique_parent_ids)
        if task.revision <= 1:
            task.revision = max(int(parent_map[item]["revision"]) for item in unique_parent_ids) + 1
        if not task.commit_message:
            task.commit_message = f"merge {', '.join(unique_parent_ids)} into {task.branch}"
        self.add_task(task)
        created = self.get_task(task.id)
        if not created:
            raise ValueError("failed to persist merge task")
        return created

    def summarize_workflow(self, workflow_id: str) -> dict[str, Any]:
        tasks = self.list_workflow_tasks(workflow_id)
        if not tasks:
            raise ValueError("workflow not found")

        status_counts: dict[str, int] = {}
        role_counts: dict[str, int] = {}
        branch_counts: dict[str, int] = {}
        consumed_task_ids: set[str] = set()
        ready_ids: list[str] = []
        blocked_ids: list[str] = []
        merge_task_ids: list[str] = []
        failed_ids: list[str] = []

        completed_ids = {task["id"] for task in tasks if task["status"] == "completed"}
        for task in tasks:
            status = str(task["status"] or "unknown")
            role = str(task["role"] or "worker")
            branch = str(task["branch"] or "main")
            status_counts[status] = status_counts.get(status, 0) + 1
            role_counts[role] = role_counts.get(role, 0) + 1
            branch_counts[branch] = branch_counts.get(branch, 0) + 1

            if task.get("parent_task_id"):
                consumed_task_ids.add(str(task["parent_task_id"]))
            for dep in task.get("depends_on", []):
                consumed_task_ids.add(str(dep))
            for merge_parent in task.get("merge_parent_ids", []):
                consumed_task_ids.add(str(merge_parent))

            if task.get("merge_parent_ids"):
                merge_task_ids.append(task["id"])
            if status == "failed":
                failed_ids.append(task["id"])

            if status == "queued":
                depends_on = set(task.get("depends_on", []))
                if depends_on.issubset(completed_ids):
                    ready_ids.append(task["id"])
                elif depends_on:
                    blocked_ids.append(task["id"])

        leaf_task_ids = [task["id"] for task in tasks if task["id"] not in consumed_task_ids]
        root_task_ids = [task["id"] for task in tasks if not task.get("parent_task_id") and not task.get("merge_parent_ids")]
        open_tasks = status_counts.get("queued", 0) + status_counts.get("leased", 0)
        terminal = open_tasks == 0
        final_status = "active"
        if terminal:
            final_status = "failed" if failed_ids else "completed"

        persisted_state = self.get_workflow_state(workflow_id)

        return {
            "workflow_id": workflow_id,
            "task_count": len(tasks),
            "root_task_ids": root_task_ids,
            "leaf_task_ids": leaf_task_ids,
            "ready_task_ids": ready_ids,
            "blocked_task_ids": blocked_ids,
            "merge_task_ids": merge_task_ids,
            "failed_task_ids": failed_ids,
            "status_counts": status_counts,
            "role_counts": role_counts,
            "branch_counts": branch_counts,
            "latest_revision": max(int(task["revision"]) for task in tasks),
            "finalizable": terminal,
            "status": final_status,
            "persisted_state": persisted_state,
        }

    def get_workflow_state(self, workflow_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT workflow_id, status, summary_json, finalized_at, created_at, updated_at
                FROM workflow_states
                WHERE workflow_id = ?
                """,
                (workflow_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "workflow_id": row["workflow_id"],
                "status": row["status"],
                "summary": json.loads(row["summary_json"]),
                "finalized_at": row["finalized_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    def finalize_workflow(self, workflow_id: str) -> dict[str, Any]:
        summary = self.summarize_workflow(workflow_id)
        if not summary["finalizable"]:
            return {"ok": False, "workflow_id": workflow_id, "summary": summary}

        now = utc_now()
        final_status = str(summary["status"])
        summary_payload = dict(summary)
        summary_payload["persisted_state"] = None

        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT created_at FROM workflow_states WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT OR REPLACE INTO workflow_states
                (workflow_id, status, summary_json, finalized_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (workflow_id, final_status, json.dumps(summary_payload, ensure_ascii=False), now, created_at, now),
            )
            conn.commit()
        finally:
            conn.close()

        finalized_state = self.get_workflow_state(workflow_id)
        return {
            "ok": True,
            "workflow_id": workflow_id,
            "status": final_status,
            "finalized_at": now,
            "summary": {**summary, "persisted_state": finalized_state},
        }

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
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
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
                depends_on = json.loads(row["depends_on_json"] or "[]")
                lease_expired = not row["lease_expires_at"] or row["lease_expires_at"] <= now
                available = row["status"] == "queued" or lease_expired
                if not available:
                    continue
                role = row["role"] or "worker"
                if worker_capabilities and role not in {"any", ""} and role not in set(worker_capabilities):
                    continue
                if required and not set(required).issubset(set(worker_capabilities)):
                    continue
                if depends_on:
                    dependency_count = conn.execute(
                        """
                        SELECT COUNT(*) FROM tasks
                        WHERE id IN ({})
                          AND status = 'completed'
                        """.format(",".join("?" for _ in depends_on)),
                        tuple(depends_on),
                    ).fetchone()[0]
                    if dependency_count != len(depends_on):
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
                "workflow_id": claimed["workflow_id"],
                "parent_task_id": claimed["parent_task_id"],
                "depends_on": json.loads(claimed["depends_on_json"] or "[]"),
                "role": claimed["role"],
                "branch": claimed["branch"],
                "revision": claimed["revision"],
                "merge_parent_ids": json.loads(claimed["merge_parent_ids_json"] or "[]"),
                "commit_message": claimed["commit_message"],
                "locked_by": claimed["locked_by"],
                "lease_token": claimed["lease_token"],
                "lease_expires_at": claimed["lease_expires_at"],
                "attempts": claimed["attempts"],
                "result": json.loads(claimed["result_json"]) if claimed["result_json"] else None,
                "completed_at": claimed["completed_at"],
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
