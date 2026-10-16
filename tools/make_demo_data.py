"""Builds worker/src/demo-data.json, everything the demo Worker and the demo page read that is fixed
before running (README.md, "The Demo Shop runs on minutes"): the demo store's terms, the six scenarios with their measured texts
and expected verdicts, the email templates, the escrow ABI and, once deployed, the addresses.

Texts come from the measured case files, never retyped: cases/subjective-c3.json (K08, K12),
cases/k17b.json (K17B), cases/nd.json (G1) or cases/g1d.json (G1D, G1 without dates: used only
if results/local-g1d.jsonl measured it 50 of 50 as expected). Addresses come from relayer/demo-state.json and
results/demo-judges-log.jsonl when they exist (null before the deploys).

    python tools/lacre_boot.py tools/make_demo_data.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "relayer"), str(ROOT / "tools")]
import demo_setup as S  # noqa: E402  (demo terms; reads no network at import)

OUT = ROOT / "worker" / "src" / "demo-data.json"
C3 = {c["id"]: c for c in json.loads((ROOT / "cases" / "subjective-c3.json").read_text(encoding="utf-8"))["cases"]}
K17B = json.loads((ROOT / "cases" / "k17b.json").read_text(encoding="utf-8"))["cases"][0]
ND = {c["id"]: c for c in json.loads((ROOT / "cases" / "nd.json").read_text(encoding="utf-8"))["cases"]}
AMOUNT_CENTS = 100  # every demo order is 1.00 USDC


def not_delivered_case():
    """G1D if its measurement gave general_denial 50 of 50 (10 passes x 5 models), else the measured G1."""
    g1d = json.loads((ROOT / "cases" / "g1d.json").read_text(encoding="utf-8"))["cases"][0]
    log = ROOT / "results" / "local-g1d.jsonl"
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    good = [r for r in rows if r["case"] == "G1D" and r["question"] == "q2" and r["verdict"] == "general_denial"]
    if len(rows) == 50 and len(good) == 50:
        return dict(g1d, source="G1D")
    return dict(ND["G1"], source="ND G1")


G1 = not_delivered_case()


def nad(case, source):
    return {"description": case["description"], "account": case["claim"]["account"], "promised": case["claim"]["promised"],
            "received": case["claim"]["received"], "proof_kind": case["claim"]["proof_kind"],
            "proof": case["claim"]["proof"], "source": source}


def step(outcome, cents, reason, action):
    return {"outcome": outcome, "refund_cents": cents, "reason": reason, "action": action}


SCENARIOS = [
    {"id": "L1", "title": "Late delivery", "path": "late", "judge": "mail", "event": "late",
     "product": {"name": "Parcel, express delivery", "art": "parcel", "goes_wrong": "It arrives one day after the promised date.",
                 "wait": "verdict tomorrow"},
     "summary": "The order arrives one day after the promised date. The store's own signed emails prove it.",
     "store": "confirms the order today and sends the delivery notice tomorrow", "next_day": True,
     "steps": [step("REFUND", 50, "per policy", "decide")], "settle": {"buyer": 50, "store": 50}},
    {"id": "N1", "title": "Not as described, the store admits",
     "product": {"name": "Wool sweater, size M, red", "art": "sweater", "goes_wrong": "It arrives green.", "wait": "about 35 min"}, "path": "not_as_described", "judge": "subjective",
     "event": "not_as_described", "claim": nad(C3["K08"], "C3 K08"), "response": C3["K08"]["response"],
     "summary": "A red sweater arrives green and the store admits the mistake.",
     "store": "admits the mistake", "steps": [step("REFUND", 100, "per policy", "decide")],
     "settle": {"buyer": 100, "store": 0}},
    {"id": "N2", "title": "Not as described, the store disputes",
     "product": {"name": "iPhone 13, 128 GB, unlocked", "art": "phone", "goes_wrong": "It arrives locked to a carrier.",
                 "wait": "about 75 min"}, "path": "not_as_described", "judge": "subjective",
     "event": "not_as_described", "claim": nad(K17B, "K17B"), "response": K17B["response"],
     "closing": {"buyer": K17B["round2"]["proof"], "store": K17B["round2"]["response"]},
     "summary": "An unlocked phone arrives locked. The store disputes with a fact twice, so the claim is not proven.",
     "store": "disputes with a fact, then again in the closing round",
     "steps": [step("NOT_YET", 0, "closing round", "open_closing_round"), step("DENY", 0, "claim not proven", "decide")],
     "settle": {"buyer": 0, "store": 100}},
    {"id": "N3", "title": "Not as described, no proof",
     "product": {"name": "Laptop, charger included", "art": "laptop", "goes_wrong": "There is no charger in the box, and no proof of it.",
                 "wait": "about 40 min"}, "path": "not_as_described", "judge": "subjective",
     "event": "not_as_described", "claim": nad(C3["K12"], "C3 K12"), "response": C3["K12"]["response"],
     "summary": "A laptop arrives without its charger. The claim has no proof, the judge asks for it and none is sent.",
     "store": "denies in general", "steps": [step("NOT_YET", 0, "proof required", "request_proof")],
     "after": "release_unproven", "settle": {"buyer": 0, "store": 100}},
    {"id": "D1", "title": "Not delivered, the store says it shipped",
     "product": {"name": "Parcel, standard delivery", "art": "parcel", "goes_wrong": "It never arrives.", "wait": "about 35 min"}, "path": "not_delivered", "judge": "subjective",
     "event": "not_delivered", "account": G1["account"], "response": G1["response"], "source": G1["source"],
     "summary": "The order never arrives. The store only says it shipped it.",
     "store": "says it shipped the order", "steps": [step("REFUND", 100, "per policy", "decide")],
     "settle": {"buyer": 100, "store": 0}},
    {"id": "D2", "title": "Not delivered, the store does not answer",
     "product": {"name": "Parcel, economy delivery", "art": "parcel", "goes_wrong": "It never arrives.", "wait": "about 40 min"}, "path": "not_delivered", "judge": "subjective",
     "event": "not_delivered", "account": G1["account"], "response": None, "source": G1["source"],
     "summary": "The order never arrives and the store does not answer within the window.",
     "store": "does not answer", "steps": [step("REFUND", 100, "per policy", "decide")],
     "settle": {"buyer": 100, "store": 0}},
]

MAIL = {
    "from": "Demo Shop Orders <orders@demo.rpmdev.app>", "to": "buyer@example.com",
    # The Demo Shop templates measured in B3 (cases/mail-set.json E01 and E03), with the demo domain.
    "confirmed": {"subject": "Order {order} confirmed",
                  "body": "Hi,\r\n\r\nThanks for your order {order}.\r\nTotal: USD {total}\r\nEstimated delivery: {day}\r\n\r\nDemo Shop\r\n"},
    "delivered": {"subject": "Delivered: order {order}",
                  "body": "Your order {order} was delivered on {day}.\r\nWe hope you enjoy it.\r\n"},
}


def addresses():
    st = json.loads((ROOT / "relayer" / "demo-state.json").read_text(encoding="utf-8")) \
        if (ROOT / "relayer" / "demo-state.json").exists() else {}
    judges = {}
    log = ROOT / "results" / "demo-judges-log.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("op") == "deploy" and r.get("state") == "final":
                judges[r["kind"]] = r["address"]
    return {"escrow": st.get("escrow"), "deploy_block": st.get("deploy_block"), "usdc": S.E.USDC,
            "judges": {"mail": judges.get("mail"), "subjective": judges.get("subjective")},
            "store": S.E.address("demo_store"), "relayer": S.E.address("demo_relayer"),
            "router": S.E.BR["router"]}


def main():
    art = S.demo_art()
    data = {
        "version": 1,
        "chain_id": S.E.CHAIN_ID, "amount_cents": AMOUNT_CENTS, "cap_cents": S.CAP // 10**4,
        "verdict_delay_seconds": S.VERDICT_DELAY,
        "windows_seconds": {"response": 300, "closing": 300, "proof": 300},
        "limits": {"per_address_per_day": 3, "per_day": 30, "stall_seconds": 6 * 3600},
        "terms": {"domain": S.DOMAIN, "selector": "demo1", "structure": S.STRUCTURE, "profile": S.demo_profile(),
                  "terms_hash": S.TERMS_HASH, "hold_seconds": S.HOLD_DAYS * 86400},
        "scenarios": SCENARIOS, "mail": MAIL,
        "addresses": addresses(),
        "escrow_abi": [x for x in art["abi"] if x["type"] in ("function", "event", "error")],
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n", encoding="ascii")
    # The page shows the Demo Shop's products from this static copy, before and without the Worker.
    shop = {k: data[k] for k in ("chain_id", "amount_cents", "windows_seconds", "limits")}
    shop["scenarios"] = [{k: x.get(k) for k in ("id", "title", "path", "summary", "store", "product", "next_day", "steps", "settle")}
                         for x in SCENARIOS]
    (ROOT / "site" / "data" / "demo-shop.json").write_text(json.dumps(shop, indent=1, ensure_ascii=True) + "\n", encoding="ascii")
    print("%s: %d scenarios; escrow %s; judges %s" % (OUT.relative_to(ROOT), len(SCENARIOS),
                                                       data["addresses"]["escrow"], data["addresses"]["judges"]))


if __name__ == "__main__":
    main()
