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
                    deliver_to TEXT,
                    delivery_status TEXT NOT NULL DEFAULT 'local',
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
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    retry_backoff_seconds INTEGER NOT NULL DEFAULT 5,
                    available_at TEXT NOT NULL,
                    last_error TEXT,
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
                    task_id TEXT,
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
            self._ensure_column(conn, "tasks", "deliver_to", "TEXT")
            self._ensure_column(conn, "tasks", "delivery_status", "TEXT NOT NULL DEFAULT 'local'")
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
            self._ensure_column(conn, "tasks", "max_attempts", "INTEGER NOT NULL DEFAULT 3")
            self._ensure_column(conn, "tasks", "retry_backoff_seconds", "INTEGER NOT NULL DEFAULT 5")
            self._ensure_column(conn, "tasks", "available_at", "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'")
            self._ensure_column(conn, "tasks", "last_error", "TEXT")
            self._ensure_column(conn, "tasks", "result_json", "TEXT")
            self._ensure_column(conn, "tasks", "completed_at", "TEXT")
            self._ensure_column(conn, "inbox", "acked", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "outbox", "task_id", "TEXT")
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
            "deliver_to": row["deliver_to"],
            "delivery_status": row["delivery_status"],
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
            "max_attempts": row["max_attempts"],
            "retry_backoff_seconds": row["retry_backoff_seconds"],
            "available_at": row["available_at"],
            "last_error": row["last_error"],
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
                (id, kind, sender, priority, status, deliver_to, delivery_status, payload_json, required_capabilities_json,
                 workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                 merge_parent_ids_json, commit_message, max_attempts, retry_backoff_seconds, available_at, last_error,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.kind,
                    task.sender,
                    task.priority,
                    task.status,
                    task.deliver_to,
                    task.delivery_status,
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
                    task.max_attempts,
                    task.retry_backoff_seconds,
                    task.available_at,
                    task.last_error,
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
                       deliver_to, delivery_status,
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, max_attempts, retry_backoff_seconds,
                       available_at, last_error, result_json, completed_at,
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

    def queue_outbox(
        self,
        message_id: str,
        target_url: str,
        auth_token: str | None,
        payload: dict[str, Any],
        task_id: str | None = None,
    ) -> None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO outbox
                (id, target_url, auth_token, task_id, payload_json, status, attempts, next_attempt_at, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, ?)
                """,
                (message_id, target_url, auth_token, task_id, json.dumps(payload, ensure_ascii=False), now, now, now),
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
                WHERE status IN ('pending', 'retrying')
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
            now = utc_now()
            row = conn.execute("SELECT task_id FROM outbox WHERE id = ?", (message_id,)).fetchone()
            conn.execute("UPDATE outbox SET status = 'delivered', updated_at = ? WHERE id = ?", (now, message_id))
            if row and row["task_id"]:
                conn.execute(
                    """
                    UPDATE tasks
                    SET delivery_status = 'remote-accepted',
                        last_error = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, row["task_id"]),
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

    def mark_outbox_failed(self, message_id: str, attempts: int, error: str, max_attempts: int) -> bool:
        delay_seconds = min(2 ** min(attempts, 6), 60)
        conn = self._connect()
        try:
            now = utc_now()
            status = "dead-letter" if attempts >= max_attempts else "retrying"
            conn.execute(
                """
                UPDATE outbox
                SET attempts = ?, status = ?, last_error = ?, next_attempt_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (attempts, status, error[:500], utc_after(delay_seconds), now, message_id),
            )
            conn.commit()
            return status == "dead-letter"
        finally:
            conn.close()

    def list_outbox(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM outbox
                    WHERE status = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM outbox
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def requeue_outbox(self, message_id: str, delay_seconds: int = 0) -> bool:
        conn = self._connect()
        try:
            updated = conn.execute(
                """
                UPDATE outbox
                SET status = 'pending', next_attempt_at = ?, updated_at = ?
                WHERE id = ? AND status = 'dead-letter'
                """,
                (utc_after(delay_seconds), utc_now(), message_id),
            ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()

    def stats(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            queued_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'queued'").fetchone()[0]
            leased_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'leased'").fetchone()[0]
            completed_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'").fetchone()[0]
            dead_letter_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'dead-letter'").fetchone()[0]
            inbox_count = conn.execute("SELECT COUNT(*) FROM inbox").fetchone()[0]
            inbox_acked = conn.execute("SELECT COUNT(*) FROM inbox WHERE acked = 1").fetchone()[0]
            outbox_pending = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'pending'").fetchone()[0]
            outbox_retrying = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'retrying'").fetchone()[0]
            outbox_delivered = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'delivered'").fetchone()[0]
            outbox_dead_letter = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'dead-letter'").fetchone()[0]
            delivery_receipts = conn.execute("SELECT COUNT(*) FROM delivery_receipts").fetchone()[0]
            peer_cards = conn.execute("SELECT COUNT(*) FROM peer_cards").fetchone()[0]
            workflow_states = conn.execute("SELECT COUNT(*) FROM workflow_states").fetchone()[0]
            return {
                "tasks": task_count,
                "tasks_queued": queued_tasks,
                "tasks_leased": leased_tasks,
                "tasks_completed": completed_tasks,
                "tasks_dead_letter": dead_letter_tasks,
                "inbox": inbox_count,
                "inbox_acked": inbox_acked,
                "outbox_pending": outbox_pending,
                "outbox_retrying": outbox_retrying,
                "outbox_delivered": outbox_delivered,
                "outbox_dead_letter": outbox_dead_letter,
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
                       deliver_to, delivery_status,
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, max_attempts, retry_backoff_seconds,
                       available_at, last_error, result_json, completed_at,
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

    def update_task_payload(self, task_id: str, payload: dict[str, Any]) -> bool:
        conn = self._connect()
        try:
            updated = conn.execute(
                """
                UPDATE tasks
                SET payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(payload, ensure_ascii=False), utc_now(), task_id),
            ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()

    def list_workflow_tasks(self, workflow_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, kind, sender, priority, status, payload_json, required_capabilities_json,
                       deliver_to, delivery_status,
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, max_attempts, retry_backoff_seconds,
                       available_at, last_error, result_json, completed_at,
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
        merge_policy = dict(task.payload.get("_merge_policy") or {})
        if merge_policy:
            protected_branches = [str(item) for item in list(merge_policy.get("protected_branches") or []) if str(item).strip()]
            merge_policy["protected_branches"] = protected_branches
            merge_policy["required_approvals_per_branch"] = max(1, int(merge_policy.get("required_approvals_per_branch") or 1))
            merge_policy["protected_parent_ids"] = [
                parent_id for parent_id in unique_parent_ids if parent_map[parent_id]["branch"] in set(protected_branches)
            ]
            task.payload["_merge_policy"] = merge_policy
        if task.revision <= 1:
            task.revision = max(int(parent_map[item]["revision"]) for item in unique_parent_ids) + 1
        if not task.commit_message:
            task.commit_message = f"merge {', '.join(unique_parent_ids)} into {task.branch}"
        self.add_task(task)
        created = self.get_task(task.id)
        if not created:
            raise ValueError("failed to persist merge task")
        return created

    def create_review_tasks(self, workflow_id: str, reviews: list[TaskEnvelope]) -> list[dict[str, Any]]:
        tasks = self.list_workflow_tasks(workflow_id)
        if not tasks:
            raise ValueError("workflow not found")
        task_map = {item["id"]: item for item in tasks}
        created: list[dict[str, Any]] = []
        for review in reviews:
            review_meta = dict(review.payload.get("_review") or {})
            target_task_id = str(review_meta.get("target_task_id") or "").strip()
            if not target_task_id:
                raise ValueError("review task requires payload._review.target_task_id")
            if target_task_id not in task_map:
                raise ValueError(f"review target not found in workflow: {target_task_id}")

            target = task_map[target_task_id]
            review.workflow_id = workflow_id
            review.role = review.role or "reviewer"
            review.parent_task_id = review.parent_task_id or target_task_id
            if not review.depends_on:
                review.depends_on = [target_task_id]
            if review.revision <= 1:
                review.revision = int(target["revision"]) + 1
            if not review.branch:
                review.branch = f"review/{target['branch']}"
            review_meta.setdefault("target_task_id", target_task_id)
            review_meta.setdefault("target_branch", target["branch"])
            review_meta.setdefault("target_revision", target["revision"])
            reviewer_type = str(review_meta.get("reviewer_type") or "human").strip().lower()
            if reviewer_type not in {"human", "ai"}:
                raise ValueError("reviewer_type must be 'human' or 'ai'")
            review_meta["reviewer_type"] = reviewer_type
            review.payload["_review"] = review_meta
            if target.get("payload", {}).get("_git") and "_git" not in review.payload:
                review.payload["_git"] = dict(target["payload"]["_git"])
            if not review.commit_message:
                review.commit_message = f"review {target_task_id} on {target['branch']}"
            self.add_task(review)
            created_review = self.get_task(review.id)
            if created_review:
                created.append(created_review)
        return created

    @staticmethod
    def _review_approval_index(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        approvals: dict[str, dict[str, Any]] = {}
        for task in tasks:
            review_meta = dict(task.get("payload", {}).get("_review") or {})
            target_task_id = str(review_meta.get("target_task_id") or "").strip()
            if not target_task_id:
                continue
            entry = approvals.setdefault(
                target_task_id,
                {
                    "target_branch": review_meta.get("target_branch"),
                    "review_task_ids": [],
                    "approved_review_task_ids": [],
                    "rejected_review_task_ids": [],
                    "pending_review_task_ids": [],
                    "approved_by_type": {"human": [], "ai": []},
                    "rejected_by_type": {"human": [], "ai": []},
                    "pending_by_type": {"human": [], "ai": []},
                },
            )
            entry["review_task_ids"].append(task["id"])
            reviewer_type = str(review_meta.get("reviewer_type") or "human").strip().lower()
            if reviewer_type not in {"human", "ai"}:
                reviewer_type = "human"
            if task["status"] == "completed":
                approved = bool((task.get("result") or {}).get("approved"))
                if approved:
                    entry["approved_review_task_ids"].append(task["id"])
                    entry["approved_by_type"][reviewer_type].append(task["id"])
                else:
                    entry["rejected_review_task_ids"].append(task["id"])
                    entry["rejected_by_type"][reviewer_type].append(task["id"])
            elif task["status"] in {"queued", "leased"}:
                entry["pending_review_task_ids"].append(task["id"])
                entry["pending_by_type"][reviewer_type].append(task["id"])
        return approvals

    @classmethod
    def _merge_policy_status_for_task(cls, merge_task: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        merge_policy = dict(merge_task.get("payload", {}).get("_merge_policy") or {})
        if not merge_policy:
            return None

        task_map = {item["id"]: item for item in tasks}
        approval_index = cls._review_approval_index(tasks)
        protected_branches = [str(item) for item in list(merge_policy.get("protected_branches") or []) if str(item).strip()]
        required_approvals = max(0, int(merge_policy.get("required_approvals_per_branch") or 0))
        required_human = max(0, int(merge_policy.get("required_human_approvals_per_branch") or 0))
        required_ai = max(0, int(merge_policy.get("required_ai_approvals_per_branch") or 0))
        if required_approvals == 0 and required_human == 0 and required_ai == 0:
            required_human = 1
        protected_parent_ids = [
            parent_id
            for parent_id in list(merge_task.get("merge_parent_ids") or [])
            if parent_id in task_map and task_map[parent_id]["branch"] in set(protected_branches)
        ]

        branch_status: dict[str, Any] = {}
        satisfied = True
        for parent_id in protected_parent_ids:
            parent = task_map[parent_id]
            reviews = approval_index.get(parent_id, {})
            approved_reviews = list(reviews.get("approved_review_task_ids") or [])
            rejected_reviews = list(reviews.get("rejected_review_task_ids") or [])
            pending_reviews = list(reviews.get("pending_review_task_ids") or [])
            approved_human = list((reviews.get("approved_by_type") or {}).get("human") or [])
            approved_ai = list((reviews.get("approved_by_type") or {}).get("ai") or [])
            rejected_human = list((reviews.get("rejected_by_type") or {}).get("human") or [])
            rejected_ai = list((reviews.get("rejected_by_type") or {}).get("ai") or [])
            branch_entry = {
                "target_task_id": parent_id,
                "branch": parent["branch"],
                "required_approvals": required_approvals,
                "required_human_approvals": required_human,
                "required_ai_approvals": required_ai,
                "approved_reviews": approved_reviews,
                "rejected_reviews": rejected_reviews,
                "pending_reviews": pending_reviews,
                "approved_human_reviews": approved_human,
                "approved_ai_reviews": approved_ai,
                "rejected_human_reviews": rejected_human,
                "rejected_ai_reviews": rejected_ai,
                "satisfied": (
                    len(approved_reviews) >= required_approvals
                    and len(approved_human) >= required_human
                    and len(approved_ai) >= required_ai
                    and not rejected_reviews
                ),
            }
            if not branch_entry["satisfied"]:
                satisfied = False
            branch_status[parent_id] = branch_entry

        return {
            "protected_branches": protected_branches,
            "required_approvals_per_branch": required_approvals,
            "required_human_approvals_per_branch": required_human,
            "required_ai_approvals_per_branch": required_ai,
            "protected_parent_ids": protected_parent_ids,
            "branch_status": branch_status,
            "satisfied": satisfied,
        }

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
        review_task_ids: list[str] = []
        failed_ids: list[str] = []
        dead_letter_ids: list[str] = []
        merge_gate_status: dict[str, Any] = {}

        completed_ids = {task["id"] for task in tasks if task["status"] == "completed"}
        review_approvals = self._review_approval_index(tasks)
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
                policy_status = self._merge_policy_status_for_task(task, tasks)
                if policy_status:
                    merge_gate_status[task["id"]] = policy_status
            if task.get("payload", {}).get("_review"):
                review_task_ids.append(task["id"])
            if status == "failed":
                failed_ids.append(task["id"])
            if status == "dead-letter":
                dead_letter_ids.append(task["id"])

            if status == "queued":
                depends_on = set(task.get("depends_on", []))
                policy_status = self._merge_policy_status_for_task(task, tasks)
                policy_ready = policy_status["satisfied"] if policy_status else True
                if depends_on.issubset(completed_ids) and policy_ready:
                    ready_ids.append(task["id"])
                elif depends_on or policy_status:
                    blocked_ids.append(task["id"])

        leaf_task_ids = [task["id"] for task in tasks if task["id"] not in consumed_task_ids]
        root_task_ids = [task["id"] for task in tasks if not task.get("parent_task_id") and not task.get("merge_parent_ids")]
        open_tasks = status_counts.get("queued", 0) + status_counts.get("leased", 0)
        terminal = open_tasks == 0
        final_status = "active"
        if terminal:
            final_status = "failed" if failed_ids or dead_letter_ids else "completed"

        persisted_state = self.get_workflow_state(workflow_id)

        return {
            "workflow_id": workflow_id,
            "task_count": len(tasks),
            "root_task_ids": root_task_ids,
            "leaf_task_ids": leaf_task_ids,
            "ready_task_ids": ready_ids,
            "blocked_task_ids": blocked_ids,
            "merge_task_ids": merge_task_ids,
            "review_task_ids": review_task_ids,
            "failed_task_ids": failed_ids,
            "dead_letter_task_ids": dead_letter_ids,
            "status_counts": status_counts,
            "role_counts": role_counts,
            "branch_counts": branch_counts,
            "review_approvals": review_approvals,
            "merge_gate_status": merge_gate_status,
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
                       deliver_to, delivery_status,
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, max_attempts, retry_backoff_seconds,
                       available_at, last_error, result_json, completed_at,
                       created_at, updated_at
                FROM tasks
                WHERE status IN ('queued', 'leased')
                ORDER BY priority DESC, created_at ASC
                """
            ).fetchall()
            workflow_task_cache: dict[str, list[dict[str, Any]]] = {}

            selected: sqlite3.Row | None = None
            for row in rows:
                required = json.loads(row["required_capabilities_json"] or "[]")
                depends_on = json.loads(row["depends_on_json"] or "[]")
                lease_expired = not row["lease_expires_at"] or row["lease_expires_at"] <= now
                available = row["status"] == "queued" or lease_expired
                if not available:
                    continue
                if row["status"] == "queued" and row["available_at"] and row["available_at"] > now:
                    continue
                if row["delivery_status"] not in {"local", "fallback-local"}:
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
                payload = json.loads(row["payload_json"] or "{}")
                merge_policy = dict(payload.get("_merge_policy") or {})
                if merge_policy:
                    workflow_id = str(row["workflow_id"] or "")
                    if workflow_id:
                        if workflow_id not in workflow_task_cache:
                            workflow_task_cache[workflow_id] = self.list_workflow_tasks(workflow_id)
                        merge_task = {
                            "id": row["id"],
                            "merge_parent_ids": json.loads(row["merge_parent_ids_json"] or "[]"),
                            "payload": payload,
                        }
                        policy_status = self._merge_policy_status_for_task(merge_task, workflow_task_cache[workflow_id])
                        if policy_status and not policy_status["satisfied"]:
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
                        last_error = NULL,
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
                "deliver_to": claimed["deliver_to"],
                "delivery_status": claimed["delivery_status"],
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
                "max_attempts": claimed["max_attempts"],
                "retry_backoff_seconds": claimed["retry_backoff_seconds"],
                "available_at": claimed["available_at"],
                "last_error": claimed["last_error"],
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
            row = conn.execute(
                """
                SELECT attempts, max_attempts, retry_backoff_seconds, delivery_status
                FROM tasks
                WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                """,
                (task_id, worker_id, lease_token),
            ).fetchone()
            if not row:
                conn.commit()
                return False

            if success:
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'completed',
                        result_json = ?,
                        last_error = NULL,
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
                status = "dead-letter" if int(row["attempts"]) >= int(row["max_attempts"]) else "queued"
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?,
                        result_json = ?,
                        last_error = ?,
                        available_at = ?,
                        locked_by = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        completed_at = CASE WHEN ? = 'dead-letter' THEN ? ELSE completed_at END,
                        updated_at = ?
                    WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                    """,
                    (
                        status,
                        json.dumps(payload_update, ensure_ascii=False),
                        error_message,
                        utc_after(int(row["retry_backoff_seconds"])) if status == "queued" else now,
                        status,
                        now,
                        now,
                        task_id,
                        worker_id,
                        lease_token,
                    ),
                ).rowcount
            else:
                failure = {"error": error_message} if error_message else {"error": "task failed"}
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        result_json = ?,
                        last_error = ?,
                        completed_at = ?,
                        locked_by = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                    """,
                    (json.dumps(failure, ensure_ascii=False), error_message, now, now, task_id, worker_id, lease_token),
                ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()

    def activate_local_fallback(self, task_id: str, error_message: str) -> bool:
        conn = self._connect()
        try:
            updated = conn.execute(
                """
                UPDATE tasks
                SET delivery_status = 'fallback-local',
                    available_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ? AND delivery_status = 'remote-pending'
                """,
                (utc_now(), error_message[:500], utc_now(), task_id),
            ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()

    def mark_task_delivery_dead_letter(self, task_id: str, error_message: str) -> bool:
        conn = self._connect()
        try:
            updated = conn.execute(
                """
                UPDATE tasks
                SET status = 'dead-letter',
                    delivery_status = 'dead-letter',
                    last_error = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (error_message[:500], utc_now(), utc_now(), task_id),
            ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()

    def list_dead_letter_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, kind, sender, priority, status, payload_json, required_capabilities_json,
                       deliver_to, delivery_status,
                       workflow_id, parent_task_id, depends_on_json, role, branch, revision,
                       merge_parent_ids_json, commit_message,
                       locked_by, lease_token, lease_expires_at, attempts, max_attempts, retry_backoff_seconds,
                       available_at, last_error, result_json, completed_at,
                       created_at, updated_at
                FROM tasks
                WHERE status = 'dead-letter'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._task_from_row(row) for row in rows]
        finally:
            conn.close()

    def requeue_dead_letter_task(self, task_id: str, delay_seconds: int = 0) -> bool:
        conn = self._connect()
        try:
            updated = conn.execute(
                """
                UPDATE tasks
                SET status = 'queued',
                    delivery_status = CASE
                        WHEN deliver_to IS NOT NULL AND deliver_to != '' THEN 'remote-pending'
                        ELSE 'local'
                    END,
                    available_at = ?,
                    last_error = NULL,
                    completed_at = NULL,
                    locked_by = NULL,
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'dead-letter'
                """,
                (utc_after(delay_seconds), utc_now(), task_id),
            ).rowcount
            conn.commit()
            return updated > 0
        finally:
            conn.close()
