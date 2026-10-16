"""Builds cases/br-cases.json: the 10 cases of the Bradbury run of the two judges, with the exact
claim text, the submissions of each step (canonical JSON), the chain of each step as the escrow
computes it, and the expected verdict, fixed here before running.

- Addresses: buyer = the signer wallet, store = a test address that does not sign. Terms = the Demo
  Shop test structure, 30 day hold.
- The late cases use the Lacre records that already exist (E01 to E18, records 10 to 27; requester
  the signer wallet). Their signatures (t=) are from September 2026: each order is paid before its
  emails were signed (otherwise they do not count: I9).
- Before writing, each case runs in the simulated SDK with records under the same ids and a
  committee that answers as expected: the verdict has to be the expected one and the chain the
  computed one.

Usage: LACRE_DIR=<lacre clone> py -3.12 cases/make_br_cases.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import judge_v2_stub_run as H  # noqa: E402

BUYER = "0x0f0c950043c4d0b570fb6a7ede0874df96966808"
MERCHANT = "0x7e7e3706a11671ae8d2ce56555df32321aa6d73b"
RECORDS = {}
for line in (ROOT / "results" / "attest-mail.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    # Only the Demo Shop set in cases/mail (the end-to-end emails live in cases/e2e).
    if r.get("record_id") and r.get("state") == "confirmed" and (ROOT / "cases" / "mail" / ("%s.eml" % r["id"])).exists():
        RECORDS[r["id"]] = r["record_id"]


def claim(order, event, amount, paid, claimed, extra=None):
    c = {"v": "claim-v1", "order_ref": H.mail_v1.order_ref(order), "order_number": order, "buyer": BUYER,
         "merchant": MERCHANT, "amount_cents": amount, "paid_at": paid, "claimed_at": claimed,
         "terms_hash": H.TERMS_HASH, "event": event}
    c.update(extra or {})
    return c


def ev(mid):
    import base64
    raw = (ROOT / "cases" / "mail" / ("%s.eml" % mid)).read_bytes()
    _, body = H.mail_v1.split_message(raw)
    return {"party": "buyer", "kind": "evidence", "content": {"record_id": RECORDS[mid],
                                                             "body_b64": base64.b64encode(body).decode()}}


def c3(cid):
    return next(x for x in H.C3["cases"] if x["id"] == cid)


def nd_case(cid):
    return next(x for x in H.ND["cases"] if x["id"] == cid)


def subjective(order, it, f):
    cl = it["claim"]
    return claim(order, "not_as_described", f["amount_cents"], H.unix(f["purchase_date"], 12), H.unix(f["claim_date"], 12),
                 {"description": it["description"], "account": cl.get("account", ""), "promised": cl["promised"],
                  "received": cl["received"], "proof_kind": cl["proof_kind"], "proof": cl["proof"],
                  "delivered_date": f["delivered_date"]})


def cases():
    out = []
    m2 = claim("DS-100231", "late", 4990, H.unix("2026-09-01"), H.unix("2026-10-01", 12))
    out.append(dict(id="M1", contract="mail", claim=claim("DS-100232", "late", 12000, H.unix("2026-09-03"),
                                                            H.unix("2026-10-12", 12)),
                    steps=[[ev("E05")], [ev("E07")]], answers=[{"type": "shipped", "date": "9|15|2026"},
                                                               {"type": "delivered", "date": "9|24|2026"}],
                    expected={"outcome": "REFUND", "refund_cents": 6000, "reason": "per policy"}))
    out.append(dict(id="M2", contract="mail", claim=m2, steps=[[ev("E01"), ev("E03")]],
                    answers=[lambda p: ("type", [{"verdict": "delivered" if "was delivered on" in p else "order_confirmed"}] * 5)
                             if "Question: what event of the order" in p else None],
                    expected={"outcome": "DENY", "refund_cents": 0, "reason": "per policy"}))
    out.append(dict(id="M3", contract="mail", claim=claim("DS-100231", "late", 4990, H.unix("2026-09-01"),
                                                            H.unix("2026-10-02", 12)),
                    steps=[[ev("E01"), ev("E04")]], answers=[{"type": "order_confirmed"}],
                    expected={"outcome": "NOT_YET", "refund_cents": 0, "reason": "signed emails required",
                              "ignored": [[1, "I8"]]}))
    out.append(dict(id="M4", contract="mail", claim=json.dumps(m2, sort_keys=True), steps=[[]], answers=[{}],
                    expected={"outcome": "INVALID_CLAIM", "refund_cents": 0, "reason": "invalid claim"}))
    for sid, cid in (("S1", "K07"), ("S2", "K01")):
        it = c3(cid)
        exp = it["expected_decision"]
        out.append(dict(id=sid, contract="subjective", claim=subjective("DS-%s" % cid, it, it["facts"]),
                        steps=[[H.response(it["response"])]],
                        answers=[{"q1": it["expected"]["q1"], "q2": (it["expected"]["q2"] or ["admits"])[0]}],
                        expected={"outcome": exp[0], "refund_cents": exp[1], "reason": exp[2]}))
    it = c3("K17")
    r2 = it["round2"]
    out.append(dict(id="S3", contract="subjective", claim=subjective("DS-K17", it, it["facts"]),
                    steps=[[H.response(it["response"])], H.closing(r2["response"], r2["proof"])],
                    answers=[{"q1": "differs", "q2": "disputes_with_fact"}, {"q1": "differs", "q2": "disputes_with_fact"}],
                    expected={"outcome": "DENY", "refund_cents": 0, "reason": "claim not proven"}))
    f = H.ND["facts"]
    g1 = nd_case("G1")
    nd_claim = lambda order, acc: claim(order, "not_delivered", f["amount_cents"], H.unix(f["purchase_date"], 12),  # noqa: E731
                                        H.unix(f["claim_date"], 12), {"account": acc, "promised_date": f["promised_date"]})
    out.append(dict(id="S4", contract="subjective", claim=nd_claim("DS-ND-G1", g1["account"]),
                    steps=[[H.response(g1["response"])]], answers=[{"q2": "general_denial"}],
                    expected={"outcome": "REFUND", "refund_cents": 5000, "reason": "per policy"}))
    out.append(dict(id="S5", contract="subjective", claim=nd_claim("DS-ND-NR", g1["account"]),
                    steps=[[H.marker("no_response")]], answers=[{}],
                    expected={"outcome": "REFUND", "refund_cents": 5000, "reason": "per policy"}))
    v1 = H.C3["incomplete"][0]
    out.append(dict(id="S6", contract="subjective", claim=subjective("DS-V1", {"description": v1["description"],
                                                                              "claim": v1["claim"]}, H.flow_facts()),
                    steps=[[H.response("We only sell what we list.")]], answers=[{}],
                    expected={"outcome": "INVALID_CLAIM", "refund_cents": 0, "reason": "invalid claim"}))
    return out


def scripted(ans, mid=None):
    if callable(ans):
        return ans
    if "q2" in ans and "q1" not in ans:  # not_delivered: a single question
        return lambda p: ("q2", [{"verdict": ans["q2"]}] * 5) if "the buyer says the order never arrived" in p else None
    return H.scripted(ans)


def dry_run(case):
    """The case through the simulated SDK, with Lacre records under the same ids as on Bradbury."""
    w = H.World(case["contract"])
    if case["contract"] == "mail":
        final = {}
        for mid, rid in RECORDS.items():
            raw = (ROOT / "cases" / "mail" / ("%s.eml" % mid)).read_bytes()
            final[rid] = dict(H.record_for(raw), requester=BUYER)
        w.node.verifier.final = final
    w.write(H.OWNER, "2026-10-12T00:00:00Z", "set_merchant", MERCHANT, json.dumps(
        {"domain": H.DOMAIN, "structure": H.STRUCTURE, "profile": H.MAIL["profile"], "terms_hash": H.TERMS_HASH}))
    text = case["claim"] if isinstance(case["claim"], str) else H.cj(case["claim"])
    chains, per_step = [], []
    for step, ans in zip(case["steps"], case["answers"]):
        r = w.judge(text, step, "2026-10-12T12:00:00Z", scripted(ans))
        assert r[0] == "ok", (case["id"], r)
        chains.append(w.chain(text))
        sv = w.verdict(text)
        per_step.append({k: sv.get(k) for k in ("action", "outcome", "refund_cents", "reason", "final")
                         if k in sv} | ({"ignored": sv["ignored"]} if "ignored" in sv else {}))
    v = w.verdict(text)
    return text, chains, v, per_step


def main():
    rows = []
    for case in cases():
        text, chains, v, per_step = dry_run(case)
        exp = case["expected"]
        raws = [[H.cj(x) for x in step] for step in case["steps"]]
        want_ignored = [[H.sha(raws[-1][i]), code] for i, code in exp.get("ignored", [])]
        ok = (v["outcome"], v["refund_cents"], v["reason"]) == (exp["outcome"], exp["refund_cents"], exp["reason"]) \
            and v["chain"] == chains[-1] and v["claim_hash"] == H.sha(text) \
            and (case["contract"] != "mail" or v.get("ignored", []) == want_ignored or exp["outcome"] == "INVALID_CLAIM")
        print("%s %-10s %-13s %s" % (case["id"], case["contract"], v["outcome"], "ok" if ok else "WRONG %s" % v))
        assert ok
        rows.append({"id": case["id"], "contract": case["contract"], "claim": text, "claim_hash": H.sha(text),
                     "chain0": H.chain0(H.sha(text)), "steps": raws, "chains": chains,
                     "expected": dict(exp, ignored=want_ignored) if "ignored" in exp else exp,
                     "expected_steps": per_step})
    out = ROOT / "cases" / "br-cases.json"
    out.write_text(json.dumps({"buyer": BUYER, "merchant": MERCHANT, "terms_hash": H.TERMS_HASH,
                               "structure": H.STRUCTURE, "profile": H.MAIL["profile"], "domain": H.DOMAIN,
                               "router": "0xEf37cb72C3A9dD6bCE2f3575B75c94C555F9c8d9", "cases": rows},
                              indent=1, ensure_ascii=True) + "\n", encoding="ascii")
    print(out, len(rows), "cases")


if __name__ == "__main__":
    main()
