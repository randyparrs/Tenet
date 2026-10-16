"""Tests of how a claim moves (arbiter/claim_flow.py): two paths, each at most once.

Usage: py -3.12 tests/test_claim_flow.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arbiter"))
sys.path.insert(0, str(ROOT / "cases"))
import claim_flow as f  # noqa: E402
from make_subjective_cases import POLICY, facts  # noqa: E402

DESC = "Samsung Galaxy S23, 256 GB, new, factory sealed."
NO_PROOF = {"account": "It has 128 GB.", "promised": "256 GB", "received": "128 GB", "proof_kind": "", "proof": ""}
PROOF = dict(NO_PROOF, proof_kind="label", proof="SM-S911B 128GB")
F = facts()


def raises(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return True
    return False


def test_proof_path_requested_once_then_denied_without_proof():
    s = dict(f.NEW_STATE)
    action, d, s = f.step(s, "differs", "general_denial", NO_PROOF, DESC, POLICY, F)
    assert (action, d) == ("request_proof", ("NOT_YET", 0, "proof required"))
    # Another evaluation before the deadline: waits; there is no second request.
    action, d, s2 = f.step(s, "differs", "general_denial", NO_PROOF, DESC, POLICY, F, hours_since_proof_request=100)
    assert action == "wait" and d[0] == "NOT_YET" and s2 == s
    action, d, _ = f.step(s, "differs", "general_denial", NO_PROOF, DESC, POLICY, F, hours_since_proof_request=168)
    assert (action, d) == ("decide", ("DENY", 0, "proof not provided"))


def test_proof_path_submitted_but_still_malformed_is_not_proven():
    s = dict(f.NEW_STATE)
    _, _, s = f.step(s, "differs", "general_denial", NO_PROOF, DESC, POLICY, F)
    s = f.submit_proof(s, 20)
    malformed = dict(NO_PROOF, proof_kind="photo", proof="photo of the settings screen")
    action, d, _ = f.step(s, "differs", "general_denial", malformed, DESC, POLICY, F, hours_since_proof_request=30)
    assert (action, d) == ("decide", ("DENY", 0, "claim not proven"))


def test_proof_path_submitted_and_well_formed_is_refunded():
    s = dict(f.NEW_STATE)
    _, _, s = f.step(s, "differs", "general_denial", NO_PROOF, DESC, POLICY, F)
    s = f.submit_proof(s, 20)
    action, d, _ = f.step(s, "differs", "general_denial", PROOF, DESC, POLICY, F, hours_since_proof_request=30)
    assert (action, d) == ("decide", ("REFUND", 5000, "per policy"))


def test_proof_cannot_be_submitted_twice_late_or_unrequested():
    s = dict(f.NEW_STATE)
    assert raises(f.submit_proof, s, 1)
    _, _, s = f.step(s, "differs", "general_denial", NO_PROOF, DESC, POLICY, F)
    assert raises(f.submit_proof, s, 168)
    s = f.submit_proof(s, 1)
    assert raises(f.submit_proof, s, 2)


def test_closing_round_opens_once():
    s = dict(f.NEW_STATE)
    action, _, s = f.step(s, "differs", "disputes_with_fact", NO_PROOF, DESC, POLICY, F)
    assert action == "open_closing_round" and not s["closing_done"]
    closing = {"response": "We checked again: our test report shows 256 GB.", "q2": "disputes_with_fact", "proof": None}
    action, d, s = f.step(s, "differs", "disputes_with_fact", NO_PROOF, DESC, POLICY, F, closing=closing)
    assert (action, d) == ("decide", ("DENY", 0, "claim not proven")) and s["closing_done"]
    # A new contradiction does not open another round.
    action, d, _ = f.step(s, "differs", "disputes_with_fact", PROOF, DESC, POLICY, F)
    assert (action, d) == ("decide", ("DENY", 0, "claim not proven"))
    assert raises(f.step, s, "differs", "disputes_with_fact", PROOF, DESC, POLICY, F, closing)


def test_closing_round_admitted_or_silent_with_proof_is_refunded():
    for closing in ({"response": "You are right, we shipped the 128 GB unit.", "q2": "admits", "proof": None},
                    {"response": "", "q2": None, "proof": {"proof_kind": "label", "proof": "SM-S911B 128GB"}},
                    {"response": "We only sell what we list.", "q2": "general_denial", "proof": None}):
        claim = PROOF if closing["q2"] == "general_denial" else NO_PROOF
        _, d, s = f.step(dict(f.NEW_STATE), "differs", "disputes_with_fact", claim, DESC, POLICY, F, closing=closing)
        assert d == ("REFUND", 5000, "per policy"), closing
        assert s["closing_done"] and not s["proof_requested"]


def test_closing_round_without_proof_moves_to_proof_path_once():
    s = dict(f.NEW_STATE)
    closing = {"response": "", "q2": None, "proof": None}
    action, d, s = f.step(s, "differs", "disputes_with_fact", NO_PROOF, DESC, POLICY, F, closing=closing)
    assert action == "request_proof" and s == {"proof_requested": True, "proof_submitted": False, "closing_done": True,
                                               "closing": closing}
    # Neither path repeats: within the 7 days it waits for the proof; after them, DENY.
    action, d, _ = f.step(s, "differs", "disputes_with_fact", NO_PROOF, DESC, POLICY, F, hours_since_proof_request=10)
    assert action == "wait" and d == ("NOT_YET", 0, "proof required")
    assert raises(f.step, s, "differs", "disputes_with_fact", NO_PROOF, DESC, POLICY, F, closing)
    action, d, _ = f.step(s, "differs", "disputes_with_fact", NO_PROOF, DESC, POLICY, F, hours_since_proof_request=200)
    assert d == ("DENY", 0, "proof not provided")


def test_well_formed_proof_after_closing_round_is_refunded():
    # Written rule: the closing round ends without proof, proof is requested, the buyer sends it well
    # formed: REFUND. Malformed: DENY "claim not proven".
    s = dict(f.NEW_STATE)
    closing = {"response": "", "q2": None, "proof": None}
    _, _, s = f.step(s, "differs", "disputes_with_fact", NO_PROOF, DESC, POLICY, F, closing=closing)
    s = f.submit_proof(s, 10)
    action, d, _ = f.step(s, "differs", "disputes_with_fact", PROOF, DESC, POLICY, F, hours_since_proof_request=10)
    assert (action, d) == ("decide", ("REFUND", 5000, "per policy"))
    malformed = dict(NO_PROOF, proof_kind="photo", proof="photo of the box")
    action, d, _ = f.step(s, "differs", "disputes_with_fact", malformed, DESC, POLICY, F, hours_since_proof_request=10)
    assert (action, d) == ("decide", ("DENY", 0, "claim not proven"))


def test_no_closing_round_without_contradiction():
    closing = {"response": "x", "q2": "admits", "proof": None}
    assert raises(f.step, dict(f.NEW_STATE), "differs", "general_denial", PROOF, DESC, POLICY, F, closing)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d of %d passed" % (len(tests), len(tests)))
