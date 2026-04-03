from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agentcoin.models import TaskEnvelope, utc_after, utc_now
from agentcoin.receipts import build_challenge_evidence
from agentcoin.semantics import capabilities_satisfy

DEFAULT_POAW_POLICY_VERSION = "0.2"

DEFAULT_POAW_SCORE_WEIGHTS: dict[str, int] = {
    "worker_base": 10,
    "reviewer_base": 8,
    "planner_base": 6,
    "aggregator_base": 9,
    "kind_code_bonus": 2,
    "kind_review_bonus": 2,
    "kind_merge_bonus": 3,
    "kind_plan_bonus": 1,
    "workflow_bonus": 1,
    "required_capability_bonus_cap": 3,
    "approved_bonus": 2,
    "merged_bonus": 1,
}

LOCAL_EVENT_TYPES = {"deterministic-pass", "deterministic-fail", "merge-completed", "task-completed"}
REVIEW_EVENT_TYPES = {
    "subjective-approve",
    "subjective-reject",
    "subjective-complete",
    "challenge-open",
    "challenge-upheld",
    "challenge-dismissed",
    "dispute-bond-awarded",
    "dispute-bond-slashed",
    "dispute-cleared",
}


class NodeStore:
    def __init__(
        self,
        database_path: str,
        *,
        poaw_policy_version: str = DEFAULT_POAW_POLICY_VERSION,
        poaw_score_weights: dict[str, int] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.poaw_policy_version = str(poaw_policy_version or DEFAULT_POAW_POLICY_VERSION).strip() or DEFAULT_POAW_POLICY_VERSION
        merged_weights = dict(DEFAULT_POAW_SCORE_WEIGHTS)
        merged_weights.update({str(key): int(value) for key, value in dict(poaw_score_weights or {}).items()})
        self.poaw_score_weights = merged_weights
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
                CREATE TABLE IF NOT EXISTS peer_health (
                    peer_id TEXT PRIMARY KEY,
                    sync_successes INTEGER NOT NULL DEFAULT 0,
                    sync_failures INTEGER NOT NULL DEFAULT 0,
                    delivery_successes INTEGER NOT NULL DEFAULT 0,
                    delivery_failures INTEGER NOT NULL DEFAULT 0,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    cooldown_until TEXT,
                    blacklisted_until TEXT,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    last_error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS execution_audits (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actor_reputation (
                    actor_id TEXT PRIMARY KEY,
                    actor_type TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    penalty_points INTEGER NOT NULL,
                    violations INTEGER NOT NULL,
                    quarantined INTEGER NOT NULL DEFAULT 0,
                    quarantine_reason TEXT,
                    last_violation_at TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS policy_violations (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    task_id TEXT,
                    source TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quarantines (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    violation_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                );
                CREATE TABLE IF NOT EXISTS governance_actions (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_auth_audits (
                    id TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    method TEXT NOT NULL,
                    policy_tier TEXT NOT NULL,
                    policy_level INTEGER NOT NULL DEFAULT 0,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    key_id TEXT,
                    auth_mode TEXT NOT NULL,
                    remote_address TEXT,
                    remote_port INTEGER,
                    nonce TEXT,
                    body_digest TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_auth_nonces (
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (key_id, nonce)
                );
                CREATE TABLE IF NOT EXISTS disputes (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    challenger_id TEXT NOT NULL,
                    actor_id TEXT,
                    actor_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_hash TEXT,
                    severity TEXT NOT NULL,
                    bond_amount_wei TEXT NOT NULL DEFAULT '0',
                    bond_status TEXT NOT NULL DEFAULT 'none',
                    committee_votes_json TEXT NOT NULL DEFAULT '[]',
                    committee_quorum INTEGER NOT NULL DEFAULT 0,
                    committee_deadline TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    resolution_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS score_events (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    points INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settlement_relays (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    recommended_resolution TEXT NOT NULL,
                    completed_steps INTEGER NOT NULL,
                    step_count INTEGER NOT NULL,
                    stopped_on_error INTEGER NOT NULL DEFAULT 0,
                    final_status TEXT NOT NULL DEFAULT 'completed',
                    last_successful_index INTEGER NOT NULL DEFAULT -1,
                    next_index INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    failure_category TEXT,
                    resumed_from_relay_id TEXT,
                    reconciliation_status TEXT NOT NULL DEFAULT 'unknown',
                    reconciliation_checked_at TEXT,
                    confirmed_at TEXT,
                    chain_receipts_json TEXT NOT NULL DEFAULT '[]',
                    relay_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settlement_relay_queue (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT,
                    last_relay_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS payment_relays (
                    id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL,
                    workflow_name TEXT,
                    completed_steps INTEGER NOT NULL,
                    step_count INTEGER NOT NULL,
                    stopped_on_error INTEGER NOT NULL DEFAULT 0,
                    final_status TEXT NOT NULL DEFAULT 'completed',
                    failure_category TEXT,
                    relay_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_relay_queue (
                    id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL,
                    workflow_name TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT,
                    last_relay_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
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
            self._ensure_column(conn, "disputes", "bond_amount_wei", "TEXT NOT NULL DEFAULT '0'")
            self._ensure_column(conn, "disputes", "bond_status", "TEXT NOT NULL DEFAULT 'none'")
            self._ensure_column(conn, "disputes", "committee_votes_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "disputes", "committee_quorum", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "disputes", "committee_deadline", "TEXT")
            self._ensure_column(conn, "settlement_relays", "final_status", "TEXT NOT NULL DEFAULT 'completed'")
            self._ensure_column(conn, "settlement_relays", "last_successful_index", "INTEGER NOT NULL DEFAULT -1")
            self._ensure_column(conn, "settlement_relays", "next_index", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "settlement_relays", "retry_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "settlement_relays", "failure_category", "TEXT")
            self._ensure_column(conn, "settlement_relays", "resumed_from_relay_id", "TEXT")
            self._ensure_column(conn, "settlement_relays", "reconciliation_status", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(conn, "settlement_relays", "reconciliation_checked_at", "TEXT")
            self._ensure_column(conn, "settlement_relays", "confirmed_at", "TEXT")
            self._ensure_column(conn, "settlement_relays", "chain_receipts_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "peer_health", "sync_successes", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "peer_health", "sync_failures", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "peer_health", "delivery_successes", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "peer_health", "delivery_failures", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "peer_health", "consecutive_failures", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "peer_health", "cooldown_until", "TEXT")
            self._ensure_column(conn, "peer_health", "blacklisted_until", "TEXT")
            self._ensure_column(conn, "peer_health", "last_success_at", "TEXT")
            self._ensure_column(conn, "peer_health", "last_failure_at", "TEXT")
            self._ensure_column(conn, "peer_health", "last_error", "TEXT")
            self._ensure_column(conn, "peer_health", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
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
            peer_health = conn.execute("SELECT COUNT(*) FROM peer_health").fetchone()[0]
            workflow_states = conn.execute("SELECT COUNT(*) FROM workflow_states").fetchone()[0]
            execution_audits = conn.execute("SELECT COUNT(*) FROM execution_audits").fetchone()[0]
            reputations = conn.execute("SELECT COUNT(*) FROM actor_reputation").fetchone()[0]
            policy_violations = conn.execute("SELECT COUNT(*) FROM policy_violations").fetchone()[0]
            active_quarantines = conn.execute("SELECT COUNT(*) FROM quarantines WHERE active = 1").fetchone()[0]
            governance_actions = conn.execute("SELECT COUNT(*) FROM governance_actions").fetchone()[0]
            operator_auth_audits = conn.execute("SELECT COUNT(*) FROM operator_auth_audits").fetchone()[0]
            disputes_open = conn.execute("SELECT COUNT(*) FROM disputes WHERE status = 'open'").fetchone()[0]
            score_events = conn.execute("SELECT COUNT(*) FROM score_events").fetchone()[0]
            settlement_relays = conn.execute("SELECT COUNT(*) FROM settlement_relays").fetchone()[0]
            settlement_relay_queue = conn.execute("SELECT COUNT(*) FROM settlement_relay_queue").fetchone()[0]
            settlement_relay_queue_queued = conn.execute("SELECT COUNT(*) FROM settlement_relay_queue WHERE status = 'queued'").fetchone()[0]
            settlement_relay_queue_paused = conn.execute("SELECT COUNT(*) FROM settlement_relay_queue WHERE status = 'paused'").fetchone()[0]
            settlement_relay_queue_running = conn.execute("SELECT COUNT(*) FROM settlement_relay_queue WHERE status = 'running'").fetchone()[0]
            settlement_relay_queue_retrying = conn.execute("SELECT COUNT(*) FROM settlement_relay_queue WHERE status = 'retrying'").fetchone()[0]
            settlement_relay_queue_completed = conn.execute("SELECT COUNT(*) FROM settlement_relay_queue WHERE status = 'completed'").fetchone()[0]
            settlement_relay_queue_dead_letter = conn.execute("SELECT COUNT(*) FROM settlement_relay_queue WHERE status = 'dead-letter'").fetchone()[0]
            payment_relays = conn.execute("SELECT COUNT(*) FROM payment_relays").fetchone()[0]
            payment_relay_queue = conn.execute("SELECT COUNT(*) FROM payment_relay_queue").fetchone()[0]
            payment_relay_queue_queued = conn.execute("SELECT COUNT(*) FROM payment_relay_queue WHERE status = 'queued'").fetchone()[0]
            payment_relay_queue_paused = conn.execute("SELECT COUNT(*) FROM payment_relay_queue WHERE status = 'paused'").fetchone()[0]
            payment_relay_queue_running = conn.execute("SELECT COUNT(*) FROM payment_relay_queue WHERE status = 'running'").fetchone()[0]
            payment_relay_queue_retrying = conn.execute("SELECT COUNT(*) FROM payment_relay_queue WHERE status = 'retrying'").fetchone()[0]
            payment_relay_queue_completed = conn.execute("SELECT COUNT(*) FROM payment_relay_queue WHERE status = 'completed'").fetchone()[0]
            payment_relay_queue_dead_letter = conn.execute("SELECT COUNT(*) FROM payment_relay_queue WHERE status = 'dead-letter'").fetchone()[0]
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
                "peer_health": peer_health,
                "workflow_states": workflow_states,
                "execution_audits": execution_audits,
                "reputations": reputations,
                "policy_violations": policy_violations,
                "quarantines_active": active_quarantines,
                "governance_actions": governance_actions,
                "operator_auth_audits": operator_auth_audits,
                "disputes_open": disputes_open,
                "score_events": score_events,
                "settlement_relays": settlement_relays,
                "settlement_relay_queue": settlement_relay_queue,
                "settlement_relay_queue_queued": settlement_relay_queue_queued,
                "settlement_relay_queue_paused": settlement_relay_queue_paused,
                "settlement_relay_queue_running": settlement_relay_queue_running,
                "settlement_relay_queue_retrying": settlement_relay_queue_retrying,
                "settlement_relay_queue_completed": settlement_relay_queue_completed,
                "settlement_relay_queue_dead_letter": settlement_relay_queue_dead_letter,
                "payment_relays": payment_relays,
                "payment_relay_queue": payment_relay_queue,
                "payment_relay_queue_queued": payment_relay_queue_queued,
                "payment_relay_queue_paused": payment_relay_queue_paused,
                "payment_relay_queue_running": payment_relay_queue_running,
                "payment_relay_queue_retrying": payment_relay_queue_retrying,
                "payment_relay_queue_completed": payment_relay_queue_completed,
                "payment_relay_queue_dead_letter": payment_relay_queue_dead_letter,
            }
        finally:
            conn.close()

    def _default_peer_health(self, peer_id: str) -> dict[str, Any]:
        now = utc_now()
        return {
            "peer_id": peer_id,
            "sync_successes": 0,
            "sync_failures": 0,
            "delivery_successes": 0,
            "delivery_failures": 0,
            "successes": 0,
            "failures": 0,
            "success_rate": 1.0,
            "consecutive_failures": 0,
            "cooldown_until": None,
            "blacklisted_until": None,
            "dispatch_blocked": {"cooldown": False, "blacklisted": False},
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        }

    def _peer_health_from_row(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if not row:
            return self._default_peer_health("")
        now = utc_now()
        sync_successes = int(row["sync_successes"] or 0)
        sync_failures = int(row["sync_failures"] or 0)
        delivery_successes = int(row["delivery_successes"] or 0)
        delivery_failures = int(row["delivery_failures"] or 0)
        successes = sync_successes + delivery_successes
        failures = sync_failures + delivery_failures
        attempts = successes + failures
        cooldown_until = row["cooldown_until"]
        blacklisted_until = row["blacklisted_until"]
        return {
            "peer_id": row["peer_id"],
            "sync_successes": sync_successes,
            "sync_failures": sync_failures,
            "delivery_successes": delivery_successes,
            "delivery_failures": delivery_failures,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / attempts, 4) if attempts else 1.0,
            "consecutive_failures": int(row["consecutive_failures"] or 0),
            "cooldown_until": cooldown_until,
            "blacklisted_until": blacklisted_until,
            "dispatch_blocked": {
                "cooldown": bool(cooldown_until and cooldown_until > now),
                "blacklisted": bool(blacklisted_until and blacklisted_until > now),
            },
            "last_success_at": row["last_success_at"],
            "last_failure_at": row["last_failure_at"],
            "last_error": row["last_error"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_peer_health(self, peer_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT peer_id, sync_successes, sync_failures, delivery_successes, delivery_failures,
                       consecutive_failures, cooldown_until, blacklisted_until,
                       last_success_at, last_failure_at, last_error, metadata_json, created_at, updated_at
                FROM peer_health
                WHERE peer_id = ?
                """,
                (peer_id,),
            ).fetchone()
            if not row:
                health = self._default_peer_health(peer_id)
                return health
            return self._peer_health_from_row(row)
        finally:
            conn.close()

    def list_peer_health(self, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT peer_id, sync_successes, sync_failures, delivery_successes, delivery_failures,
                       consecutive_failures, cooldown_until, blacklisted_until,
                       last_success_at, last_failure_at, last_error, metadata_json, created_at, updated_at
                FROM peer_health
                ORDER BY updated_at DESC, peer_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._peer_health_from_row(row) for row in rows]
        finally:
            conn.close()

    def record_peer_health(
        self,
        peer_id: str,
        *,
        source: str,
        success: bool,
        error_message: str | None = None,
        cooldown_seconds: int = 0,
        blacklist_after_failures: int = 0,
        blacklist_seconds: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if source not in {"sync", "delivery"}:
            raise ValueError("source must be sync or delivery")
        now = utc_now()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT peer_id, sync_successes, sync_failures, delivery_successes, delivery_failures,
                       consecutive_failures, cooldown_until, blacklisted_until,
                       last_success_at, last_failure_at, last_error, metadata_json, created_at, updated_at
                FROM peer_health
                WHERE peer_id = ?
                """,
                (peer_id,),
            ).fetchone()
            current = self._peer_health_from_row(row)
            sync_successes = int(current["sync_successes"])
            sync_failures = int(current["sync_failures"])
            delivery_successes = int(current["delivery_successes"])
            delivery_failures = int(current["delivery_failures"])
            consecutive_failures = int(current["consecutive_failures"])
            cooldown_until = current["cooldown_until"]
            blacklisted_until = current["blacklisted_until"]
            last_success_at = current["last_success_at"]
            last_failure_at = current["last_failure_at"]
            last_error = current["last_error"]
            merged_metadata = dict(current.get("metadata") or {})
            merged_metadata.update(dict(metadata or {}))
            merged_metadata["last_source"] = source
            merged_metadata["last_status"] = "ok" if success else "error"

            if success:
                if source == "sync":
                    sync_successes += 1
                else:
                    delivery_successes += 1
                consecutive_failures = 0
                cooldown_until = None
                last_success_at = now
                last_error = None
            else:
                if source == "sync":
                    sync_failures += 1
                else:
                    delivery_failures += 1
                consecutive_failures += 1
                last_failure_at = now
                last_error = str(error_message or "")[:500] or None
                if cooldown_seconds > 0:
                    cooldown_until = utc_after(cooldown_seconds)
                if blacklist_after_failures > 0 and blacklist_seconds > 0 and consecutive_failures >= blacklist_after_failures:
                    blacklisted_until = utc_after(blacklist_seconds)

            created_at = current["created_at"] if row else now
            conn.execute(
                """
                INSERT OR REPLACE INTO peer_health
                (peer_id, sync_successes, sync_failures, delivery_successes, delivery_failures,
                 consecutive_failures, cooldown_until, blacklisted_until,
                 last_success_at, last_failure_at, last_error, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    peer_id,
                    sync_successes,
                    sync_failures,
                    delivery_successes,
                    delivery_failures,
                    consecutive_failures,
                    cooldown_until,
                    blacklisted_until,
                    last_success_at,
                    last_failure_at,
                    last_error,
                    json.dumps(merged_metadata, ensure_ascii=False),
                    created_at,
                    now,
                ),
            )
            conn.commit()
            return self.get_peer_health(peer_id)
        finally:
            conn.close()

    def set_peer_dispatch_state(
        self,
        peer_id: str,
        *,
        cooldown_seconds: int = 0,
        blacklist_seconds: int = 0,
        clear: bool = False,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        conn = self._connect()
        try:
            current = self.get_peer_health(peer_id)
            merged_metadata = dict(current.get("metadata") or {})
            merged_metadata.update(dict(metadata or {}))
            if reason:
                merged_metadata["dispatch_state_reason"] = reason
            cooldown_until = None if clear else current.get("cooldown_until")
            blacklisted_until = None if clear else current.get("blacklisted_until")
            if cooldown_seconds > 0:
                cooldown_until = utc_after(cooldown_seconds)
            if blacklist_seconds > 0:
                blacklisted_until = utc_after(blacklist_seconds)
            conn.execute(
                """
                INSERT OR REPLACE INTO peer_health
                (peer_id, sync_successes, sync_failures, delivery_successes, delivery_failures,
                 consecutive_failures, cooldown_until, blacklisted_until,
                 last_success_at, last_failure_at, last_error, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    peer_id,
                    int(current["sync_successes"]),
                    int(current["sync_failures"]),
                    int(current["delivery_successes"]),
                    int(current["delivery_failures"]),
                    int(current["consecutive_failures"]),
                    cooldown_until,
                    blacklisted_until,
                    current["last_success_at"],
                    current["last_failure_at"],
                    current["last_error"],
                    json.dumps(merged_metadata, ensure_ascii=False),
                    current["created_at"] if current.get("created_at") else now,
                    now,
                ),
            )
            conn.commit()
            return self.get_peer_health(peer_id)
        finally:
            conn.close()

    def outbox_backlog(self, target_url: str) -> dict[str, int]:
        conn = self._connect()
        try:
            pending = conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE target_url = ? AND status = 'pending'",
                (target_url,),
            ).fetchone()[0]
            retrying = conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE target_url = ? AND status = 'retrying'",
                (target_url,),
            ).fetchone()[0]
            dead_letter = conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE target_url = ? AND status = 'dead-letter'",
                (target_url,),
            ).fetchone()[0]
            delivered = conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE target_url = ? AND status = 'delivered'",
                (target_url,),
            ).fetchone()[0]
            return {
                "pending": int(pending),
                "retrying": int(retrying),
                "dead_letter": int(dead_letter),
                "delivered": int(delivered),
                "total": int(pending) + int(retrying) + int(dead_letter) + int(delivered),
            }
        finally:
            conn.close()

    def save_execution_audit(
        self,
        *,
        task_id: str,
        worker_id: str,
        event_type: str,
        status: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        audit_id = str(uuid4())
        created_at = utc_now()
        conn = self._connect()
        try:
            self._insert_execution_audit(
                conn,
                audit_id=audit_id,
                task_id=task_id,
                worker_id=worker_id,
                event_type=event_type,
                status=status,
                payload=payload,
                created_at=created_at,
            )
            conn.commit()
            return {
                "id": audit_id,
                "task_id": task_id,
                "worker_id": worker_id,
                "event_type": event_type,
                "status": status,
                "payload": payload,
                "created_at": created_at,
            }
        finally:
            conn.close()

    @staticmethod
    def _insert_execution_audit(
        conn: sqlite3.Connection,
        *,
        audit_id: str,
        task_id: str,
        worker_id: str,
        event_type: str,
        status: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO execution_audits
            (id, task_id, worker_id, event_type, status, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (audit_id, task_id, worker_id, event_type, status, json.dumps(payload, ensure_ascii=False), created_at),
        )

    def list_execution_audits(self, task_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if task_id:
                rows = conn.execute(
                    """
                    SELECT id, task_id, worker_id, event_type, status, payload_json, created_at
                    FROM execution_audits
                    WHERE task_id = ?
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (task_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, task_id, worker_id, event_type, status, payload_json, created_at
                    FROM execution_audits
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "worker_id": row["worker_id"],
                    "event_type": row["event_type"],
                    "status": row["status"],
                    "payload": json.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    @staticmethod
    def _severity_penalty(severity: str) -> int:
        penalties = {
            "low": 5,
            "medium": 15,
            "high": 30,
            "critical": 50,
        }
        return penalties.get(str(severity or "medium").strip().lower(), 15)

    @staticmethod
    def _score_event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"],
            "task_id": row["task_id"],
            "event_type": row["event_type"],
            "points": row["points"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _dispute_from_row(row: sqlite3.Row) -> dict[str, Any]:
        committee_votes = json.loads(row["committee_votes_json"] or "[]")
        challenge_evidence = None
        if row["evidence_hash"]:
            challenge_evidence = build_challenge_evidence(
                task_id=row["task_id"],
                evidence_hash=row["evidence_hash"],
                source="dispute-lane",
                reason=row["reason"],
                severity=row["severity"],
                dispute_id=row["id"],
                payload=json.loads(row["payload_json"] or "{}"),
            )
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "challenger_id": row["challenger_id"],
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"],
            "reason": row["reason"],
            "evidence_hash": row["evidence_hash"],
            "challenge_evidence": challenge_evidence,
            "severity": row["severity"],
            "bond_amount_wei": str(row["bond_amount_wei"] or "0"),
            "bond_status": row["bond_status"],
            "committee_votes": committee_votes,
            "committee_quorum": int(row["committee_quorum"] or 0),
            "committee_deadline": row["committee_deadline"],
            "committee_tally": NodeStore._committee_tally(committee_votes),
            "status": row["status"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "resolution": json.loads(row["resolution_json"]) if row["resolution_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
        }

    @staticmethod
    def _committee_tally(votes: list[dict[str, Any]] | None) -> dict[str, int]:
        tally = {"approve": 0, "reject": 0, "abstain": 0}
        for item in list(votes or []):
            decision = str(item.get("decision") or "").strip().lower()
            if decision in tally:
                tally[decision] += 1
        return tally

    def _insert_score_event(
        self,
        conn: sqlite3.Connection,
        *,
        actor_id: str,
        actor_type: str,
        event_type: str,
        points: int,
        payload: dict[str, Any] | None = None,
        task_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        event_id = str(uuid4())
        timestamp = created_at or utc_now()
        stored_payload = payload or {}
        conn.execute(
            """
            INSERT INTO score_events
            (id, actor_id, actor_type, task_id, event_type, points, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                actor_id,
                actor_type,
                task_id,
                event_type,
                int(points),
                json.dumps(stored_payload, ensure_ascii=False),
                timestamp,
            ),
        )
        return {
            "id": event_id,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "task_id": task_id,
            "event_type": event_type,
            "points": int(points),
            "payload": stored_payload,
            "created_at": timestamp,
        }

    def list_score_events(
        self,
        *,
        actor_id: str | None = None,
        actor_type: str | None = None,
        task_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if actor_id:
                conditions.append("actor_id = ?")
                params.append(actor_id)
            if actor_type:
                conditions.append("actor_type = ?")
                params.append(actor_type)
            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)
            if event_type:
                conditions.append("event_type = ?")
                params.append(event_type)
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"""
                SELECT id, actor_id, actor_type, task_id, event_type, points, payload_json, created_at
                FROM score_events
                {where_clause}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [self._score_event_from_row(row) for row in rows]
        finally:
            conn.close()

    def open_dispute(
        self,
        *,
        dispute_id: str | None = None,
        task_id: str,
        challenger_id: str,
        reason: str,
        actor_id: str | None = None,
        actor_type: str = "worker",
        severity: str = "medium",
        evidence_hash: str | None = None,
        bond_amount_wei: str | int | None = None,
        committee_quorum: int | None = None,
        committee_deadline: str | None = None,
        payload: dict[str, Any] | None = None,
        operator_id: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        dispute_id = str(dispute_id or uuid4())
        normalized_bond_amount = str(bond_amount_wei or "0").strip() or "0"
        bond_status = "locked" if normalized_bond_amount != "0" else "none"
        normalized_committee_quorum = max(0, int(committee_quorum or 0))
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO disputes
                (id, task_id, challenger_id, actor_id, actor_type, reason, evidence_hash, severity,
                 bond_amount_wei, bond_status, committee_votes_json, committee_quorum, committee_deadline,
                 status, payload_json, resolution_json, created_at, updated_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, 'open', ?, NULL, ?, ?, NULL)
                """,
                (
                    dispute_id,
                    task_id,
                    challenger_id,
                    actor_id,
                    actor_type,
                    reason,
                    evidence_hash,
                    str(severity or "medium").strip().lower() or "medium",
                    normalized_bond_amount,
                    bond_status,
                    normalized_committee_quorum,
                    committee_deadline,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            action = self._insert_governance_action(
                conn,
                actor_id=actor_id or challenger_id,
                actor_type=actor_type,
                action_type="dispute-opened",
                reason=reason,
                payload={
                    "task_id": task_id,
                    "challenger_id": challenger_id,
                    "evidence_hash": evidence_hash,
                    "bond_amount_wei": normalized_bond_amount,
                    "bond_status": bond_status,
                    "committee_quorum": normalized_committee_quorum,
                    "committee_deadline": committee_deadline,
                    "operator_id": operator_id,
                    "receipt": receipt,
                    "context": payload or {},
                },
                created_at=now,
            )
            self._insert_score_event(
                conn,
                actor_id=challenger_id,
                actor_type="reviewer",
                task_id=task_id,
                event_type="challenge-open",
                points=0,
                payload={
                    "dispute_id": dispute_id,
                    "actor_id": actor_id,
                    "severity": str(severity or "medium").strip().lower() or "medium",
                    "poaw_policy_version": self.poaw_policy_version,
                },
                created_at=now,
            )
            conn.commit()
            return {
                "challenge_evidence": (
                    build_challenge_evidence(
                        task_id=task_id,
                        evidence_hash=evidence_hash,
                        source="dispute-lane",
                        reason=reason,
                        severity=str(severity or "medium").strip().lower() or "medium",
                        dispute_id=dispute_id,
                        payload=payload or {},
                    )
                    if evidence_hash
                    else None
                ),
                "action": action,
                "ok": True,
                "dispute": {
                    "id": dispute_id,
                    "task_id": task_id,
                    "challenger_id": challenger_id,
                    "actor_id": actor_id,
                    "actor_type": actor_type,
                    "reason": reason,
                    "evidence_hash": evidence_hash,
                    "challenge_evidence": (
                        build_challenge_evidence(
                            task_id=task_id,
                            evidence_hash=evidence_hash,
                            source="dispute-lane",
                            reason=reason,
                            severity=str(severity or "medium").strip().lower() or "medium",
                            dispute_id=dispute_id,
                            payload=payload or {},
                        )
                        if evidence_hash
                        else None
                    ),
                    "severity": str(severity or "medium").strip().lower() or "medium",
                    "bond_amount_wei": normalized_bond_amount,
                    "bond_status": bond_status,
                    "committee_votes": [],
                    "committee_quorum": normalized_committee_quorum,
                    "committee_deadline": committee_deadline,
                    "committee_tally": self._committee_tally([]),
                    "status": "open",
                    "payload": payload or {},
                    "resolution": None,
                    "created_at": now,
                    "updated_at": now,
                    "resolved_at": None,
                },
            }
        finally:
            conn.close()

    def resolve_dispute(
        self,
        *,
        dispute_id: str,
        resolution_status: str,
        reason: str,
        operator_id: str | None = None,
        payload: dict[str, Any] | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, task_id, challenger_id, actor_id, actor_type, reason, evidence_hash, severity,
                       bond_amount_wei, bond_status, committee_votes_json, committee_quorum, committee_deadline,
                       status, payload_json, resolution_json, created_at, updated_at, resolved_at
                FROM disputes
                WHERE id = ?
                """,
                (dispute_id,),
            ).fetchone()
            if not row:
                conn.commit()
                return None
            if str(row["status"]) != "open":
                conn.commit()
                return self._dispute_from_row(row)
            resolution = {
                "status": str(resolution_status or "dismissed").strip().lower() or "dismissed",
                "reason": reason,
                "operator_id": operator_id,
                "payload": payload or {},
                "receipt": receipt,
            }
            resolution_name = str(resolution["status"])
            actor_id = row["actor_id"]
            actor_type = str(row["actor_type"] or "worker")
            challenger_id = str(row["challenger_id"] or "")
            bond_amount_wei = str(row["bond_amount_wei"] or "0")
            bond_status = str(row["bond_status"] or "none")
            bond_outcome: dict[str, Any] = {
                "bond_amount_wei": bond_amount_wei,
                "previous_status": bond_status,
                "status": bond_status,
            }
            if resolution_name == "upheld":
                if bond_amount_wei != "0":
                    bond_outcome["status"] = "awarded"
                if actor_id:
                    self._record_policy_violation_with_conn(
                        conn,
                        actor_id=actor_id,
                        actor_type=actor_type,
                        task_id=row["task_id"],
                        source="dispute",
                        reason=f"dispute upheld: {reason}",
                        severity=str(row["severity"] or "medium"),
                        payload={
                            "dispute_id": dispute_id,
                            "challenger_id": challenger_id,
                            "evidence_hash": row["evidence_hash"],
                            "resolution": resolution,
                        },
                        created_at=now,
                    )
                if challenger_id:
                    self._insert_score_event(
                        conn,
                        actor_id=challenger_id,
                        actor_type="reviewer",
                        task_id=row["task_id"],
                        event_type="challenge-upheld",
                        points=8,
                        payload={
                            "dispute_id": dispute_id,
                            "actor_id": actor_id,
                            "severity": row["severity"],
                            "bond_amount_wei": bond_amount_wei,
                            "bond_status": bond_outcome["status"],
                            "poaw_policy_version": self.poaw_policy_version,
                        },
                        created_at=now,
                    )
                    if bond_amount_wei != "0":
                        self._insert_score_event(
                            conn,
                            actor_id=challenger_id,
                            actor_type="reviewer",
                            task_id=row["task_id"],
                            event_type="dispute-bond-awarded",
                            points=3,
                            payload={
                                "dispute_id": dispute_id,
                                "bond_amount_wei": bond_amount_wei,
                                "actor_id": actor_id,
                            },
                            created_at=now,
                        )
                    self._apply_reputation_delta_with_conn(
                        conn,
                        actor_id=challenger_id,
                        actor_type="reviewer",
                        score_delta=5,
                        metadata_update={
                            "last_dispute_outcome": "upheld",
                            "last_dispute_id": dispute_id,
                            "last_dispute_bond_outcome": bond_outcome["status"],
                            "last_dispute_bond_amount_wei": bond_amount_wei,
                        },
                        updated_at=now,
                    )
            elif resolution_name == "dismissed":
                if bond_amount_wei != "0":
                    bond_outcome["status"] = "slashed"
                if actor_id:
                    self._insert_score_event(
                        conn,
                        actor_id=actor_id,
                        actor_type=actor_type,
                        task_id=row["task_id"],
                        event_type="dispute-cleared",
                        points=4,
                        payload={
                            "dispute_id": dispute_id,
                            "challenger_id": challenger_id,
                        },
                        created_at=now,
                    )
                    self._apply_reputation_delta_with_conn(
                        conn,
                        actor_id=actor_id,
                        actor_type=actor_type,
                        score_delta=3,
                        metadata_update={
                            "last_dispute_outcome": "dismissed",
                            "last_dispute_id": dispute_id,
                            "last_dispute_bond_outcome": "cleared",
                            "last_dispute_bond_amount_wei": bond_amount_wei,
                        },
                        updated_at=now,
                    )
                if challenger_id:
                    self._insert_score_event(
                        conn,
                        actor_id=challenger_id,
                        actor_type="reviewer",
                        task_id=row["task_id"],
                        event_type="challenge-dismissed",
                        points=-5,
                        payload={
                            "dispute_id": dispute_id,
                            "actor_id": actor_id,
                            "bond_amount_wei": bond_amount_wei,
                            "bond_status": bond_outcome["status"],
                            "poaw_policy_version": self.poaw_policy_version,
                        },
                        created_at=now,
                    )
                    if bond_amount_wei != "0":
                        self._insert_score_event(
                            conn,
                            actor_id=challenger_id,
                            actor_type="reviewer",
                            task_id=row["task_id"],
                            event_type="dispute-bond-slashed",
                            points=-3,
                            payload={
                                "dispute_id": dispute_id,
                                "bond_amount_wei": bond_amount_wei,
                                "actor_id": actor_id,
                            },
                            created_at=now,
                        )
                    self._apply_reputation_delta_with_conn(
                        conn,
                        actor_id=challenger_id,
                        actor_type="reviewer",
                        score_delta=-5,
                        metadata_update={
                            "last_dispute_outcome": "dismissed",
                            "last_dispute_id": dispute_id,
                            "last_dispute_bond_outcome": bond_outcome["status"],
                            "last_dispute_bond_amount_wei": bond_amount_wei,
                        },
                        updated_at=now,
                    )
            resolution["bond_outcome"] = bond_outcome
            conn.execute(
                """
                UPDATE disputes
                SET status = ?, bond_status = ?, resolution_json = ?, updated_at = ?, resolved_at = ?
                WHERE id = ?
                """,
                (
                    resolution["status"],
                    bond_outcome["status"],
                    json.dumps(resolution, ensure_ascii=False),
                    now,
                    now,
                    dispute_id,
                ),
            )
            self._insert_governance_action(
                conn,
                actor_id=row["actor_id"] or row["challenger_id"],
                actor_type=row["actor_type"],
                action_type="dispute-resolved",
                reason=reason,
                payload={
                    "task_id": row["task_id"],
                    "dispute_id": dispute_id,
                    "operator_id": operator_id,
                    "receipt": receipt,
                    "resolution": resolution,
                    "bond_outcome": bond_outcome,
                },
                created_at=now,
            )
            conn.commit()
            updated = conn.execute(
                """
                SELECT id, task_id, challenger_id, actor_id, actor_type, reason, evidence_hash, severity,
                       bond_amount_wei, bond_status, committee_votes_json, committee_quorum, committee_deadline,
                       status, payload_json, resolution_json, created_at, updated_at, resolved_at
                FROM disputes
                WHERE id = ?
                """,
                (dispute_id,),
            ).fetchone()
            return self._dispute_from_row(updated) if updated else None
        finally:
            conn.close()

    def list_disputes(
        self,
        *,
        task_id: str | None = None,
        challenger_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)
            if challenger_id:
                conditions.append("challenger_id = ?")
                params.append(challenger_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"""
                SELECT id, task_id, challenger_id, actor_id, actor_type, reason, evidence_hash, severity,
                       bond_amount_wei, bond_status, committee_votes_json, committee_quorum, committee_deadline,
                       status, payload_json, resolution_json, created_at, updated_at, resolved_at
                FROM disputes
                {where_clause}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [self._dispute_from_row(row) for row in rows]
        finally:
            conn.close()

    def vote_dispute(
        self,
        *,
        dispute_id: str,
        voter_id: str,
        decision: str,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
        operator_id: str | None = None,
        resolution_receipt_factory: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"approve", "reject", "abstain"}:
            raise ValueError("decision must be approve, reject, or abstain")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, task_id, challenger_id, actor_id, actor_type, reason, evidence_hash, severity,
                       bond_amount_wei, bond_status, committee_votes_json, committee_quorum, committee_deadline,
                       status, payload_json, resolution_json, created_at, updated_at, resolved_at
                FROM disputes
                WHERE id = ?
                """,
                (dispute_id,),
            ).fetchone()
            if not row:
                conn.commit()
                return None
            if str(row["status"] or "") != "open":
                conn.commit()
                return self._dispute_from_row(row)
            committee_quorum = int(row["committee_quorum"] or 0)
            if committee_quorum <= 0:
                raise ValueError("dispute does not require committee voting")
            votes = json.loads(row["committee_votes_json"] or "[]")
            filtered_votes = [item for item in votes if str(item.get("voter_id") or "") != voter_id]
            filtered_votes.append(
                {
                    "voter_id": voter_id,
                    "decision": normalized_decision,
                    "note": note,
                    "payload": payload or {},
                    "created_at": now,
                }
            )
            conn.execute(
                """
                UPDATE disputes
                SET committee_votes_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(filtered_votes, ensure_ascii=False),
                    now,
                    dispute_id,
                ),
            )
            tally = self._committee_tally(filtered_votes)
            self._insert_governance_action(
                conn,
                actor_id=voter_id,
                actor_type="reviewer",
                action_type="dispute-voted",
                reason=f"committee vote: {normalized_decision}",
                payload={
                    "dispute_id": dispute_id,
                    "task_id": row["task_id"],
                    "decision": normalized_decision,
                    "operator_id": operator_id,
                    "committee_quorum": committee_quorum,
                    "committee_tally": tally,
                },
                created_at=now,
            )
            conn.commit()
        finally:
            conn.close()

        resolution_status = None
        resolution_reason = None
        tally = self._committee_tally(filtered_votes)
        if tally["approve"] >= committee_quorum:
            resolution_status = "upheld"
            resolution_reason = "committee quorum approved challenge"
        elif tally["reject"] >= committee_quorum:
            resolution_status = "dismissed"
            resolution_reason = "committee quorum rejected challenge"
        elif len(filtered_votes) >= committee_quorum and max(tally["approve"], tally["reject"]) < committee_quorum:
            resolution_status = "escalated"
            resolution_reason = "committee reached quorum without decisive outcome"

        if resolution_status:
            resolution_context = {
                "dispute_id": dispute_id,
                "task_id": row["task_id"],
                "challenger_id": row["challenger_id"],
                "actor_id": row["actor_id"],
                "actor_type": row["actor_type"],
                "reason": row["reason"],
                "evidence_hash": row["evidence_hash"],
                "severity": row["severity"],
                "committee_quorum": committee_quorum,
                "committee_votes": filtered_votes,
                "committee_tally": tally,
                "resolution_status": resolution_status,
                "resolution_reason": resolution_reason,
                "operator_id": operator_id or f"committee:{voter_id}",
            }
            return self.resolve_dispute(
                dispute_id=dispute_id,
                resolution_status=resolution_status,
                reason=resolution_reason or "committee resolution",
                operator_id=operator_id or f"committee:{voter_id}",
                payload={
                    "committee_votes": filtered_votes,
                    "committee_tally": tally,
                    "committee_quorum": committee_quorum,
                },
                receipt=resolution_receipt_factory(resolution_context) if resolution_receipt_factory else None,
            )
        return self.get_dispute(dispute_id)

    def get_dispute(self, dispute_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, task_id, challenger_id, actor_id, actor_type, reason, evidence_hash, severity,
                       bond_amount_wei, bond_status, committee_votes_json, committee_quorum, committee_deadline,
                       status, payload_json, resolution_json, created_at, updated_at, resolved_at
                FROM disputes
                WHERE id = ?
                """,
                (dispute_id,),
            ).fetchone()
            return self._dispute_from_row(row) if row else None
        finally:
            conn.close()

    def summarize_score_events(
        self,
        *,
        actor_id: str | None = None,
        actor_type: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        conn = self._connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if actor_id:
                conditions.append("actor_id = ?")
                params.append(actor_id)
            if actor_type:
                conditions.append("actor_type = ?")
                params.append(actor_type)
            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            totals = conn.execute(
                f"""
                SELECT COUNT(*) AS event_count,
                       COALESCE(SUM(points), 0) AS total_points,
                       COALESCE(SUM(CASE WHEN points > 0 THEN points ELSE 0 END), 0) AS positive_points,
                       COALESCE(SUM(CASE WHEN points < 0 THEN points ELSE 0 END), 0) AS negative_points
                FROM score_events
                {where_clause}
                """,
                params,
            ).fetchone()
            type_rows = conn.execute(
                f"""
                SELECT event_type, COUNT(*) AS count, COALESCE(SUM(points), 0) AS points
                FROM score_events
                {where_clause}
                GROUP BY event_type
                ORDER BY event_type ASC
                """,
                params,
            ).fetchall()
            by_event_type = [
                {
                    "event_type": row["event_type"],
                    "count": int(row["count"] or 0),
                    "points": int(row["points"] or 0),
                }
                for row in type_rows
            ]
            local_score = sum(item["points"] for item in by_event_type if item["event_type"] in LOCAL_EVENT_TYPES)
            review_score = sum(item["points"] for item in by_event_type if item["event_type"] in REVIEW_EVENT_TYPES)
            summary = {
                "actor_id": actor_id,
                "actor_type": actor_type,
                "task_id": task_id,
                "poaw_policy_version": self.poaw_policy_version,
                "score_weights": dict(self.poaw_score_weights),
                "event_count": int(totals["event_count"] or 0),
                "total_points": int(totals["total_points"] or 0),
                "positive_points": int(totals["positive_points"] or 0),
                "negative_points": int(totals["negative_points"] or 0),
                "local_score": int(local_score),
                "review_score": int(review_score),
                "network_trust_score": int(self.get_actor_reputation(actor_id, actor_type=actor_type or "worker").get("score", 100))
                if actor_id
                else None,
                "by_event_type": by_event_type,
            }
            if actor_id:
                summary["reputation"] = self.get_actor_reputation(actor_id, actor_type=actor_type or "worker")
            return summary
        finally:
            conn.close()

    def save_settlement_relay(
        self,
        relay: dict[str, Any],
        *,
        retry_count: int = 0,
        resumed_from_relay_id: str | None = None,
    ) -> dict[str, Any]:
        relay_id = str(uuid4())
        created_at = utc_now()
        final_status = str(relay.get("final_status") or "").strip() or "completed"
        last_successful_index = int(relay.get("last_successful_index") or -1)
        next_index = int(relay.get("next_index") or 0)
        failure_category = str(relay.get("failure_category") or "").strip() or None
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO settlement_relays
                (
                    id, task_id, recommended_resolution, completed_steps, step_count, stopped_on_error,
                    final_status, last_successful_index, next_index, retry_count, failure_category,
                    resumed_from_relay_id, reconciliation_status, reconciliation_checked_at,
                    confirmed_at, chain_receipts_json, relay_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown', NULL, NULL, '[]', ?, ?)
                """,
                (
                    relay_id,
                    str(relay.get("task_id") or ""),
                    str(relay.get("recommended_resolution") or ""),
                    int(relay.get("completed_steps") or 0),
                    int(relay.get("step_count") or 0),
                    1 if bool(relay.get("stopped_on_error")) else 0,
                    final_status,
                    last_successful_index,
                    next_index,
                    retry_count,
                    failure_category,
                    resumed_from_relay_id,
                    json.dumps(relay, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.commit()
            return {
                "id": relay_id,
                "task_id": str(relay.get("task_id") or ""),
                "recommended_resolution": str(relay.get("recommended_resolution") or ""),
                "completed_steps": int(relay.get("completed_steps") or 0),
                "step_count": int(relay.get("step_count") or 0),
                "stopped_on_error": bool(relay.get("stopped_on_error")),
                "final_status": final_status,
                "last_successful_index": last_successful_index,
                "next_index": next_index,
                "retry_count": retry_count,
                "failure_category": failure_category,
                "resumed_from_relay_id": resumed_from_relay_id,
                "reconciliation_status": "unknown",
                "reconciliation_checked_at": None,
                "confirmed_at": None,
                "chain_receipts": [],
                "relay": relay,
                "created_at": created_at,
            }
        finally:
            conn.close()

    @staticmethod
    def _settlement_relay_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "recommended_resolution": row["recommended_resolution"],
            "completed_steps": int(row["completed_steps"] or 0),
            "step_count": int(row["step_count"] or 0),
            "stopped_on_error": bool(row["stopped_on_error"]),
            "final_status": row["final_status"],
            "last_successful_index": int(row["last_successful_index"] or -1),
            "next_index": int(row["next_index"] or 0),
            "retry_count": int(row["retry_count"] or 0),
            "failure_category": row["failure_category"],
            "resumed_from_relay_id": row["resumed_from_relay_id"],
            "reconciliation_status": row["reconciliation_status"],
            "reconciliation_checked_at": row["reconciliation_checked_at"],
            "confirmed_at": row["confirmed_at"],
            "chain_receipts": json.loads(row["chain_receipts_json"] or "[]"),
            "relay": json.loads(row["relay_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def list_settlement_relays(self, task_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if task_id:
                rows = conn.execute(
                    """
                    SELECT id, task_id, recommended_resolution, completed_steps, step_count,
                           stopped_on_error, final_status, last_successful_index, next_index, retry_count,
                           failure_category, resumed_from_relay_id, reconciliation_status,
                           reconciliation_checked_at, confirmed_at, chain_receipts_json, relay_json, created_at
                    FROM settlement_relays
                    WHERE task_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (task_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, task_id, recommended_resolution, completed_steps, step_count,
                           stopped_on_error, final_status, last_successful_index, next_index, retry_count,
                           failure_category, resumed_from_relay_id, reconciliation_status,
                           reconciliation_checked_at, confirmed_at, chain_receipts_json, relay_json, created_at
                    FROM settlement_relays
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._settlement_relay_from_row(row) for row in rows]
        finally:
            conn.close()

    def get_settlement_relay(self, relay_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, task_id, recommended_resolution, completed_steps, step_count,
                       stopped_on_error, final_status, last_successful_index, next_index, retry_count,
                       failure_category, resumed_from_relay_id, reconciliation_status,
                       reconciliation_checked_at, confirmed_at, chain_receipts_json, relay_json, created_at
                FROM settlement_relays
                WHERE id = ?
                """,
                (relay_id,),
            ).fetchone()
            if not row:
                return None
            return self._settlement_relay_from_row(row)
        finally:
            conn.close()

    def get_latest_settlement_relay(self, task_id: str) -> dict[str, Any] | None:
        items = self.list_settlement_relays(task_id=task_id, limit=1)
        return items[0] if items else None

    def update_settlement_relay_reconciliation(
        self,
        relay_id: str,
        *,
        reconciliation_status: str,
        reconciliation_checked_at: str,
        confirmed_at: str | None,
        chain_receipts: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT relay_json
                FROM settlement_relays
                WHERE id = ?
                """,
                (relay_id,),
            ).fetchone()
            if not row:
                return None

            relay_payload = json.loads(row["relay_json"] or "{}")
            relay_payload["reconciliation"] = {
                "status": reconciliation_status,
                "checked_at": reconciliation_checked_at,
                "confirmed_at": confirmed_at,
                "receipts": list(chain_receipts or []),
            }
            conn.execute(
                """
                UPDATE settlement_relays
                SET reconciliation_status = ?,
                    reconciliation_checked_at = ?,
                    confirmed_at = ?,
                    chain_receipts_json = ?,
                    relay_json = ?
                WHERE id = ?
                """,
                (
                    reconciliation_status,
                    reconciliation_checked_at,
                    confirmed_at,
                    json.dumps(list(chain_receipts or []), ensure_ascii=False),
                    json.dumps(relay_payload, ensure_ascii=False),
                    relay_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_settlement_relay(relay_id)

    def enqueue_settlement_relay(
        self,
        *,
        task_id: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
        delay_seconds: int = 0,
    ) -> dict[str, Any]:
        queue_id = str(uuid4())
        created_at = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO settlement_relay_queue
                (
                    id, task_id, status, attempts, max_attempts, next_attempt_at,
                    last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                )
                VALUES (?, ?, 'queued', 0, ?, ?, NULL, NULL, ?, ?, ?, NULL)
                """,
                (
                    queue_id,
                    task_id,
                    int(max_attempts or 3),
                    next_attempt_at,
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                    created_at,
                ),
            )
            conn.commit()
            return self.get_settlement_relay_queue_item(queue_id) or {
                "id": queue_id,
                "task_id": task_id,
                "status": "queued",
                "attempts": 0,
                "max_attempts": int(max_attempts or 3),
                "next_attempt_at": next_attempt_at,
                "last_error": None,
                "last_relay_id": None,
                "payload": payload,
                "created_at": created_at,
                "updated_at": created_at,
                "completed_at": None,
            }
        finally:
            conn.close()

    def list_settlement_relay_queue(
        self,
        *,
        task_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"""
                SELECT id, task_id, status, attempts, max_attempts, next_attempt_at,
                       last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                FROM settlement_relay_queue
                {where_clause}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "status": row["status"],
                    "attempts": int(row["attempts"] or 0),
                    "max_attempts": int(row["max_attempts"] or 0),
                    "next_attempt_at": row["next_attempt_at"],
                    "last_error": row["last_error"],
                    "last_relay_id": row["last_relay_id"],
                    "payload": json.loads(row["payload_json"] or "{}"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "completed_at": row["completed_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def get_settlement_relay_queue_item(self, queue_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, task_id, status, attempts, max_attempts, next_attempt_at,
                       last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                FROM settlement_relay_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "status": row["status"],
                "attempts": int(row["attempts"] or 0),
                "max_attempts": int(row["max_attempts"] or 0),
                "next_attempt_at": row["next_attempt_at"],
                "last_error": row["last_error"],
                "last_relay_id": row["last_relay_id"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
            }
        finally:
            conn.close()

    def recover_running_settlement_relay_queue_items(self, *, delay_seconds: int = 0) -> int:
        now = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = 'retrying',
                    next_attempt_at = ?,
                    updated_at = ?,
                    completed_at = NULL
                WHERE status = 'running'
                """,
                (next_attempt_at, now),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()

    def claim_next_settlement_relay_queue_item(self, *, max_in_flight: int | None = None) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if max_in_flight is not None and int(max_in_flight) > 0:
                running = conn.execute(
                    "SELECT COUNT(*) FROM settlement_relay_queue WHERE status = 'running'"
                ).fetchone()[0]
                if int(running or 0) >= int(max_in_flight):
                    conn.commit()
                    return None
            row = conn.execute(
                """
                SELECT id, task_id, status, attempts, max_attempts, next_attempt_at,
                       last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                FROM settlement_relay_queue
                WHERE status IN ('queued', 'retrying')
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, created_at ASC, rowid ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                conn.commit()
                return None

            attempts = int(row["attempts"] or 0) + 1
            conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = 'running',
                    attempts = ?,
                    last_error = NULL,
                    updated_at = ?,
                    completed_at = NULL
                WHERE id = ?
                """,
                (attempts, now, row["id"]),
            )
            conn.commit()
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "status": "running",
                "attempts": attempts,
                "max_attempts": int(row["max_attempts"] or 0),
                "next_attempt_at": row["next_attempt_at"],
                "last_error": None,
                "last_relay_id": row["last_relay_id"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": now,
                "completed_at": None,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete_settlement_relay_queue_item(self, queue_id: str, *, last_relay_id: str | None = None) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = 'completed',
                    last_relay_id = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (last_relay_id, now, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_settlement_relay_queue_item(queue_id)

    def fail_settlement_relay_queue_item(
        self,
        queue_id: str,
        *,
        error: str,
        last_relay_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT attempts, max_attempts, payload_json
                FROM settlement_relay_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
            if not row:
                return None

            attempts = int(row["attempts"] or 0)
            max_attempts = int(row["max_attempts"] or 0)
            status = "dead-letter" if attempts >= max_attempts else "retrying"
            delay_seconds = 0 if status == "dead-letter" else min(2 ** min(attempts, 6), 60)
            next_attempt_at = utc_after(delay_seconds)
            payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else str(row["payload_json"] or "{}")
            completed_at = now if status == "dead-letter" else None
            conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = ?,
                    last_error = ?,
                    last_relay_id = ?,
                    payload_json = ?,
                    next_attempt_at = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (status, str(error or "")[:500], last_relay_id, payload_json, next_attempt_at, now, completed_at, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_settlement_relay_queue_item(queue_id)

    def pause_settlement_relay_queue_item(self, queue_id: str) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = 'paused',
                    updated_at = ?
                WHERE id = ? AND status IN ('queued', 'retrying')
                """,
                (now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_settlement_relay_queue_item(queue_id)

    def resume_settlement_relay_queue_item(self, queue_id: str, *, delay_seconds: int = 0) -> dict[str, Any] | None:
        now = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = 'queued',
                    next_attempt_at = ?,
                    updated_at = ?,
                    completed_at = NULL
                WHERE id = ? AND status = 'paused'
                """,
                (next_attempt_at, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_settlement_relay_queue_item(queue_id)

    def requeue_settlement_relay_queue_item(
        self,
        queue_id: str,
        *,
        delay_seconds: int = 0,
        payload: dict[str, Any] | None = None,
        max_attempts: int | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json, max_attempts
                FROM settlement_relay_queue
                WHERE id = ? AND status = 'dead-letter'
                """,
                (queue_id,),
            ).fetchone()
            if not row:
                return self.get_settlement_relay_queue_item(queue_id)

            payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else str(row["payload_json"] or "{}")
            effective_max_attempts = int(max_attempts or row["max_attempts"] or 3)
            conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = 'queued',
                    attempts = 0,
                    max_attempts = ?,
                    next_attempt_at = ?,
                    last_error = NULL,
                    payload_json = ?,
                    updated_at = ?,
                    completed_at = NULL
                WHERE id = ? AND status = 'dead-letter'
                """,
                (effective_max_attempts, next_attempt_at, payload_json, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_settlement_relay_queue_item(queue_id)

    def cancel_settlement_relay_queue_item(self, queue_id: str) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE settlement_relay_queue
                SET status = 'dead-letter',
                    last_error = 'cancelled',
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ? AND status IN ('queued', 'paused', 'retrying')
                """,
                (now, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_settlement_relay_queue_item(queue_id)

    def delete_settlement_relay_queue_item(self, queue_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "DELETE FROM settlement_relay_queue WHERE id = ?",
                (queue_id,),
            )
            conn.commit()
            return row.rowcount > 0
        finally:
            conn.close()

    def save_payment_relay(self, relay: dict[str, Any]) -> dict[str, Any]:
        relay_id = str(uuid4())
        created_at = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO payment_relays
                (
                    id, receipt_id, workflow_name, completed_steps, step_count, stopped_on_error,
                    final_status, failure_category, relay_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relay_id,
                    str(relay.get("receipt_id") or ""),
                    str(relay.get("workflow_name") or ""),
                    int(relay.get("completed_steps") or 0),
                    int(relay.get("step_count") or 0),
                    1 if bool(relay.get("stopped_on_error")) else 0,
                    str(relay.get("final_status") or "completed"),
                    str(relay.get("failures", [{}])[0].get("category") or "") if relay.get("failures") else None,
                    json.dumps(relay, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.commit()
            return {
                "id": relay_id,
                "receipt_id": str(relay.get("receipt_id") or ""),
                "workflow_name": str(relay.get("workflow_name") or ""),
                "completed_steps": int(relay.get("completed_steps") or 0),
                "step_count": int(relay.get("step_count") or 0),
                "stopped_on_error": bool(relay.get("stopped_on_error")),
                "final_status": str(relay.get("final_status") or "completed"),
                "failure_category": str(relay.get("failures", [{}])[0].get("category") or "") if relay.get("failures") else None,
                "relay": relay,
                "created_at": created_at,
            }
        finally:
            conn.close()

    @staticmethod
    def _payment_relay_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "receipt_id": row["receipt_id"],
            "workflow_name": row["workflow_name"],
            "completed_steps": int(row["completed_steps"] or 0),
            "step_count": int(row["step_count"] or 0),
            "stopped_on_error": bool(row["stopped_on_error"]),
            "final_status": row["final_status"],
            "failure_category": row["failure_category"],
            "relay": json.loads(row["relay_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def list_payment_relays(self, *, receipt_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if receipt_id:
                rows = conn.execute(
                    """
                    SELECT id, receipt_id, workflow_name, completed_steps, step_count,
                           stopped_on_error, final_status, failure_category, relay_json, created_at
                    FROM payment_relays
                    WHERE receipt_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (receipt_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, receipt_id, workflow_name, completed_steps, step_count,
                           stopped_on_error, final_status, failure_category, relay_json, created_at
                    FROM payment_relays
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._payment_relay_from_row(row) for row in rows]
        finally:
            conn.close()

    def get_latest_payment_relay(self, receipt_id: str | None = None) -> dict[str, Any] | None:
        items = self.list_payment_relays(receipt_id=receipt_id, limit=1)
        return items[0] if items else None

    def get_latest_failed_payment_relay(self, receipt_id: str | None = None) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            if receipt_id:
                row = conn.execute(
                    """
                    SELECT id, receipt_id, workflow_name, completed_steps, step_count,
                           stopped_on_error, final_status, failure_category, relay_json, created_at
                    FROM payment_relays
                    WHERE receipt_id = ? AND final_status != 'completed'
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (receipt_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id, receipt_id, workflow_name, completed_steps, step_count,
                           stopped_on_error, final_status, failure_category, relay_json, created_at
                    FROM payment_relays
                    WHERE final_status != 'completed'
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """
                ).fetchone()
            return self._payment_relay_from_row(row) if row else None
        finally:
            conn.close()

    def enqueue_payment_relay(
        self,
        *,
        receipt_id: str,
        workflow_name: str | None,
        payload: dict[str, Any],
        max_attempts: int = 3,
        delay_seconds: int = 0,
    ) -> dict[str, Any]:
        queue_id = str(uuid4())
        created_at = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO payment_relay_queue
                (
                    id, receipt_id, workflow_name, status, attempts, max_attempts, next_attempt_at,
                    last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, 'queued', 0, ?, ?, NULL, NULL, ?, ?, ?, NULL)
                """,
                (
                    queue_id,
                    receipt_id,
                    workflow_name,
                    int(max_attempts or 3),
                    next_attempt_at,
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                    created_at,
                ),
            )
            conn.commit()
            return self.get_payment_relay_queue_item(queue_id) or {
                "id": queue_id,
                "receipt_id": receipt_id,
                "workflow_name": workflow_name,
                "status": "queued",
                "attempts": 0,
                "max_attempts": int(max_attempts or 3),
                "next_attempt_at": next_attempt_at,
                "last_error": None,
                "last_relay_id": None,
                "payload": payload,
                "created_at": created_at,
                "updated_at": created_at,
                "completed_at": None,
            }
        finally:
            conn.close()

    def list_payment_relay_queue(
        self,
        *,
        receipt_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if receipt_id:
                conditions.append("receipt_id = ?")
                params.append(receipt_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"""
                SELECT id, receipt_id, workflow_name, status, attempts, max_attempts, next_attempt_at,
                       last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                FROM payment_relay_queue
                {where_clause}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "receipt_id": row["receipt_id"],
                    "workflow_name": row["workflow_name"],
                    "status": row["status"],
                    "attempts": int(row["attempts"] or 0),
                    "max_attempts": int(row["max_attempts"] or 0),
                    "next_attempt_at": row["next_attempt_at"],
                    "last_error": row["last_error"],
                    "last_relay_id": row["last_relay_id"],
                    "payload": json.loads(row["payload_json"] or "{}"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "completed_at": row["completed_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def summarize_payment_relay_queue(self, *, receipt_id: str | None = None) -> dict[str, Any]:
        items = self.list_payment_relay_queue(receipt_id=receipt_id, limit=1000)
        counts = {
            "queued": 0,
            "paused": 0,
            "running": 0,
            "retrying": 0,
            "completed": 0,
            "dead-letter": 0,
        }
        auto_requeue_disabled_count = 0
        latest_item = items[0] if items else None
        latest_failed_item = next((item for item in items if str(item.get("status") or "") == "dead-letter"), None)
        for item in items:
            status_name = str(item.get("status") or "").strip()
            if status_name in counts:
                counts[status_name] += 1
            if bool(dict(item.get("payload") or {}).get("_auto_requeue_disabled")):
                auto_requeue_disabled_count += 1
        return {
            "receipt_id": receipt_id,
            "item_count": len(items),
            "counts": counts,
            "auto_requeue_disabled_count": auto_requeue_disabled_count,
            "latest_item": latest_item,
            "latest_failed_item": latest_failed_item,
        }

    def get_payment_relay_queue_item(self, queue_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, receipt_id, workflow_name, status, attempts, max_attempts, next_attempt_at,
                       last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                FROM payment_relay_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "receipt_id": row["receipt_id"],
                "workflow_name": row["workflow_name"],
                "status": row["status"],
                "attempts": int(row["attempts"] or 0),
                "max_attempts": int(row["max_attempts"] or 0),
                "next_attempt_at": row["next_attempt_at"],
                "last_error": row["last_error"],
                "last_relay_id": row["last_relay_id"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
            }
        finally:
            conn.close()

    def update_payment_relay_queue_payload(self, queue_id: str, *, payload: dict[str, Any]) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET payload_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(payload, ensure_ascii=False), now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_payment_relay_queue_item(queue_id)

    def recover_running_payment_relay_queue_items(self, *, delay_seconds: int = 0) -> int:
        now = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = 'retrying',
                    next_attempt_at = ?,
                    updated_at = ?,
                    completed_at = NULL
                WHERE status = 'running'
                """,
                (next_attempt_at, now),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()

    def claim_next_payment_relay_queue_item(self, *, max_in_flight: int | None = None) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if max_in_flight is not None and int(max_in_flight) > 0:
                running = conn.execute(
                    "SELECT COUNT(*) FROM payment_relay_queue WHERE status = 'running'"
                ).fetchone()[0]
                if int(running or 0) >= int(max_in_flight):
                    conn.commit()
                    return None
            row = conn.execute(
                """
                SELECT id, receipt_id, workflow_name, status, attempts, max_attempts, next_attempt_at,
                       last_error, last_relay_id, payload_json, created_at, updated_at, completed_at
                FROM payment_relay_queue
                WHERE status IN ('queued', 'retrying')
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, created_at ASC, rowid ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                conn.commit()
                return None
            attempts = int(row["attempts"] or 0) + 1
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = 'running',
                    attempts = ?,
                    last_error = NULL,
                    updated_at = ?,
                    completed_at = NULL
                WHERE id = ?
                """,
                (attempts, now, row["id"]),
            )
            conn.commit()
            return {
                "id": row["id"],
                "receipt_id": row["receipt_id"],
                "workflow_name": row["workflow_name"],
                "status": "running",
                "attempts": attempts,
                "max_attempts": int(row["max_attempts"] or 0),
                "next_attempt_at": row["next_attempt_at"],
                "last_error": None,
                "last_relay_id": row["last_relay_id"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": now,
                "completed_at": None,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete_payment_relay_queue_item(self, queue_id: str, *, last_relay_id: str | None = None) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = 'completed',
                    last_relay_id = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (last_relay_id, now, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_payment_relay_queue_item(queue_id)

    def fail_payment_relay_queue_item(
        self,
        queue_id: str,
        *,
        error: str,
        last_relay_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT attempts, max_attempts, payload_json
                FROM payment_relay_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
            if not row:
                return None
            attempts = int(row["attempts"] or 0)
            max_attempts = int(row["max_attempts"] or 0)
            status = "dead-letter" if attempts >= max_attempts else "retrying"
            delay_seconds = 0 if status == "dead-letter" else min(2 ** min(attempts, 6), 60)
            next_attempt_at = utc_after(delay_seconds)
            if payload is not None:
                merged_payload = json.loads(row["payload_json"] or "{}")
                merged_payload.update(dict(payload))
                payload_json = json.dumps(merged_payload, ensure_ascii=False)
            else:
                payload_json = str(row["payload_json"] or "{}")
            completed_at = now if status == "dead-letter" else None
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = ?,
                    last_error = ?,
                    last_relay_id = ?,
                    payload_json = ?,
                    next_attempt_at = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (status, str(error or "")[:500], last_relay_id, payload_json, next_attempt_at, now, completed_at, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_payment_relay_queue_item(queue_id)

    def requeue_payment_relay_queue_item(
        self,
        queue_id: str,
        *,
        delay_seconds: int = 0,
        payload: dict[str, Any] | None = None,
        max_attempts: int | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json, max_attempts
                FROM payment_relay_queue
                WHERE id = ? AND status = 'dead-letter'
                """,
                (queue_id,),
            ).fetchone()
            if not row:
                return self.get_payment_relay_queue_item(queue_id)
            payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else str(row["payload_json"] or "{}")
            effective_max_attempts = int(max_attempts or row["max_attempts"] or 3)
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = 'queued',
                    attempts = 0,
                    max_attempts = ?,
                    next_attempt_at = ?,
                    last_error = NULL,
                    payload_json = ?,
                    updated_at = ?,
                    completed_at = NULL
                WHERE id = ? AND status = 'dead-letter'
                """,
                (effective_max_attempts, next_attempt_at, payload_json, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_payment_relay_queue_item(queue_id)

    def pause_payment_relay_queue_item(self, queue_id: str) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = 'paused',
                    updated_at = ?
                WHERE id = ? AND status IN ('queued', 'retrying')
                """,
                (now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_payment_relay_queue_item(queue_id)

    def resume_payment_relay_queue_item(self, queue_id: str, *, delay_seconds: int = 0) -> dict[str, Any] | None:
        now = utc_now()
        next_attempt_at = utc_after(max(0, int(delay_seconds)))
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = 'queued',
                    next_attempt_at = ?,
                    updated_at = ?,
                    completed_at = NULL
                WHERE id = ? AND status = 'paused'
                """,
                (next_attempt_at, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_payment_relay_queue_item(queue_id)

    def cancel_payment_relay_queue_item(self, queue_id: str) -> dict[str, Any] | None:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE payment_relay_queue
                SET status = 'dead-letter',
                    last_error = 'cancelled',
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ? AND status IN ('queued', 'paused', 'retrying')
                """,
                (now, now, queue_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_payment_relay_queue_item(queue_id)

    def delete_payment_relay_queue_item(self, queue_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "DELETE FROM payment_relay_queue WHERE id = ?",
                (queue_id,),
            )
            conn.commit()
            return row.rowcount > 0
        finally:
            conn.close()

    def _completion_score_event(
        self,
        *,
        task_id: str,
        worker_id: str,
        role: str,
        kind: str,
        workflow_id: str | None,
        branch: str,
        delivery_status: str,
        required_capabilities: list[str],
        result: dict[str, Any] | None,
    ) -> tuple[str, int, dict[str, Any]]:
        role_name = str(role or "worker").strip().lower() or "worker"
        kind_name = str(kind or "generic").strip().lower() or "generic"
        role_base = {
            "worker": self.poaw_score_weights["worker_base"],
            "reviewer": self.poaw_score_weights["reviewer_base"],
            "planner": self.poaw_score_weights["planner_base"],
            "aggregator": self.poaw_score_weights["aggregator_base"],
        }.get(role_name, 5)
        kind_bonus = {
            "code": self.poaw_score_weights["kind_code_bonus"],
            "exec": self.poaw_score_weights["kind_code_bonus"],
            "tool-call": self.poaw_score_weights["kind_code_bonus"],
            "review": self.poaw_score_weights["kind_review_bonus"],
            "merge": self.poaw_score_weights["kind_merge_bonus"],
            "plan": self.poaw_score_weights["kind_plan_bonus"],
        }.get(kind_name, 0)
        points = role_base + kind_bonus
        score_components = {
            "role_base": role_base,
            "kind_bonus": kind_bonus,
            "workflow_bonus": 0,
            "required_capabilities_bonus": 0,
            "approved_bonus": 0,
            "merged_bonus": 0,
        }
        if workflow_id:
            points += self.poaw_score_weights["workflow_bonus"]
            score_components["workflow_bonus"] = self.poaw_score_weights["workflow_bonus"]
        if required_capabilities:
            required_bonus = min(self.poaw_score_weights["required_capability_bonus_cap"], len(required_capabilities))
            points += required_bonus
            score_components["required_capabilities_bonus"] = required_bonus
        approved = bool((result or {}).get("approved"))
        merged = bool((result or {}).get("merged"))
        if approved:
            points += self.poaw_score_weights["approved_bonus"]
            score_components["approved_bonus"] = self.poaw_score_weights["approved_bonus"]
        if merged:
            points += self.poaw_score_weights["merged_bonus"]
            score_components["merged_bonus"] = self.poaw_score_weights["merged_bonus"]
        event_type = "task-completed"
        if kind_name in {"code", "exec", "tool-call"}:
            event_type = "deterministic-pass"
        if kind_name == "review":
            event_type = "subjective-approve" if approved else "subjective-complete"
        elif kind_name == "merge":
            event_type = "merge-completed"
        return (
            event_type,
            points,
            {
                "worker_id": worker_id,
                "role": role_name,
                "kind": kind_name,
                "workflow_id": workflow_id,
                "branch": branch,
                "delivery_status": delivery_status,
                "required_capabilities": required_capabilities,
                "result_keys": sorted((result or {}).keys()),
                "approved": approved,
                "merged": merged,
                "poaw_policy_version": self.poaw_policy_version,
                "score_components": score_components,
            },
        )

    def _failure_score_event(
        self,
        *,
        task_id: str,
        worker_id: str,
        role: str,
        kind: str,
        workflow_id: str | None,
        branch: str,
        delivery_status: str,
        required_capabilities: list[str],
        error_message: str | None,
    ) -> tuple[str, int, dict[str, Any]]:
        kind_name = str(kind or "generic").strip().lower() or "generic"
        event_type = "task-failed"
        points = -10
        if kind_name in {"code", "exec", "tool-call"}:
            event_type = "deterministic-fail"
            points = -12
        elif kind_name == "review":
            event_type = "subjective-reject"
            points = -8
        return (
            event_type,
            points,
            {
                "worker_id": worker_id,
                "role": str(role or "worker").strip().lower() or "worker",
                "kind": kind_name,
                "workflow_id": workflow_id,
                "branch": branch,
                "delivery_status": delivery_status,
                "required_capabilities": required_capabilities,
                "error_message": error_message,
                "poaw_policy_version": self.poaw_policy_version,
            },
        )

    @staticmethod
    def _reputation_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"],
            "score": row["score"],
            "penalty_points": row["penalty_points"],
            "violations": row["violations"],
            "quarantined": bool(row["quarantined"]),
            "quarantine_reason": row["quarantine_reason"],
            "last_violation_at": row["last_violation_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _apply_reputation_delta_with_conn(
        self,
        conn: sqlite3.Connection,
        *,
        actor_id: str,
        actor_type: str = "worker",
        score_delta: int = 0,
        penalty_points_delta: int = 0,
        violations_delta: int = 0,
        metadata_update: dict[str, Any] | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        now = updated_at or utc_now()
        existing = conn.execute(
            """
            SELECT score, penalty_points, violations, quarantined, quarantine_reason, last_violation_at, metadata_json, created_at
            FROM actor_reputation
            WHERE actor_id = ?
            """,
            (actor_id,),
        ).fetchone()
        if existing:
            score = max(0, min(150, int(existing["score"]) + int(score_delta)))
            penalty_points = max(0, int(existing["penalty_points"]) + int(penalty_points_delta))
            violations = max(0, int(existing["violations"]) + int(violations_delta))
            quarantined = bool(existing["quarantined"])
            quarantine_reason = existing["quarantine_reason"]
            last_violation_at = existing["last_violation_at"]
            metadata = json.loads(existing["metadata_json"] or "{}")
            created = existing["created_at"]
        else:
            score = max(0, min(150, 100 + int(score_delta)))
            penalty_points = max(0, int(penalty_points_delta))
            violations = max(0, int(violations_delta))
            quarantined = False
            quarantine_reason = None
            last_violation_at = None
            metadata = {}
            created = now

        if metadata_update:
            metadata.update(metadata_update)
        conn.execute(
            """
            INSERT OR REPLACE INTO actor_reputation
            (actor_id, actor_type, score, penalty_points, violations, quarantined,
             quarantine_reason, last_violation_at, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                actor_type,
                score,
                penalty_points,
                violations,
                1 if quarantined else 0,
                quarantine_reason,
                last_violation_at,
                json.dumps(metadata, ensure_ascii=False),
                created,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT actor_id, actor_type, score, penalty_points, violations, quarantined,
                   quarantine_reason, last_violation_at, metadata_json, created_at, updated_at
            FROM actor_reputation
            WHERE actor_id = ?
            """,
            (actor_id,),
        ).fetchone()
        return self._reputation_from_row(row)

    def get_actor_reputation(self, actor_id: str, actor_type: str = "worker") -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT actor_id, actor_type, score, penalty_points, violations, quarantined,
                       quarantine_reason, last_violation_at, metadata_json, created_at, updated_at
                FROM actor_reputation
                WHERE actor_id = ?
                """,
                (actor_id,),
            ).fetchone()
            if not row:
                now = utc_now()
                return {
                    "actor_id": actor_id,
                    "actor_type": actor_type,
                    "score": 100,
                    "penalty_points": 0,
                    "violations": 0,
                    "quarantined": False,
                    "quarantine_reason": None,
                    "last_violation_at": None,
                    "metadata": {},
                    "created_at": now,
                    "updated_at": now,
                }
            return self._reputation_from_row(row)
        finally:
            conn.close()

    def list_actor_reputations(self, actor_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if actor_type:
                rows = conn.execute(
                    """
                    SELECT actor_id, actor_type, score, penalty_points, violations, quarantined,
                           quarantine_reason, last_violation_at, metadata_json, created_at, updated_at
                    FROM actor_reputation
                    WHERE actor_type = ?
                    ORDER BY quarantined DESC, score ASC, updated_at DESC
                    LIMIT ?
                    """,
                    (actor_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT actor_id, actor_type, score, penalty_points, violations, quarantined,
                           quarantine_reason, last_violation_at, metadata_json, created_at, updated_at
                    FROM actor_reputation
                    ORDER BY quarantined DESC, score ASC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._reputation_from_row(row) for row in rows]
        finally:
            conn.close()

    def is_actor_quarantined(self, actor_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT quarantined FROM actor_reputation WHERE actor_id = ?",
                (actor_id,),
            ).fetchone()
            return bool(row and row["quarantined"])
        finally:
            conn.close()

    def _record_policy_violation_with_conn(
        self,
        conn: sqlite3.Connection,
        *,
        actor_id: str,
        actor_type: str = "worker",
        source: str,
        reason: str,
        severity: str = "medium",
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now()
        violation_id = str(uuid4())
        severity_name = str(severity or "medium").strip().lower() or "medium"
        penalty = self._severity_penalty(severity_name)
        payload = payload or {}
        conn.execute(
            """
            INSERT INTO policy_violations
            (id, actor_id, actor_type, task_id, source, reason, severity, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                violation_id,
                actor_id,
                actor_type,
                task_id,
                source,
                reason,
                severity_name,
                json.dumps(payload, ensure_ascii=False),
                now,
            ),
        )
        self._insert_score_event(
            conn,
            actor_id=actor_id,
            actor_type=actor_type,
            task_id=task_id,
            event_type="policy-violation",
            points=-penalty,
            payload={
                "source": source,
                "reason": reason,
                "severity": severity_name,
                "penalty": penalty,
                "poaw_policy_version": self.poaw_policy_version,
                **(payload or {}),
            },
            created_at=now,
        )
        existing = conn.execute(
            """
            SELECT score, penalty_points, violations, quarantined, quarantine_reason, metadata_json, created_at
            FROM actor_reputation
            WHERE actor_id = ?
            """,
            (actor_id,),
        ).fetchone()
        if existing:
            score = max(0, int(existing["score"]) - penalty)
            penalty_points = int(existing["penalty_points"]) + penalty
            violations = int(existing["violations"]) + 1
            metadata = json.loads(existing["metadata_json"] or "{}")
            created = existing["created_at"]
        else:
            score = max(0, 100 - penalty)
            penalty_points = penalty
            violations = 1
            metadata = {}
            created = now

        metadata["last_source"] = source
        metadata["last_reason"] = reason
        metadata["last_severity"] = severity_name
        quarantine_reason = existing["quarantine_reason"] if existing else None
        quarantined = bool(existing["quarantined"]) if existing else False
        should_quarantine = penalty_points >= 45 or violations >= 3 or severity_name == "critical"
        if should_quarantine:
            quarantined = True
            quarantine_reason = quarantine_reason or f"{severity_name} policy violations threshold reached"
            active = conn.execute(
                """
                SELECT id FROM quarantines
                WHERE actor_id = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (actor_id,),
            ).fetchone()
            if active:
                conn.execute(
                    """
                    UPDATE quarantines
                    SET reason = ?, violation_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (quarantine_reason, violations, now, active["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO quarantines
                    (id, actor_id, actor_type, scope, reason, active, violation_count, created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL)
                    """,
                    (str(uuid4()), actor_id, actor_type, "task-claim", quarantine_reason, violations, now, now),
                )

        conn.execute(
            """
            INSERT OR REPLACE INTO actor_reputation
            (actor_id, actor_type, score, penalty_points, violations, quarantined,
             quarantine_reason, last_violation_at, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                actor_type,
                score,
                penalty_points,
                violations,
                1 if quarantined else 0,
                quarantine_reason,
                now,
                json.dumps(metadata, ensure_ascii=False),
                created,
                now,
            ),
        )
        return {
            "id": violation_id,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "task_id": task_id,
            "source": source,
            "reason": reason,
            "severity": severity_name,
            "payload": payload,
            "created_at": now,
            "reputation": {
                "actor_id": actor_id,
                "actor_type": actor_type,
                "score": score,
                "penalty_points": penalty_points,
                "violations": violations,
                "quarantined": quarantined,
                "quarantine_reason": quarantine_reason,
                "last_violation_at": now,
                "metadata": metadata,
                "created_at": created,
                "updated_at": now,
            },
        }

    def record_policy_violation(
        self,
        *,
        actor_id: str,
        actor_type: str = "worker",
        source: str,
        reason: str,
        severity: str = "medium",
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            violation = self._record_policy_violation_with_conn(
                conn,
                actor_id=actor_id,
                actor_type=actor_type,
                source=source,
                reason=reason,
                severity=severity,
                task_id=task_id,
                payload=payload,
            )
            conn.commit()
            return violation
        finally:
            conn.close()

    def list_policy_violations(self, actor_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if actor_id:
                rows = conn.execute(
                    """
                    SELECT id, actor_id, actor_type, task_id, source, reason, severity, payload_json, created_at
                    FROM policy_violations
                    WHERE actor_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (actor_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, actor_id, actor_type, task_id, source, reason, severity, payload_json, created_at
                    FROM policy_violations
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "actor_id": row["actor_id"],
                    "actor_type": row["actor_type"],
                    "task_id": row["task_id"],
                    "source": row["source"],
                    "reason": row["reason"],
                    "severity": row["severity"],
                    "payload": json.loads(row["payload_json"] or "{}"),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def list_quarantines(
        self,
        actor_id: str | None = None,
        *,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if actor_id:
                conditions.append("actor_id = ?")
                params.append(actor_id)
            if active_only:
                conditions.append("active = 1")
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"""
                SELECT id, actor_id, actor_type, scope, reason, active, violation_count, created_at, updated_at, expires_at
                FROM quarantines
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "actor_id": row["actor_id"],
                    "actor_type": row["actor_type"],
                    "scope": row["scope"],
                    "reason": row["reason"],
                    "active": bool(row["active"]),
                    "violation_count": row["violation_count"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "expires_at": row["expires_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    @staticmethod
    def _governance_action_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"] or "{}")
        return {
            "id": row["id"],
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"],
            "action_type": row["action_type"],
            "reason": row["reason"],
            "payload": payload,
            "operator_id": payload.get("operator_id"),
            "receipt": payload.get("receipt"),
            "created_at": row["created_at"],
        }

    def _insert_governance_action(
        self,
        conn: sqlite3.Connection,
        *,
        actor_id: str,
        actor_type: str,
        action_type: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        action_id = str(uuid4())
        timestamp = created_at or utc_now()
        stored_payload = payload or {}
        conn.execute(
            """
            INSERT INTO governance_actions
            (id, actor_id, actor_type, action_type, reason, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                actor_id,
                actor_type,
                action_type,
                reason,
                json.dumps(stored_payload, ensure_ascii=False),
                timestamp,
            ),
        )
        return {
            "id": action_id,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "action_type": action_type,
            "reason": reason,
            "payload": stored_payload,
            "operator_id": stored_payload.get("operator_id"),
            "receipt": stored_payload.get("receipt"),
            "created_at": timestamp,
        }

    def list_governance_actions(self, actor_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if actor_id:
                rows = conn.execute(
                    """
                    SELECT id, actor_id, actor_type, action_type, reason, payload_json, created_at
                    FROM governance_actions
                    WHERE actor_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (actor_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, actor_id, actor_type, action_type, reason, payload_json, created_at
                    FROM governance_actions
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._governance_action_from_row(row) for row in rows]
        finally:
            conn.close()

    def record_governance_action(
        self,
        *,
        actor_id: str,
        actor_type: str,
        action_type: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = self._connect()
        try:
            action = self._insert_governance_action(
                conn,
                actor_id=actor_id,
                actor_type=actor_type,
                action_type=action_type,
                reason=reason,
                payload=payload,
            )
            conn.commit()
            return action
        finally:
            conn.close()

    @staticmethod
    def _operator_auth_audit_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"] or "{}")
        return {
            "id": row["id"],
            "endpoint": row["endpoint"],
            "method": row["method"],
            "policy_tier": row["policy_tier"],
            "policy_level": int(row["policy_level"] or 0),
            "decision": row["decision"],
            "reason": row["reason"],
            "key_id": row["key_id"],
            "auth_mode": row["auth_mode"],
            "remote_address": row["remote_address"],
            "remote_port": row["remote_port"],
            "nonce": row["nonce"],
            "body_digest": row["body_digest"],
            "payload": payload,
            "created_at": row["created_at"],
        }

    def record_operator_auth_audit(
        self,
        *,
        endpoint: str,
        method: str,
        policy_tier: str,
        policy_level: int,
        decision: str,
        reason: str,
        auth_mode: str,
        key_id: str | None = None,
        remote_address: str | None = None,
        remote_port: int | None = None,
        nonce: str | None = None,
        body_digest: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit_id = str(uuid4())
        created_at = utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO operator_auth_audits
                (id, endpoint, method, policy_tier, policy_level, decision, reason, key_id, auth_mode,
                 remote_address, remote_port, nonce, body_digest, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    endpoint,
                    method,
                    policy_tier,
                    int(policy_level),
                    decision,
                    reason,
                    key_id,
                    auth_mode,
                    remote_address,
                    remote_port,
                    nonce,
                    body_digest,
                    json.dumps(payload or {}, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.commit()
            return {
                "id": audit_id,
                "endpoint": endpoint,
                "method": method,
                "policy_tier": policy_tier,
                "policy_level": int(policy_level),
                "decision": decision,
                "reason": reason,
                "key_id": key_id,
                "auth_mode": auth_mode,
                "remote_address": remote_address,
                "remote_port": remote_port,
                "nonce": nonce,
                "body_digest": body_digest,
                "payload": payload or {},
                "created_at": created_at,
            }
        finally:
            conn.close()

    def list_operator_auth_audits(
        self,
        *,
        endpoint: str | None = None,
        decision: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if endpoint:
                conditions.append("endpoint = ?")
                params.append(endpoint)
            if decision:
                conditions.append("decision = ?")
                params.append(decision)
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"""
                SELECT id, endpoint, method, policy_tier, policy_level, decision, reason, key_id,
                       auth_mode, remote_address, remote_port, nonce, body_digest, payload_json, created_at
                FROM operator_auth_audits
                {where_clause}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [self._operator_auth_audit_from_row(row) for row in rows]
        finally:
            conn.close()

    def reserve_operator_auth_nonce(self, *, key_id: str, nonce: str, ttl_seconds: int) -> bool:
        normalized_key_id = str(key_id or "").strip()
        normalized_nonce = str(nonce or "").strip()
        if not normalized_key_id or not normalized_nonce:
            raise ValueError("key_id and nonce are required")
        now = utc_now()
        expires_at = utc_after(max(1, int(ttl_seconds)))
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM operator_auth_nonces WHERE expires_at <= ?",
                (now,),
            )
            try:
                conn.execute(
                    """
                    INSERT INTO operator_auth_nonces (key_id, nonce, first_seen_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (normalized_key_id, normalized_nonce, now, expires_at),
                )
            except sqlite3.IntegrityError:
                conn.commit()
                return False
            conn.commit()
            return True
        finally:
            conn.close()

    def set_actor_quarantine(
        self,
        *,
        actor_id: str,
        reason: str,
        actor_type: str = "worker",
        scope: str = "task-claim",
        payload: dict[str, Any] | None = None,
        operator_id: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT actor_id, actor_type, score, penalty_points, violations, quarantined,
                       quarantine_reason, last_violation_at, metadata_json, created_at, updated_at
                FROM actor_reputation
                WHERE actor_id = ?
                """,
                (actor_id,),
            ).fetchone()
            metadata = json.loads(existing["metadata_json"] or "{}") if existing else {}
            metadata["manual_quarantine"] = True
            metadata["manual_quarantine_reason"] = reason
            score = int(existing["score"]) if existing else 100
            penalty_points = int(existing["penalty_points"]) if existing else 0
            violations = int(existing["violations"]) if existing else 0
            created = existing["created_at"] if existing else now

            conn.execute(
                """
                INSERT OR REPLACE INTO actor_reputation
                (actor_id, actor_type, score, penalty_points, violations, quarantined,
                 quarantine_reason, last_violation_at, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    actor_id,
                    actor_type,
                    score,
                    penalty_points,
                    violations,
                    reason,
                    existing["last_violation_at"] if existing else None,
                    json.dumps(metadata, ensure_ascii=False),
                    created,
                    now,
                ),
            )

            active = conn.execute(
                """
                SELECT id, violation_count FROM quarantines
                WHERE actor_id = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (actor_id,),
            ).fetchone()
            if active:
                conn.execute(
                    """
                    UPDATE quarantines
                    SET reason = ?, scope = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (reason, scope, now, active["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO quarantines
                    (id, actor_id, actor_type, scope, reason, active, violation_count, created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL)
                    """,
                    (str(uuid4()), actor_id, actor_type, scope, reason, violations, now, now),
                )
            action = self._insert_governance_action(
                conn,
                actor_id=actor_id,
                actor_type=actor_type,
                action_type="quarantine-set",
                reason=reason,
                payload={
                    "operator_id": operator_id,
                    "receipt": receipt,
                    "context": payload or {},
                    "scope": scope,
                },
                created_at=now,
            )
            conn.commit()
            return {
                "ok": True,
                "actor_id": actor_id,
                "quarantined": True,
                "reputation": self.get_actor_reputation(actor_id, actor_type=actor_type),
                "quarantines": self.list_quarantines(actor_id=actor_id, active_only=True, limit=20),
                "action": action,
            }
        finally:
            conn.close()

    def release_actor_quarantine(
        self,
        *,
        actor_id: str,
        reason: str,
        actor_type: str = "worker",
        payload: dict[str, Any] | None = None,
        operator_id: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT actor_id, actor_type, score, penalty_points, violations, quarantined,
                       quarantine_reason, last_violation_at, metadata_json, created_at, updated_at
                FROM actor_reputation
                WHERE actor_id = ?
                """,
                (actor_id,),
            ).fetchone()
            if row:
                metadata = json.loads(row["metadata_json"] or "{}")
                metadata["manual_release_reason"] = reason
                conn.execute(
                    """
                    UPDATE actor_reputation
                    SET quarantined = 0,
                        quarantine_reason = NULL,
                        metadata_json = ?,
                        updated_at = ?
                    WHERE actor_id = ?
                    """,
                    (json.dumps(metadata, ensure_ascii=False), now, actor_id),
                )
            conn.execute(
                """
                UPDATE quarantines
                SET active = 0, updated_at = ?
                WHERE actor_id = ? AND active = 1
                """,
                (now, actor_id),
            )
            action = self._insert_governance_action(
                conn,
                actor_id=actor_id,
                actor_type=actor_type,
                action_type="quarantine-release",
                reason=reason,
                payload={
                    "operator_id": operator_id,
                    "receipt": receipt,
                    "context": payload or {},
                },
                created_at=now,
            )
            conn.commit()
            return {
                "ok": True,
                "actor_id": actor_id,
                "quarantined": False,
                "reputation": self.get_actor_reputation(actor_id, actor_type=actor_type),
                "quarantines": self.list_quarantines(actor_id=actor_id, active_only=False, limit=20),
                "action": action,
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
            target_git = dict(target.get("payload", {}).get("_git") or {})
            if target_git:
                review_meta.setdefault("base_ref", target_git.get("base_ref"))
                review_meta.setdefault("head_ref", target_git.get("target_ref") or target_git.get("head_ref"))
                review_meta.setdefault("base_sha", target_git.get("base_sha"))
                review_meta.setdefault("head_sha", target_git.get("target_sha") or target_git.get("head_sha"))
            review.payload["_review"] = review_meta
            if target_git and "_git" not in review.payload:
                review.payload["_git"] = target_git
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
        if self.is_actor_quarantined(worker_id):
            return None
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
                if required and not capabilities_satisfy(required, worker_capabilities):
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
        policy_violation: dict[str, Any] | None = None
        if result:
            policy_receipt = dict(result.get("policy_receipt") or {})
            adapter = dict(result.get("adapter") or {})
            decision = str(policy_receipt.get("decision") or "").strip().lower()
            adapter_status = str(adapter.get("status") or "").strip().lower()
            if decision == "rejected" or adapter_status == "rejected":
                severity = "medium"
                reason_text = str(policy_receipt.get("reason") or adapter.get("reason") or error_message or "policy rejected")
                if "escape" in reason_text.lower() or "timeout" in reason_text.lower():
                    severity = "high"
                policy_violation = {
                    "actor_id": worker_id,
                    "actor_type": "worker",
                    "task_id": task_id,
                    "source": str(policy_receipt.get("protocol") or adapter.get("protocol") or "adapter-policy"),
                    "reason": reason_text,
                    "severity": severity,
                    "payload": {
                        "policy_receipt": policy_receipt,
                        "adapter": adapter,
                    },
                }
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT attempts, max_attempts, retry_backoff_seconds, delivery_status,
                       role, kind, workflow_id, branch, required_capabilities_json
                FROM tasks
                WHERE id = ? AND status = 'leased' AND locked_by = ? AND lease_token = ?
                """,
                (task_id, worker_id, lease_token),
            ).fetchone()
            if not row:
                conn.commit()
                return False

            if success:
                audit_id = str(uuid4())
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
                if updated:
                    self._insert_execution_audit(
                        conn,
                        audit_id=audit_id,
                        task_id=task_id,
                        worker_id=worker_id,
                        event_type="ack",
                        status="completed",
                        payload={"success": True, "result": result or {}},
                        created_at=now,
                    )
                    event_type, points, event_payload = self._completion_score_event(
                        task_id=task_id,
                        worker_id=worker_id,
                        role=str(row["role"] or "worker"),
                        kind=str(row["kind"] or "generic"),
                        workflow_id=row["workflow_id"],
                        branch=str(row["branch"] or "main"),
                        delivery_status=str(row["delivery_status"] or "local"),
                        required_capabilities=json.loads(row["required_capabilities_json"] or "[]"),
                        result=result or {},
                    )
                    self._insert_score_event(
                        conn,
                        actor_id=worker_id,
                        actor_type="worker",
                        task_id=task_id,
                        event_type=event_type,
                        points=points,
                        payload=event_payload,
                        created_at=now,
                    )
                    if policy_violation:
                        violation = self._record_policy_violation_with_conn(conn, created_at=now, **policy_violation)
                        conn.execute(
                            """
                            UPDATE execution_audits
                            SET payload_json = ?
                            WHERE id = ?
                            """,
                            (
                                json.dumps(
                                    {
                                        "success": True,
                                        "result": result or {},
                                        "policy_violation": violation,
                                    },
                                    ensure_ascii=False,
                                ),
                                audit_id,
                            ),
                        )
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
                if updated:
                    self._insert_execution_audit(
                        conn,
                        audit_id=str(uuid4()),
                        task_id=task_id,
                        worker_id=worker_id,
                        event_type="ack",
                        status=status,
                        payload={
                            "success": False,
                            "requeue": True,
                            "error_message": error_message,
                            "result": payload_update,
                        },
                        created_at=now,
                    )
                    if status == "dead-letter":
                        event_type, points, event_payload = self._failure_score_event(
                            task_id=task_id,
                            worker_id=worker_id,
                            role=str(row["role"] or "worker"),
                            kind=str(row["kind"] or "generic"),
                            workflow_id=row["workflow_id"],
                            branch=str(row["branch"] or "main"),
                            delivery_status=str(row["delivery_status"] or "local"),
                            required_capabilities=json.loads(row["required_capabilities_json"] or "[]"),
                            error_message=error_message,
                        )
                        self._insert_score_event(
                            conn,
                            actor_id=worker_id,
                            actor_type="worker",
                            task_id=task_id,
                            event_type=event_type,
                            points=points,
                            payload=event_payload,
                            created_at=now,
                        )
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
                if updated:
                    self._insert_execution_audit(
                        conn,
                        audit_id=str(uuid4()),
                        task_id=task_id,
                        worker_id=worker_id,
                        event_type="ack",
                        status="failed",
                        payload={
                            "success": False,
                            "requeue": False,
                            "error_message": error_message,
                            "result": failure,
                        },
                        created_at=now,
                    )
                    event_type, points, event_payload = self._failure_score_event(
                        task_id=task_id,
                        worker_id=worker_id,
                        role=str(row["role"] or "worker"),
                        kind=str(row["kind"] or "generic"),
                        workflow_id=row["workflow_id"],
                        branch=str(row["branch"] or "main"),
                        delivery_status=str(row["delivery_status"] or "local"),
                        required_capabilities=json.loads(row["required_capabilities_json"] or "[]"),
                        error_message=error_message,
                    )
                    self._insert_score_event(
                        conn,
                        actor_id=worker_id,
                        actor_type="worker",
                        task_id=task_id,
                        event_type=event_type,
                        points=points,
                        payload=event_payload,
                        created_at=now,
                    )
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
