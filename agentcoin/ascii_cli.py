from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

DEFAULT_ENDPOINT = "http://127.0.0.1:8080"
DEFAULT_RECEIPT_ID = ""
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = {"en", "zh", "ja"}

ASCII_ART = r"""
     _                    _    _____      _
    / \                  | |  / ____|    (_)
   / _ \   __ _  ___ _ __| |_| |     ___  _ _ __
  / /_\ \ / _` |/ _ \ '__| __| |    / _ \| | '_ \
 / ____ \ (_| |  __/ |  | |_| |___| (_) | | | | |
/_/    \_\__, |\___|_|   \__|\_____\___/|_|_| |_|
          __/ |
         |___/
"""


def _messages_path(locale: str) -> Path:
    root = Path(__file__).resolve().parent.parent
    return root / "web" / "src" / "messages" / f"{locale}.json"


def load_messages(locale: str) -> dict[str, Any]:
    normalized = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    path = _messages_path(normalized)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        if normalized != DEFAULT_LOCALE:
            return load_messages(DEFAULT_LOCALE)
        return {}


def tr(messages: dict[str, Any], *keys: str, default: str = "") -> str:
    current: Any = messages
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return str(current) if isinstance(current, str) else default


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def terminal_width() -> int:
    return max(72, min(120, shutil.get_terminal_size((100, 30)).columns))


def fit(text: str, width: int) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return [""]
    return textwrap.wrap(normalized, width=width, break_long_words=True, break_on_hyphens=False) or [normalized]


def render_box(title: str, lines: list[str], *, width: int) -> str:
    inner_width = max(20, width - 4)
    top = f"+-[{title[: inner_width - 2]}]".ljust(width - 1, "-") + "+"
    body: list[str] = []
    for line in lines:
        for wrapped in fit(line, inner_width):
            body.append(f"| {wrapped[:inner_width].ljust(inner_width)} |")
    if not body:
        body.append(f"| {'':{inner_width}} |")
    bottom = "+" + "-" * (width - 2) + "+"
    return "\n".join([top, *body, bottom])


