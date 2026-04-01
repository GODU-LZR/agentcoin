from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any
from urllib import error, request

from agentcoin.adapters import AdapterPolicy, ExecutionAdapterRegistry
from agentcoin.models import utc_now

LOG = logging.getLogger("agentcoin.worker")


class WorkerLoop:
    def __init__(
        self,
        node_url: str,
        token: str,
        worker_id: str,
        capabilities: list[str],
        lease_seconds: int = 60,
        adapter_policy: AdapterPolicy | None = None,
    ) -> None:
        self.node_url = node_url.rstrip("/")
        self.token = token
        self.worker_id = worker_id
        self.capabilities = capabilities
        self.lease_seconds = lease_seconds
        self.adapters = ExecutionAdapterRegistry(adapter_policy)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.node_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            LOG.warning("request failed path=%s worker_id=%s error=%s", path, self.worker_id, exc)
            return None

    def run_once(self) -> bool:
        claimed = self._post_json(
            "/v1/tasks/claim",
            {
                "worker_id": self.worker_id,
                "worker_capabilities": self.capabilities,
                "lease_seconds": self.lease_seconds,
            },
        )
        if claimed is None:
            return False
        task = claimed.get("task")
        if not task:
            return False

        LOG.info("claimed task %s kind=%s", task["id"], task["kind"])
        result = self.execute_task(task)
        ack = self._post_json(
            "/v1/tasks/ack",
            {
                "task_id": task["id"],
                "worker_id": self.worker_id,
                "lease_token": task["lease_token"],
                "success": True,
                "result": result,
            },
        )
        if ack is None:
            LOG.warning("ack failed for task %s; lease will expire and task may be retried", task["id"])
            return False
        LOG.info("acked task %s ok=%s", task["id"], ack.get("ok"))
        return True

    def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        result = self.adapters.execute(task, worker_id=self.worker_id)
        result.setdefault("worker_id", self.worker_id)
        result.setdefault("handled_kind", task["kind"])
        result.setdefault("handled_at", utc_now())
        result.setdefault("workflow_id", task.get("workflow_id"))
        result.setdefault("branch", task.get("branch"))
        result.setdefault("revision", task.get("revision"))
        result.setdefault("echo", task.get("payload", {}))
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an AgentCoin worker loop skeleton.")
    parser.add_argument("--node-url", required=True, help="Base URL of the AgentCoin node.")
    parser.add_argument("--token", required=True, help="Bearer token for the node.")
    parser.add_argument("--worker-id", required=True, help="Stable worker identifier.")
    parser.add_argument(
        "--capability",
        dest="capabilities",
        action="append",
        default=[],
        help="Repeatable worker capability. Example: --capability worker",
    )
    parser.add_argument("--lease-seconds", type=int, default=60, help="Requested lease duration.")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Sleep time between empty polls.")
    parser.add_argument(
        "--allow-tool",
        dest="allowed_tools",
        action="append",
        default=[],
        help="Repeatable MCP tool allowlist entry.",
    )
    parser.add_argument(
        "--allow-intent",
        dest="allowed_intents",
        action="append",
        default=[],
        help="Repeatable A2A intent allowlist entry.",
    )
    parser.add_argument("--allow-subprocess", action="store_true", help="Enable sandboxed subprocess execution for local-command tool.")
    parser.add_argument(
        "--allow-command",
        dest="allowed_commands",
        action="append",
        default=[],
        help="Repeatable subprocess executable allowlist entry.",
    )
    parser.add_argument("--workspace-root", help="Restrict subprocess cwd to this root path.")
    parser.add_argument("--subprocess-timeout-seconds", type=int, default=10, help="Timeout for allowlisted subprocess execution.")
    parser.add_argument("--once", action="store_true", help="Claim at most one task and exit.")
    parser.add_argument("--log-level", default="INFO", help="Python logging level.")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    loop = WorkerLoop(
        node_url=args.node_url,
        token=args.token,
        worker_id=args.worker_id,
        capabilities=args.capabilities,
        lease_seconds=args.lease_seconds,
        adapter_policy=AdapterPolicy(
            allowed_mcp_tools=args.allowed_tools,
            allowed_a2a_intents=args.allowed_intents,
            allow_subprocess=args.allow_subprocess,
            allowed_commands=args.allowed_commands,
            subprocess_timeout_seconds=args.subprocess_timeout_seconds,
            workspace_root=args.workspace_root,
        ),
    )

    while True:
        handled = loop.run_once()
        if args.once:
            break
        if not handled:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
