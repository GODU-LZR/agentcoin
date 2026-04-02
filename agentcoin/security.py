from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from agentcoin.models import utc_now

SIGNATURE_FIELD = "_signature"
IDENTITY_SIGNATURE_FIELD = "_identity_signature"
SIGNATURE_ALGORITHM = "hmac-sha256"
IDENTITY_ALGORITHM = "ssh-ed25519"


class SignatureError(ValueError):
    pass


def _unsigned_document(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key not in {SIGNATURE_FIELD, IDENTITY_SIGNATURE_FIELD}}


def _canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _signature_input(document: dict[str, Any], *, key_id: str, scope: str, signed_at: str) -> bytes:
    canonical = _canonical_json(_unsigned_document(document))
    material = "\n".join([SIGNATURE_ALGORITHM, scope, key_id, signed_at, canonical])
    return material.encode("utf-8")


def sign_document(document: dict[str, Any], *, secret: str, key_id: str, scope: str) -> dict[str, Any]:
    signed_at = utc_now()
    signed_document = dict(document)
    digest = hmac.new(
        secret.encode("utf-8"),
        _signature_input(signed_document, key_id=key_id, scope=scope, signed_at=signed_at),
        hashlib.sha256,
    ).hexdigest()
    signed_document[SIGNATURE_FIELD] = {
        "alg": SIGNATURE_ALGORITHM,
        "key_id": key_id,
        "scope": scope,
        "signed_at": signed_at,
        "value": digest,
    }
    return signed_document


