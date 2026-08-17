from req2code.replay_guard import ReplayGuard


def test_replay_guard_detects_duplicate(tmp_path):
    guard = ReplayGuard(str(tmp_path / "nonces.yaml"))
    now = 1000
    assert guard.seen_or_add("abc", now_ts=now, ttl_seconds=300) is False
    assert guard.seen_or_add("abc", now_ts=now + 1, ttl_seconds=300) is True
