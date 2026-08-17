from req2code.tapd_stats import TapdErrorStats


def test_tapd_error_stats_inc(tmp_path):
    path = tmp_path / "stats.yaml"
    stats = TapdErrorStats(str(path))
    stats.inc("auth")
    stats.inc("auth")
    stats.inc("rate_limit")

    summary = stats.summary()
    assert summary["auth"] == 2
    assert summary["rate_limit"] == 1
