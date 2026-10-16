"""Builds site/data/tenet.json, the data file of the static demo page, from the run logs.

Sources (nothing is read from the network):
- results/e2e-log.jsonl: the live end-to-end test (escrow v3 on Arc testnet, judges v2 on Bradbury), the raw
  log written by relayer/e2e.py. It is kept out of the repository: this script writes results/e2e-log-en.jsonl,
  the same rows with the labels of the "checks" rows in English, and reads that copy when the raw log is absent;
- results/br-log.jsonl and cases/br-cases.json: the Bradbury run of the two judges (10 cases);
- results/attest-mail.jsonl: Lacre attestations of the Demo Shop emails;
- contracts/judge_build.json, relayer/e2e-state.json, relayer/e2e.py (cases and expected verdicts);
- results/*-report.txt: local committee measurements.

Run it again after every end-to-end session (a Python with genlayer-py 0.16.3, see README.md):
    python tools/lacre_boot.py tools/make_site_data.py
"""
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relayer"))
import e2e as E  # noqa: E402  (cases, expected verdicts, addresses)

OUT = ROOT / "site" / "data" / "tenet.json"
LOG_RAW, LOG_EN = "results/e2e-log.jsonl", "results/e2e-log-en.jsonl"
# Official explorer per docs.arc.io (testnet.arcscan.app redirects here).
ARC_EXPLORER = "https://explorer.testnet.arc.io"
ARC_TX, ARC_ADDR = ARC_EXPLORER + "/tx/", ARC_EXPLORER + "/address/"
GL_TX, GL_ADDR = "https://explorer-bradbury.genlayer.com/tx/", "https://explorer-bradbury.genlayer.com/address/"
ROUTER = "0xEf37cb72C3A9dD6bCE2f3575B75c94C555F9c8d9"

# What each live case is and what is still scheduled (UTC dates). Kept here, next to the expected
# verdicts in relayer/e2e.py, so the page never states a plan the logs do not back.
LIVE = {
    "A": {"title": "Late delivery, partial refund", "path": "late",
          "story": "The order arrives 3 days after the promised date. The buyer presents the store's own signed emails "
                   "(order confirmation and delivery notice), attested on Lacre. Policy: 50% refund after 2 days of grace.",
          "stage": "Paid; order confirmation email attested; waiting for the delivery date",
          "next": [{"date": "2026-10-17", "what": "Delivery email signed and attested, claim, judgment, settlement"}]},
    "B": {"title": "Not as described, store disputes", "path": "not_as_described",
          "story": "An unlocked phone arrives locked to a carrier. The store disputes with a fact (IMEI check), the judge "
                   "opens a closing round, both sides answer, and the claim is not proven.", "next": []},
    "C": {"title": "Not delivered, store silent", "path": "not_delivered",
          "story": "The order never arrives and the store does not answer within 72 hours. Policy: full refund from 10 days "
                   "after the promised date.",
          "stage": "Paid; waiting until 10 days after the promised date to claim",
          "next": [{"date": "2026-10-24", "what": "Claim (10 days after the promised date)"},
                   {"date": "2026-10-27", "what": "No-response marker after 72 hours, judgment, settlement"}]},
    "D": {"title": "Proof requested, never sent", "path": "not_as_described",
          "story": "A laptop arrives without its charger; the claim has no proof and the store gives a general denial. The "
                   "judge asks for proof; if the buyer sends none in 7 days, anyone releases the payment to the store.",
          "stage": "Claim open; proof requested on 2026-10-13 15:02 UTC; the buyer has 7 days",
          "next": [{"date": "2026-10-20", "time_utc": "15:02", "what": "releaseUnproven: payment released to the store"}]},
    "E": {"title": "Not as described, store admits", "path": "not_as_described",
          "story": "Running shoes arrive in the wrong size and the store admits the mistake. Full refund the same day.",
          "next": []},
}
BR_INFO = {
    "M1": ("mail", "late", "Late delivery: shipped email first, delivered email in a second step"),
    "M2": ("mail", "late", "On time: confirmation and delivery emails in one step"),
    "M3": ("mail", "late", "An email about another order is ignored (code I8)"),
    "M4": ("mail", "late", "Claim that is not canonical JSON"),
    "S1": ("subjective", "not_as_described", "Store admits"),
    "S2": ("subjective", "not_as_described", "Item arrived as described"),
    "S3": ("subjective", "not_as_described", "Store disputes with a fact twice (closing round)"),
    "S4": ("subjective", "not_delivered", "Store only says it shipped"),
    "S5": ("subjective", "not_delivered", "Store did not answer (no-response marker)"),
    "S6": ("subjective", "not_as_described", "Incomplete claim"),
}
ACTOR = {"buyer": "buyer", "merchant": "store", "signer": "relayer"}
# Labels of the "checks" rows of results/e2e-log.jsonl (written in Spanish on day 0); values unchanged.
CHECK_LABELS = {
    "openClaim desde el relayer": "openClaim sent by the relayer",
    "submit de un envio del comprador desde el relayer": "a buyer submission sent by the relayer",
    "proposeVerdict con otro hash de reclamo": "proposeVerdict with another claim hash",
    "proposeVerdict con otra cadena": "proposeVerdict with another chain",
    "releaseUnproven antes de 7 dias": "releaseUnproven before the 7 day proof window ends",
}


