from req2code.models import TestResult
from req2code.review import ReviewService


def test_ai_review_approved():
    svc = ReviewService()
    ok, _ = svc.ai_review(TestResult(unit_passed=True, script_passed=True, coverage=90.0))
    assert ok is True


def test_ai_review_rejected_by_coverage():
    svc = ReviewService()
    ok, _ = svc.ai_review(TestResult(unit_passed=True, script_passed=True, coverage=60.0))
    assert ok is False
