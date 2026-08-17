import hashlib
import hmac
import json

from req2code.security import sign_payload


def test_sign_payload_is_stable():
    payload = {"req_id": "TAPD-1", "approved": True, "comment": "ok"}
    secret = "abc123"

    expected = hmac.new(
        secret.encode("utf-8"),
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert sign_payload(secret, payload) == expected
