from req2code.tapd_stats import TapdErrorStats


def test_tapd_stats_write_reports(tmp_path):
    stats = TapdErrorStats(str(tmp_path / "stats.yaml"))
    stats.inc("auth")
    stats.inc("mapping")

    md, js = stats.write_reports(report_dir=str(tmp_path / "reports"))
    assert md.exists()
    assert js.exists()
    assert "auth" in md.read_text(encoding="utf-8")
