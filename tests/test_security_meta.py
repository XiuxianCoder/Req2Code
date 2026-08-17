from req2code.security import sign_payload_with_meta


def test_sign_payload_with_meta_changes_when_meta_changes():
    payload = {"req_id": "A"}
    s1 = sign_payload_with_meta("secret", payload, "100", "n1")
    s2 = sign_payload_with_meta("secret", payload, "101", "n1")
    s3 = sign_payload_with_meta("secret", payload, "100", "n2")
    assert s1 != s2
    assert s1 != s3