def build_auth_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def http_json(base_url: str, path: str, *, token: str | None = None, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    normalized_base = str(base_url or DEFAULT_ENDPOINT).rstrip("/")
    data = None
    headers = build_auth_headers(token)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{normalized_base}{path}", data=data, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw or str(exc)}
        return int(exc.code), parsed
    except Exception as exc:
        return 0, {"error": str(exc)}


@dataclass
class WorkbenchState:
    endpoint: str = DEFAULT_ENDPOINT
    token: str = ""
    receipt_id: str = DEFAULT_RECEIPT_ID
    locale: str = DEFAULT_LOCALE
    last_workflow_name: str = ""
    last_service_id: str = ""
    last_challenge: dict[str, Any] | None = None
    last_receipt: dict[str, Any] | None = None
    last_renter_token: dict[str, Any] | None = None


class AgentcoinAsciiWorkbench:
    def __init__(self, state: WorkbenchState) -> None:
        self.state = state
        self.messages = load_messages(state.locale)
        self.logs: list[str] = []

    def set_locale(self, locale: str) -> None:
        normalized = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
        self.state.locale = normalized
        self.messages = load_messages(normalized)

    def log(self, line: str) -> None:
        self.logs.append(str(line))
        self.logs = self.logs[-12:]

    def _fetch_receipt_status(self, receipt_id: str | None = None) -> tuple[int, dict[str, Any]]:
        active_receipt_id = str(receipt_id or self.state.receipt_id or "").strip()
        if not active_receipt_id:
            return 0, {"error": "receipt_id is required"}
        return http_json(
            self.state.endpoint,
            f"/v1/payments/receipts/status?receipt_id={active_receipt_id}",
            token=self.state.token or None,
        )

    def _service_id_for_workflow(self, workflow_name: str) -> str:
        if self.state.last_service_id:
            return self.state.last_service_id
        services_code, services = http_json(self.state.endpoint, "/v1/services", token=self.state.token or None)
        if services_code == 200:
            for item in list((services or {}).get("items") or []):
                service_id = str(item.get("service_id") or "").strip()
                if service_id == workflow_name:
                    return service_id
        return workflow_name

    def fetch_snapshot(self) -> dict[str, Any]:
        status_code, status = http_json(self.state.endpoint, "/v1/status", token=self.state.token or None)
        manifest_code, manifest = http_json(self.state.endpoint, "/v1/manifest", token=self.state.token or None)
        services_code, services = http_json(self.state.endpoint, "/v1/services", token=self.state.token or None)
        discovery_code, discovery = http_json(self.state.endpoint, "/v1/discovery/local-agents", token=self.state.token or None)
        ops = {}
        ops_code = 0
        if self.state.receipt_id:
            ops_code, ops = http_json(
                self.state.endpoint,
                f"/v1/payments/ops/summary?receipt_id={self.state.receipt_id}&relay_limit=5",
                token=self.state.token or None,
            )
        return {
            "status_code": status_code,
            "status": status,
            "manifest_code": manifest_code,
            "manifest": manifest,
            "services_code": services_code,
            "services": services,
            "discovery_code": discovery_code,
            "discovery": discovery,
            "ops_code": ops_code,
            "ops": ops,
        }

    def render(self) -> str:
        width = terminal_width()
        snapshot = self.fetch_snapshot()
        status = snapshot["status"] if isinstance(snapshot["status"], dict) else {}
        manifest = snapshot["manifest"] if isinstance(snapshot["manifest"], dict) else {}
        services = list((snapshot["services"] or {}).get("items") or [])
        discovery_items = list((snapshot["discovery"] or {}).get("items") or [])
        ops = snapshot["ops"] if isinstance(snapshot["ops"], dict) else {}

        title = tr(self.messages, "Workspace", "title", default="AgentCoin ASCII Workspace")
        boot_lines = list(self.messages.get("Index", {}).get("boot_sequence") or [])
        status_text = tr(self.messages, "Workspace", "status_online", default="STATUS: ONLINE") if snapshot["status_code"] == 200 else tr(
            self.messages,
            "Workspace",
            "status_offline",
            default="STATUS: OFFLINE",
        )
        local_identity = dict(status.get("local_identity") or {})
        routes = dict(status.get("routes") or {})
        payment = dict(manifest.get("payment") or {})

        header_lines = [line.rstrip() for line in ASCII_ART.strip("\n").splitlines()]
        header_lines.append("")
        header_lines.append(title)
        header_lines.append(status_text)
        header_lines.extend(boot_lines[:2])
        header = "\n".join(header_lines)

        node_lines = [
            f"endpoint: {self.state.endpoint}",
            f"node_id: {status.get('node_id') or '-'}",
            f"name: {status.get('name') or manifest.get('name') or '-'}",
            f"did: {local_identity.get('did') or '-'}",
            f"manifest: {routes.get('manifest') or '-'}",
            f"frontend_origins: {', '.join(status.get('frontend_origins') or []) or '-'}",
        ]

        service_lines: list[str] = []
        if services:
            for service in services[:6]:
                service_lines.append(
                    f"{service.get('service_id')} | {service.get('price_per_call')} {service.get('price_asset')} | "
                    f"privacy={service.get('privacy_level')} | uses={service.get('renter_token_max_uses')}"
                )
        else:
            service_lines.append("no public services discovered")

        discovery_lines: list[str] = []
        if snapshot["discovery_code"] == 200:
            if discovery_items:
                for item in discovery_items[:6]:
                    compatibility = dict(item.get("agentcoin_compatibility") or {})
                    discovery_lines.append(
                        f"{item.get('title')} | {item.get('family') or item.get('type') or '-'} | "
                        f"attachable={compatibility.get('attachable_today')}"
                    )
            else:
                discovery_lines.append("no local agents discovered")
        else:
            discovery_lines.append("local discovery unavailable without local auth")

        payment_lines = [
            f"required_workflows: {', '.join(payment.get('required_workflows') or []) or '-'}",
            f"receipt_kind: {payment.get('receipt_kind') or '-'}",
            f"renter_token_issue: {payment.get('renter_token_issue_url') or '-'}",
            f"renter_token_summary: {payment.get('renter_token_summary_url') or '-'}",
            f"service_usage_reconciliation: {payment.get('service_usage_reconciliation_url') or '-'}",
        ]
        if self.state.last_challenge:
            payment_lines.append(f"challenge_id: {self.state.last_challenge.get('challenge_id') or '-'}")
        if self.state.last_renter_token:
            payment_lines.append(f"renter_token: {self.state.last_renter_token.get('token_id') or '-'}")
        if self.state.receipt_id:
            service_reconcile = dict(ops.get("service_usage_reconciliation") or {})
            renter_summary = dict(ops.get("renter_token_summary") or {})
            payment_lines.extend(
                [
                    f"receipt_id: {self.state.receipt_id}",
                    f"reconciliation_status: {service_reconcile.get('reconciliation_status') or '-'}",
                    f"recommended_actions: {', '.join(service_reconcile.get('recommended_actions') or []) or '-'}",
                    f"token_count: {renter_summary.get('item_count') or 0}",
                    f"remaining_uses: {renter_summary.get('total_remaining_uses') or 0}",
                ]
            )

        log_lines = self.logs or ["type 'help' to see available commands"]
        command_lines = [
            "connect [endpoint] [token]",
            "token [value]",
            "receipt [receipt-id]",
            "workflow <workflow> <prompt...>",
            "issue-receipt <payer> <tx_hash> [challenge-id]",
            "issue-renter-token [workflow] [service-id] [max-uses]",
            "receipt-status | token-status | reconcile",
            "probe | services | discover | ops",
            "status | help | clear | exit",
        ]

        blocks = [
            render_box("NODE STATUS", node_lines, width=width),
            render_box("SERVICES", service_lines, width=width),
            render_box("LOCAL DISCOVERY", discovery_lines, width=width),
            render_box("PAYMENT / RENT", payment_lines, width=width),
            render_box("COMMANDS", command_lines, width=width),
            render_box("TERMINAL LOG", log_lines, width=width),
        ]
        return f"{header}\n\n" + "\n\n".join(blocks)

    def handle_command(self, raw: str) -> bool:
        command = str(raw or "").strip()
        if not command:
            return True
        parts = shlex.split(command)
        verb = parts[0].lower()
        args = parts[1:]

        if verb in {"exit", "quit"}:
            return False
        if verb == "help":
            self.log(
                "commands: connect, token, receipt, workflow, issue-receipt, issue-renter-token, "
                "receipt-status, token-status, reconcile, probe, services, discover, ops, status, clear, exit"
            )
            return True
        if verb == "clear":
            self.logs.clear()
            clear_screen()
            return True
        if verb == "connect":
            if args:
                self.state.endpoint = args[0].rstrip("/")
            if len(args) > 1:
                self.state.token = args[1]
            code, payload = http_json(self.state.endpoint, "/v1/status", token=self.state.token or None)
            if code == 200:
                self.log(f"connected: {payload.get('node_id') or self.state.endpoint}")
            else:
                self.log(f"connect failed: {payload.get('error') or code}")
            return True
        if verb == "token":
            self.state.token = args[0] if args else ""
            self.log("token updated" if self.state.token else "token cleared")
            return True
        if verb == "receipt":
            self.state.receipt_id = args[0] if args else ""
            self.log(f"receipt set: {self.state.receipt_id or '-'}")
            return True
        if verb == "locale":
            self.set_locale(args[0] if args else DEFAULT_LOCALE)
            self.log(f"locale: {self.state.locale}")
            return True
        if verb == "workflow":
            if len(args) < 2:
                self.log("usage: workflow <workflow-name> <prompt...>")
                return True
            workflow_name = str(args[0]).strip()
            prompt = " ".join(args[1:]).strip()
            payload: dict[str, Any] = {
                "workflow_name": workflow_name,
                "input": {"prompt": prompt},
            }
            self.state.last_workflow_name = workflow_name
            self.state.last_service_id = self._service_id_for_workflow(workflow_name)
            if self.state.last_renter_token:
                payload["renter_token"] = self.state.last_renter_token
            elif self.state.last_receipt:
                payload["payment_receipt"] = self.state.last_receipt
            code, response = http_json(
                self.state.endpoint,
                "/v1/workflow/execute",
                token=self.state.token or None,
                method="POST",
                payload=payload,
            )
            if code == 402:
                payment = dict(response.get("payment") or {})
                self.state.last_challenge = dict(payment.get("challenge") or {})
                self.log(
                    f"payment required: workflow={workflow_name} "
                    f"challenge={self.state.last_challenge.get('challenge_id') or '-'} "
                    f"amount={dict(payment.get('quote') or {}).get('amount_wei') or '-'}"
                )
            elif code == 202:
                task = dict(response.get("task") or {})
                self.log(f"workflow accepted: task={task.get('id') or '-'} kind={task.get('kind') or '-'}")
            else:
                self.log(f"workflow failed: {response.get('error') or code}")
            return True
        if verb == "issue-receipt":
            if len(args) < 2:
                self.log("usage: issue-receipt <payer> <tx_hash> [challenge-id]")
                return True
            payer = str(args[0]).strip()
            tx_hash = str(args[1]).strip()
            challenge_id = str(args[2]).strip() if len(args) > 2 else str((self.state.last_challenge or {}).get("challenge_id") or "").strip()
            if not challenge_id:
                self.log("no cached challenge_id; run workflow first or pass challenge-id")
                return True
            code, response = http_json(
                self.state.endpoint,
                "/v1/payments/receipts/issue",
                token=self.state.token or None,
                method="POST",
                payload={
                    "challenge_id": challenge_id,
                    "payer": payer,
                    "tx_hash": tx_hash,
                },
            )
            if code in {200, 201}:
                receipt = dict(response.get("receipt") or {})
                self.state.last_receipt = receipt
                self.state.receipt_id = str(receipt.get("receipt_id") or "").strip()
                self.log(f"receipt issued: receipt_id={self.state.receipt_id or '-'} challenge={challenge_id}")
            else:
                self.log(f"issue-receipt failed: {response.get('error') or code}")
            return True
        if verb == "issue-renter-token":
            workflow_name = str(args[0]).strip() if args else self.state.last_workflow_name
            if not workflow_name:
                self.log("usage: issue-renter-token [workflow] [service-id] [max-uses]")
                return True
            service_id = str(args[1]).strip() if len(args) > 1 else self.state.last_service_id or workflow_name
            max_uses = int(args[2]) if len(args) > 2 and str(args[2]).strip() else None
            receipt = self.state.last_receipt
            if not receipt:
                receipt_code, receipt_payload = self._fetch_receipt_status()
                if receipt_code == 200:
                    receipt = dict(receipt_payload.get("receipt") or {})
                    self.state.last_receipt = receipt
            if not receipt:
                self.log("no cached receipt; issue a receipt first")
                return True
            payload = {
                "workflow_name": workflow_name,
                "service_id": service_id,
                "payment_receipt": receipt,
            }
            if max_uses is not None:
                payload["max_uses"] = max_uses
            code, response = http_json(
                self.state.endpoint,
                "/v1/payments/renter-tokens/issue",
                token=self.state.token or None,
                method="POST",
                payload=payload,
            )
            if code in {200, 201}:
                token = dict(response.get("token") or {})
                token_status = dict(response.get("token_status") or {})
                self.state.last_renter_token = token
                self.state.last_service_id = str(token.get("service_id") or service_id or "").strip()
                self.log(
                    f"renter token issued: token_id={token.get('token_id') or '-'} "
                    f"remaining={token_status.get('remaining_uses')}"
                )
            else:
                self.log(f"issue-renter-token failed: {response.get('error') or code}")
            return True
        if verb == "receipt-status":
            code, response = self._fetch_receipt_status()
            if code == 200:
                receipt = dict(response.get("receipt") or {})
                self.state.last_receipt = receipt
                self.log(
                    f"receipt status: id={receipt.get('receipt_id') or '-'} "
                    f"status={receipt.get('status') or '-'}"
                )
            else:
                self.log(f"receipt-status failed: {response.get('error') or code}")
            return True
        if verb == "token-status":
            token_id = str((self.state.last_renter_token or {}).get("token_id") or "").strip()
            if not token_id:
                self.log("no cached renter token")
                return True
            code, response = http_json(
                self.state.endpoint,
                f"/v1/payments/renter-tokens/status?token_id={token_id}",
                token=self.state.token or None,
            )
            if code == 200:
                token = dict(response.get("token") or {})
                self.state.last_renter_token = token
                self.log(
                    f"token status: id={token.get('token_id') or '-'} "
                    f"remaining={token.get('remaining_uses')} status={token.get('status') or '-'}"
                )
            else:
                self.log(f"token-status failed: {response.get('error') or code}")
            return True
        if verb == "reconcile":
            active_receipt_id = str(args[0]).strip() if args else self.state.receipt_id
            if not active_receipt_id:
                self.log("no receipt set")
                return True
            code, response = http_json(
                self.state.endpoint,
                f"/v1/payments/service-usage/reconciliation?receipt_id={active_receipt_id}&service_id={self.state.last_service_id or ''}&limit=5",
                token=self.state.token or None,
            )
            if code == 200:
                self.log(
                    "reconcile="
                    f"{response.get('reconciliation_status') or '-'} "
                    f"actions={','.join(response.get('recommended_actions') or []) or '-'}"
                )
            else:
                self.log(f"reconcile failed: {response.get('error') or code}")
            return True
        if verb in {"probe", "status", "services", "discover", "ops"}:
            snapshot = self.fetch_snapshot()
            if verb == "probe":
                self.log(f"status={snapshot['status_code']} manifest={snapshot['manifest_code']} services={snapshot['services_code']} discovery={snapshot['discovery_code']} ops={snapshot['ops_code']}")
            elif verb == "status":
                status = snapshot["status"] if isinstance(snapshot["status"], dict) else {}
                self.log(f"node={status.get('node_id') or '-'} did={dict(status.get('local_identity') or {}).get('did') or '-'}")
            elif verb == "services":
                items = list((snapshot["services"] or {}).get("items") or [])
                if items:
                    for item in items[:6]:
                        self.log(f"{item.get('service_id')} {item.get('price_per_call')} {item.get('price_asset')}")
                else:
                    self.log("no services")
            elif verb == "discover":
                items = list((snapshot["discovery"] or {}).get("items") or [])
                if items:
                    for item in items[:6]:
                        self.log(f"{item.get('title')} attachable={dict(item.get('agentcoin_compatibility') or {}).get('attachable_today')}")
                else:
                    self.log("no discovered agents")
            elif verb == "ops":
                reconcile = dict((snapshot["ops"] or {}).get("service_usage_reconciliation") or {})
                self.log(
                    f"reconcile={reconcile.get('reconciliation_status') or '-'} actions={','.join(reconcile.get('recommended_actions') or []) or '-'}"
                )
            return True

        self.log(f"unknown command: {verb}")
        return True


def render_once(endpoint: str, token: str, receipt_id: str, locale: str) -> str:
    workbench = AgentcoinAsciiWorkbench(WorkbenchState(endpoint=endpoint, token=token, receipt_id=receipt_id, locale=locale))
    return workbench.render()


def interactive_main(endpoint: str, token: str, receipt_id: str, locale: str) -> None:
    workbench = AgentcoinAsciiWorkbench(WorkbenchState(endpoint=endpoint, token=token, receipt_id=receipt_id, locale=locale))
    clear_screen()
    while True:
        print(workbench.render())
        try:
            command = input("\nA-SH> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        keep_running = workbench.handle_command(command)
        if not keep_running:
            break
        clear_screen()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AgentCoin ASCII workbench.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Local AgentCoin node endpoint.")
    parser.add_argument("--token", default="", help="Optional bearer token for local protected endpoints.")
    parser.add_argument("--receipt-id", default=DEFAULT_RECEIPT_ID, help="Optional receipt id for payment dashboard views.")
    parser.add_argument("--locale", default=DEFAULT_LOCALE, choices=sorted(SUPPORTED_LOCALES), help="Locale for shared frontend strings.")
    parser.add_argument("--once", action="store_true", help="Render one snapshot and exit.")
    args = parser.parse_args()

    if args.once:
        sys.stdout.write(render_once(args.endpoint, args.token, args.receipt_id, args.locale))
        sys.stdout.write("\n")
        return
    interactive_main(args.endpoint, args.token, args.receipt_id, args.locale)


if __name__ == "__main__":
    main()
