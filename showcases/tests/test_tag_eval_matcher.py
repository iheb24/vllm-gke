import importlib.util
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "eval" / "run_tag_eval.py"
spec = importlib.util.spec_from_file_location("run_tag_eval", RUNNER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def q(texts):
    return {"type": "exact", "expect_in_answer": texts}


def result(answer):
    return {"answer": answer, "evidence": {"sql": "SELECT 1"}}


def test_plain_substring_still_works():
    ok, detail = mod.score(q(["2026-09-08"]), result("the top day was 2026-09-08"))
    assert ok and not detail["missing"]


def test_thousands_separator_matches():
    ok, _ = mod.score(q(["14909"]), result("the cpu tier served 14,909 requests"))
    assert ok


def test_currency_and_trailing_zero_match():
    ok, _ = mod.score(q(["324.80"]), result("total cost is $324.8"))
    assert ok


def test_rounding_within_tolerance_matches():
    ok, _ = mod.score(q(["10.83"]), result("the average is $10.827 per day"))
    assert ok


def test_wrong_number_still_fails():
    ok, detail = mod.score(q(["6650"]), result("the gpu tier served 6,651 requests"))
    assert not ok and detail["missing"] == ["6650"]


def test_missing_number_still_fails():
    ok, detail = mod.score(q(["2026-09-13", "692"]), result("busiest was September 13, 2026"))
    assert not ok and "692" in detail["missing"]


def test_nonnumeric_expected_stays_strict():
    ok, _ = mod.score(q(["capacity"]), result("mainly a capacity problem"))
    assert ok
    ok, _ = mod.score(q(["capacity"]), result("mainly a configuration problem"))
    assert not ok