def jsonl(path):
    p = ROOT / path
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def e2e_log():
    """Rows of the live test. From the raw log when present, also writing its English copy; else from the copy."""
    raw = ROOT / LOG_RAW
    if not raw.exists():
        return jsonl(LOG_EN)
    rows = jsonl(LOG_RAW)
    en = [dict(r, results={CHECK_LABELS.get(k, k): v for k, v in r["results"].items()}) if r.get("op") == "checks" else r
          for r in rows]
    (ROOT / LOG_EN).write_text("".join(json.dumps(r) + "\n" for r in en), encoding="ascii")
    return rows


def usdc_gas(row):
    return round(int(row["cost_wei"]) / 1e18, 6) if row.get("cost_wei") else None


def gen(row):
    return round(int(row["l2_cost_wei"]) / 1e18, 9) if row.get("l2_cost_wei") else None


def usdc_text(cents):
    """Amounts in page texts are always in USDC: 100 cents -> "1.00 USDC"."""
    return "%.2f USDC" % (int(cents) / 100)


def verdict_view(v):
    keys = ("outcome", "refund_cents", "reason", "action", "final", "judged_at", "chain", "claim_hash", "ignored")
    return {k: v[k] for k in keys if k in v}


def live_cases(rows):
    out = []
    for cid, info in LIVE.items():
        c = E.CASES[cid]
        mine = [r for r in rows if r.get("case") == cid]
        timeline, verdicts, attempts, sends = [], [], {}, {}
        claim = None
        for r in mine:
            op = r.get("op")
            if op in ("approve", "pay", "claim", "submit", "mark", "act", "execute", "unproven") and r.get("state") == "ok":
                name = {"approve": "Approve USDC for the escrow", "pay": "Pay into escrow", "claim": "Open claim",
                        "execute": "Execute verdict", "unproven": "Release unproven claim to the store"}.get(op)
                if op == "submit":
                    name = "Submit: %s" % r.get("name")
                elif op == "mark":
                    name = "Marker: %s" % r.get("name")
                elif op == "act":
                    name = {"propose": "Propose verdict on Arc", "open_closing_round": "Open closing round on Arc",
                            "request_proof": "Request proof on Arc"}.get(r.get("name"), r.get("name"))
                timeline.append({"at": r["at"], "chain": "arc", "actor": ACTOR.get(r.get("role"), r.get("role")),
                                 "action": name, "tx": r["tx"], "url": ARC_TX + r["tx"], "gas_used": r.get("gas_used"),
                                 "gas_usdc": usdc_gas(r)})
                if op == "claim":
                    claim = {"text": r.get("claim"), "hash": next((e["claim_hash"] for e in r.get("events", [])
                                                                  if e["name"] == "ClaimOpened"), None)}
            elif op == "judge" and not r.get("acted"):
                # One timeline entry per judge transaction: the send (time, cost, link) and its result.
                a = attempts.setdefault(r["step"], [])
                if r["state"] == "sent":
                    a.append({"tx": r["tx"], "url": GL_TX + r["tx"], "gen": gen(r), "result": "pending"})
                    sends[r["tx"]] = {"at": r["at"], "chain": "bradbury", "actor": "relayer",
                                      "action": "Step %d sent to the judge, attempt %d: pending" % (r["step"], r["attempt"]),
                                      "tx": r["tx"], "url": GL_TX + r["tx"], "gen": gen(r)}
                    timeline.append(sends[r["tx"]])
                else:
                    for x in a:
                        if x["tx"] == r["tx"]:
                            x["result"] = "no consensus, resent" if r["state"] == "resend" else "accepted"
                            x["votes"] = r.get("votes")
                    if r["state"] == "as_expected":
                        v = verdict_view(r["verdict"])
                        verdicts.append({"step": r["step"], "verdict": v, "expected": c["steps"][r["step"] - 1],
                                         "matches_expected": True, "votes": r.get("votes"), "tx": r["tx"],
                                         "url": GL_TX + r["tx"]})
                        result = "%s %s (%s)" % (v["outcome"], usdc_text(v["refund_cents"]), v["reason"])
                    else:
                        result = "no consensus (%s), resent" % r.get("final_result")
                    if r["tx"] in sends:
                        sends[r["tx"]]["action"] = sends[r["tx"]]["action"].rsplit(": ", 1)[0] + ": " + result
            elif op == "mail":
                timeline.append({"at": r["at"], "chain": None, "actor": "store",
                                 "action": "Store email %s signed (DKIM, shop.rpmdev.app)" % r["name"]})
        if cid == "A":
            att = jsonl("results/attest-mail.jsonl")
            for r in att:
                if r.get("id") in ("X01", "X02") and r.get("state") == "confirmed":
                    tx = next((x["tx"] for x in att if x.get("id") == r["id"] and x.get("state") == "sent"), None)
                    timeline.append({"at": r["at"], "chain": "bradbury", "actor": "relayer",
                                     "action": "Email %s attested on Lacre: record %s, signature %s, domain %s" % (
                                         r["id"], r["record_id"], "valid" if r["valid"] else "not valid",
                                         "aligned" if r["aligned"] else "not aligned"),
                                     "tx": tx, "url": GL_TX + tx if tx else None, "gen": float(r.get("cost_gen") or 0)})
        timeline.sort(key=lambda t: t["at"])
        settled = [ev for r in mine for ev in r.get("events", []) if ev["name"] == "OrderSettled"]
        settle_row = next((r for r in mine if r.get("op") in ("execute", "unproven") and r.get("state") == "ok"), None)
        status = "settled" if settled else "in_progress"
        out.append({
            "id": cid, "title": info["title"], "path": info["path"], "story": info["story"], "judge": c["judge"],
            "order_number": c["order"], "order_ref": E.mail_v1.order_ref(c["order"]), "amount_usdc": c["amount"] / 1e6,
            "status": status, "stage": "Settled on Arc" if settled else info["stage"],
            "next_steps": [] if settled else info["next"],
            "expected": {"steps": c["steps"], "settlement_usdc": {k: v / 1e6 for k, v in c["settle"].items()}},
            "claim": claim, "verdicts": verdicts,
            "attempts": [{"step": k, "attempts": v} for k, v in sorted(attempts.items())],
            "settlement": ({"refund_usdc": settled[0]["refund"] / 1e6, "released_usdc": settled[0]["released"] / 1e6,
                            "tx": settle_row["tx"], "url": ARC_TX + settle_row["tx"],
                            "note": "Credited in the escrow; withdrawals at the end of the test."} if settled else None),
            "checks": [{"what": CHECK_LABELS.get(k, k), "want": v["want"], "got": v["got"], "at": r["at"]}
                       for r in mine if r.get("op") == "checks" for k, v in r["results"].items()],
            "timeline": timeline})
    return out


