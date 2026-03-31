from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from agentcoin.models import utc_now

SIGNATURE_FIELD = "_signature"
SIGNATURE_ALGORITHM = "hmac-sha256"


class SignatureError(ValueError):
    pass


def _unsigned_document(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != SIGNATURE_FIELD}


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
