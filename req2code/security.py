from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def sign_payload(secret: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def sign_payload_with_meta(secret: str, payload: dict[str, Any], timestamp: str, nonce: str) -> str:
    raw_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw = f"{timestamp}\n{nonce}\n{raw_payload}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