def br_cases(rows, cases):
    out = []
    for c in cases["cases"]:
        cid = c["id"]
        contract, path, title = BR_INFO[cid]
        mine = [r for r in rows if r.get("op") == "judge" and r.get("case") == cid]
        steps = []
        for n in range(1, len(c["steps"]) + 1):
            sent = [r for r in mine if r.get("step") == n and r["state"] == "sent"]
            done = {r["tx"]: r for r in mine if r.get("step") == n and r["state"] != "sent"}
            ok = next((done[r["tx"]] for r in sent if done.get(r["tx"], {}).get("state") == "as_expected"), None)
            steps.append({
                "step": n, "expected": c["expected_steps"][n - 1],
                "verdict": verdict_view(ok["verdict"]) if ok else None,
                "votes": ok.get("votes", {}).get("counts") if ok else None,
                "attempts": [{"tx": r["tx"], "url": GL_TX + r["tx"], "gen": gen(r),
                              "result": {"as_expected": "accepted", "resend": "no consensus, resent"}.get(
                                  done.get(r["tx"], {}).get("state"), done.get(r["tx"], {}).get("state"))}
                             for r in sent]})
        out.append({"id": cid, "contract": contract, "path": path, "title": title, "claim_hash": c["claim_hash"],
                    "steps": steps, "passed": all(s["verdict"] is not None for s in steps)})
    return out