def verify_document(
    document: dict[str, Any],
    *,
    secret: str,
    expected_scope: str,
    expected_key_id: str | None = None,
) -> dict[str, Any]:
    signature = document.get(SIGNATURE_FIELD)
    if not isinstance(signature, dict):
        raise SignatureError("missing signature")
    if signature.get("alg") != SIGNATURE_ALGORITHM:
        raise SignatureError("unsupported signature algorithm")

    key_id = str(signature.get("key_id") or "").strip()
    scope = str(signature.get("scope") or "").strip()
    signed_at = str(signature.get("signed_at") or "").strip()
    value = str(signature.get("value") or "").strip()

    if not key_id or not scope or not signed_at or not value:
        raise SignatureError("signature is incomplete")
    if scope != expected_scope:
        raise SignatureError(f"unexpected signature scope: {scope}")
    if expected_key_id and key_id != expected_key_id:
        raise SignatureError(f"unexpected signature key_id: {key_id}")

    expected_value = hmac.new(
        secret.encode("utf-8"),
        _signature_input(document, key_id=key_id, scope=scope, signed_at=signed_at),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(value, expected_value):
        raise SignatureError("signature verification failed")

    return {
        "verified": True,
        "alg": SIGNATURE_ALGORITHM,
        "key_id": key_id,
        "scope": scope,
        "signed_at": signed_at,
    }


def resolve_public_key(*, private_key_path: str | None = None, public_key: str | None = None) -> str | None:
    if public_key and public_key.strip():
        return public_key.strip()
    if private_key_path:
        public_key_path = Path(f"{private_key_path}.pub")
        if public_key_path.exists():
            return public_key_path.read_text(encoding="utf-8").strip()
    return None


def _require_ssh_keygen() -> str:
    executable = shutil.which("ssh-keygen")
    if not executable:
        raise SignatureError("ssh-keygen is not available")
    return executable


def _run_ssh_keygen(args: list[str], *, input_bytes: bytes | None = None) -> None:
    completed = subprocess.run(
        [_require_ssh_keygen(), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        return
    message = completed.stderr.decode("utf-8", "ignore").strip() or completed.stdout.decode("utf-8", "ignore").strip()
    raise SignatureError(message or "ssh-keygen failed")


def sign_document_with_ssh(
    document: dict[str, Any],
    *,
    private_key_path: str,
    principal: str,
    namespace: str,
    public_key: str | None = None,
) -> dict[str, Any]:
    resolved_public_key = resolve_public_key(private_key_path=private_key_path, public_key=public_key)
    if not resolved_public_key:
        raise SignatureError("public key is not available for SSH identity signing")

    signed_document = dict(document)
    payload = _canonical_json(_unsigned_document(signed_document)).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="agentcoin-sign-") as temp_dir:
        payload_path = Path(temp_dir) / "payload.json"
        payload_path.write_bytes(payload)
        _run_ssh_keygen(["-Y", "sign", "-f", private_key_path, "-n", namespace, str(payload_path)])
        signature_path = Path(f"{payload_path}.sig")
        signature_value = signature_path.read_text(encoding="utf-8")

    signed_document[IDENTITY_SIGNATURE_FIELD] = {
        "alg": IDENTITY_ALGORITHM,
        "principal": principal,
        "namespace": namespace,
        "public_key": resolved_public_key,
        "value": signature_value,
    }
    return signed_document


def verify_document_with_ssh(
    document: dict[str, Any],
    *,
    public_key: str | None = None,
    public_keys: list[str] | None = None,
    revoked_public_keys: list[str] | None = None,
    principal: str,
    expected_namespace: str,
) -> dict[str, Any]:
    signature = document.get(IDENTITY_SIGNATURE_FIELD)
    if not isinstance(signature, dict):
        raise SignatureError("missing identity signature")

    namespace = str(signature.get("namespace") or "").strip()
    signature_value = str(signature.get("value") or "").strip()
    algorithm = str(signature.get("alg") or IDENTITY_ALGORITHM).strip()
    signature_principal = str(signature.get("principal") or "").strip()
    claimed_public_key = str(signature.get("public_key") or "").strip()

    if not namespace or not signature_value or not signature_principal:
        raise SignatureError("identity signature is incomplete")
    if algorithm != IDENTITY_ALGORITHM:
        raise SignatureError("unsupported identity signature algorithm")
    if namespace != expected_namespace:
        raise SignatureError(f"unexpected identity namespace: {namespace}")
    if signature_principal != principal:
        raise SignatureError(f"unexpected identity principal: {signature_principal}")

    revoked_keys: list[str] = []
    for candidate in revoked_public_keys or []:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in revoked_keys:
            revoked_keys.append(normalized)
    if claimed_public_key and claimed_public_key in revoked_keys:
        raise SignatureError("identity signature uses a revoked public key")

    trusted_keys: list[str] = []
    for candidate in [public_key, *(public_keys or [])]:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in revoked_keys and normalized not in trusted_keys:
            trusted_keys.append(normalized)
    if not trusted_keys:
        if revoked_keys:
            raise SignatureError("no non-revoked identity public keys are configured")
        raise SignatureError("no trusted identity public keys are configured")

    payload = _canonical_json(_unsigned_document(document)).encode("utf-8")
    last_error: SignatureError | None = None
    for trusted_key in trusted_keys:
        try:
            with tempfile.TemporaryDirectory(prefix="agentcoin-verify-") as temp_dir:
                signature_path = Path(temp_dir) / "payload.sig"
                allowed_signers_path = Path(temp_dir) / "allowed_signers"
                signature_path.write_text(signature_value, encoding="utf-8")
                allowed_signers_path.write_text(f"{principal} {trusted_key}\n", encoding="utf-8")
                _run_ssh_keygen(
                    ["-Y", "verify", "-f", str(allowed_signers_path), "-I", principal, "-n", namespace, "-s", str(signature_path)],
                    input_bytes=payload,
                )
            return {
                "verified": True,
                "alg": algorithm,
                "principal": principal,
                "namespace": namespace,
                "claimed_public_key": claimed_public_key,
                "matched_public_key": trusted_key,
                "trusted_key_count": len(trusted_keys),
                "revoked_key_count": len(revoked_keys),
            }
        except SignatureError as exc:
            last_error = exc

    raise last_error or SignatureError("identity signature verification failed")
