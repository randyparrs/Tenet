"""Tests of the date built in code for store emails (arbiter/mail_llm_v2.resolve_date).

Usage: py -3.12 tests/test_resolve_date.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arbiter"))
import mail_llm_v2 as m  # noqa: E402

r = m.resolve_date


def test_written_date_is_kept():
    assert r("9|15|2026", "Expected delivery: Tuesday, September 15, 2026.", "2026-09-03") == "2026-09-15"
    assert r("9|17|2026", "Llega el jueves 17 de septiembre de 2026.", "2026-09-11") == "2026-09-17"


def test_year_not_written_is_discarded_and_deduced_from_the_order_date():
    text = "It arrives Friday, Sept 18."
    for invented in ("9|18|2020", "9|18|2023", "9|18|2024", "9|18|"):
        assert r(invented, text, "2026-09-12") == "2026-09-18", invented


def test_deduction_crosses_the_year_end():
    assert r("1|3|", "It arrives January 3.", "2026-12-20") == "2027-01-03"
    assert r("12|28|", "It arrives December 28.", "2026-12-20") == "2026-12-28"


def test_weekday_that_does_not_match_leaves_it_empty():
    assert r("9|18|", "It arrives Thursday, Sept 18.", "2026-09-12") == ""
    assert r("9|17|2026", "Llega el viernes 17 de septiembre de 2026.", "2026-09-11") == ""


def test_day_or_month_not_written_leaves_it_empty():
    assert r("9|19|2026", "It arrives Friday, Sept 18, 2026.", "2026-09-12") == ""
    assert r("10|18|2026", "It arrives Friday, Sept 18, 2026.", "2026-09-12") == ""
    assert r("9||2026", "It arrives in September 2026.", "2026-09-12") == ""
    assert r("", "No date here.", "2026-09-12") == ""


def test_impossible_dates_are_empty():
    assert r("2|30|", "It arrives February 30.", "2026-01-10") == ""


def test_canonical_form():
    assert m.canonical("date", '{"month": 9, "day": 18, "year": null}') == "9|18|"
    assert m.canonical("date", '{"month": null, "day": null, "year": null}') == "||"
    assert m.canonical("date", '{"month": 13, "day": 18, "year": null}') is None
    assert m.canonical("date", '{"month": 9, "day": 18}') is None
    assert m.canonical("date", '{"month": "9", "day": 18, "year": null}') is None
    assert m.canonical("type", '{"verdict": "shipped"}') == "shipped"
    assert m.PROMPTS["type"] == m.mail_llm.PROMPTS["type"]


def test_the_set_resolves_to_what_b2_expects_when_the_parts_are_copied_right():
    data = json.load(open(ROOT / "cases" / "mail-set.json", encoding="utf-8"))
    copied = {"E05": "9|15|2026", "E06": "9|24|2026", "E07": "9|24|2026", "E15": "9|17|2026",
              "E17": "9|18|", "E18": "9|22|2026"}
    for x in data["positives"]:
        if x["id"] in copied:
            text = x["headers"]["Subject"] + "\n" + x["body"]
            assert r(copied[x["id"]], text, x["order_date"]) == x["expected_date_b2"], x["id"]


def test_delivery_date_outside_order_window_is_discarded():
    data = json.load(open(ROOT / "cases" / "mail-set.json", encoding="utf-8"))
    e18 = next(x for x in data["positives"] if x["id"] == "E18")
    text = e18["headers"]["Subject"] + "\n" + e18["body"]
    # The E18 injection asks for 2026-01-01, which is written: the range stops it (before the order).
    assert e18["order_date"] == "2026-09-12"
    assert r("1|1|2026", text, e18["order_date"]) == ""
    assert r("9|22|2026", text, e18["order_date"]) == "2026-09-22"
    # Edges: the order day and 120 days later are valid; one more, or one before the order, are not.
    assert r("9|12|2026", "Arrives September 12, 2026.", "2026-09-12") == "2026-09-12"
    assert r("1|10|2027", "Arrives January 10, 2027.", "2026-09-12") == "2027-01-10"
    assert r("1|11|2027", "Arrives January 11, 2027.", "2026-09-12") == ""
    assert r("9|11|2026", "Arrives September 11, 2026.", "2026-09-12") == ""


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d of %d passed" % (len(tests), len(tests)))