def report_numbers():
    def grab(path, pattern):
        m = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"))
        return m.groups() if m else None
    c3 = grab("results/local-c3-report.txt", r"runs (\d+).*readings (\d+), reported cost ([\d.]+)")
    nd = grab("results/local-nd-report.txt", r"runs (\d+), readings (\d+), reported cost ([\d.]+)")
    b3 = grab("results/local-b3-report.txt", r"readings (\d+), reported cost ([\d.]+)")
    k17b = jsonl("results/local-k17b.jsonl")
    return {
        "committee": "5 models through OpenRouter (Llama 3.3 70B, Qwen3 235B, Gemma 3 27B, Mistral Small 3.2, "
                     "DeepSeek V3), majority of 3 out of 5, same prompts as the deployed judges",
        "runs": [
            {"id": "C3", "what": "Not as described: two closed questions and the closing round", "runs": int(c3[0]),
             "readings": int(c3[1]), "cost_usd": float(c3[2]),
             "results": {"correct decision": "310 / 310", "wrong refund": "0 / 310", "prompt injection that wins": "0 / 40"}},
            {"id": "ND", "what": "Not delivered: the store's answer", "runs": int(nd[0]), "readings": int(nd[1]),
             "cost_usd": float(nd[2]),
             "results": {"correct decision": "320 / 320", "wrong refund": "0 / 320", "wrong denial": "0 / 320",
                         "prompt injection that wins": "0 / 40"}},
            {"id": "B3", "what": "Store emails: event type and date", "readings": int(b3[0]), "cost_usd": float(b3[1]),
             "results": {"correct type": "180 / 180", "correct date": "60 / 60", "prompt injection that wins": "0 / 10"}},
            {"id": "K17B", "what": "Case B store answer reworded for an October order",
             "runs": len({r["pass"] for r in k17b}), "readings": len(k17b),
             "cost_usd": round(sum((r.get("usage") or {}).get("cost", 0) or 0 for r in k17b), 4),
             "results": {q: "%d / 50" % sum(1 for r in k17b if r["question"] == q and r["verdict"] == v)
                         for q, v in (("q1", "differs"), ("q2", "disputes_with_fact"), ("q2r2", "disputes_with_fact"))}},
        ],
        "local_checks": [
            {"what": "Judges v2 in Lacre's simulated GenVM SDK (all paths, error codes, equivalence with the measured "
                     "modules)", "result": "pass"},
            {"what": "Escrow v3 Foundry tests", "result": "39 unit tests and 3 invariants (256 runs, depth 60) pass"},
            {"what": "End-to-end rehearsal on a local chain with the same tools (cases A to E)",
             "result": "pass: 6 of 6 steps, settlements exact to the cent, relayer cannot alter the buyer's claim"},
        ],
    }


def escrow_windows():
    """RESPONSE_WINDOW, CLOSING_WINDOW and PROOF_WINDOW of evm/src/RefundEscrow.sol, in seconds."""
    src = (ROOT / "evm" / "src" / "RefundEscrow.sol").read_text(encoding="utf-8")
    unit = {"minutes": 60, "hours": 3600, "days": 86400}
    out = {}
    for name in ("RESPONSE", "CLOSING", "PROOF"):
        m = re.search(r"constant %s_WINDOW = (\d+) (minutes|hours|days);" % name, src)
        out["%s_window_seconds" % name.lower()] = int(m.group(1)) * unit[m.group(2)]
    return out


def contracts(br, state, e2e_rows):
    final = {r["kind"]: r for r in br if r.get("op") == "deploy" and r.get("state") == "final"}
    build = json.loads((ROOT / "contracts" / "judge_build.json").read_text(encoding="ascii"))
    deploy = next(r for r in e2e_rows if r.get("op") == "deploy" and r.get("state") == "ok")
    out = [{"name": "RefundEscrow v3", "chain": "arc", "address": state["escrow"], "url": ARC_ADDR + state["escrow"],
            "deploy_tx": deploy["tx"], "deploy_url": ARC_TX + deploy["tx"], "gas_used": deploy["gas_used"],
            "deploy_cost_usdc": usdc_gas(deploy), "source": "evm/src/RefundEscrow.sol",
            "params": {"token": "USDC", "cap_per_order_usdc": E.CAP / 1e6, "verdict_delay_seconds": E.VERDICT_DELAY,
                       "store_hold_days": E.HOLD // 86400, **escrow_windows()}}]
    for kind, name in (("mail", "Judge: store emails (late)"), ("subjective", "Judge: not as described, not delivered")):
        r = final[kind]
        src = "contracts/judge_%s.py" % kind
        out.append({"name": name, "chain": "bradbury", "address": r["address"], "url": GL_ADDR + r["address"],
                    "deploy_tx": r["tx"], "deploy_url": GL_TX + r["tx"], "gas_used": r.get("l2_gas_used"),
                    "deploy_cost_gen": gen(r), "bytes": build[src]["bytes"], "sha256": build[src]["sha256"],
                    "prompt_hash": r.get("prompt_hash"), "methods": r.get("schema_methods"), "source": src})
    out.append({"name": "Lacre Router (email attestations)", "chain": "bradbury", "address": ROUTER,
                "url": GL_ADDR + ROUTER, "project_url": "https://lacre.in-sidr.xyz",
                "source": "github.com/eudomar500/lacre (MIT, Insidr Labs)"})
    return out


def main():
    e2e_rows = e2e_log()
    br_rows = jsonl("results/br-log.jsonl")
    state = json.loads((ROOT / "relayer" / "e2e-state.json").read_text(encoding="utf-8"))
    br = json.loads((ROOT / "cases" / "br-cases.json").read_text(encoding="ascii"))
    who = {r["role"]: r["from"] for r in e2e_rows if r.get("role") in ("buyer", "merchant", "signer")}
    data = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "project": {"name": "Tenet", "tagline": "Buyer protection for stablecoin payments."},
        "networks": {
            "arc": {"name": "Arc testnet", "chain_id": E.CHAIN_ID, "explorer": ARC_EXPLORER,
                    "tx_url": ARC_TX, "address_url": ARC_ADDR, "usdc": E.USDC, "faucet": "https://faucet.circle.com"},
            "bradbury": {"name": "GenLayer Bradbury testnet", "explorer": "https://explorer-bradbury.genlayer.com",
                         "tx_url": GL_TX, "address_url": GL_ADDR}},
        "roles": {"buyer": who.get("buyer"), "store": who.get("merchant"), "signer": who.get("signer")},
        "contracts": contracts(br_rows, state, e2e_rows),
        "terms": {"terms_hash": E.TERMS_HASH, "store": "Demo Shop (shop.rpmdev.app)",
                  "rules": [{"event": r["event"], "refund_percent": r["refund_percent"], "wait_from": r["wait_from"],
                             "wait_days": r["wait_days"], "deadline_from": r["deadline_from"],
                             "deadline_days": r["deadline_days"], "late_grace_days": r["late_grace_days"]}
                            for r in E.BR["structure"]["rules"]]},
        "live_cases": live_cases(e2e_rows),
        "bradbury_run": {"summary": "10 of 10 verdicts as expected, read in final state; 2 resends after transactions "
                                    "that ended without votes", "cases": br_cases(br_rows, br)},
        "measurements": report_numbers(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n", encoding="ascii")
    print("%s: %d live cases (%s), %d Bradbury cases" % (
        OUT.relative_to(ROOT), len(data["live_cases"]),
        ", ".join("%s %s" % (c["id"], c["status"]) for c in data["live_cases"]), len(data["bradbury_run"]["cases"])))


if __name__ == "__main__":
    main()
