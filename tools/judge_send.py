"""Deploy and run of the judge contracts on GenLayer Bradbury (the Bradbury run, cases in
cases/br-cases.json). One command at a time. The signer key is read from SIGNER_ENV and is never
printed or stored.

    <venv with genlayer-py>/python tools/lacre_boot.py tools/judge_send.py <command> ...

  deploy <mail|subjective> [--dry]   sends the deploy and waits for ACCEPTED; prints address and cost
  recover-deploy <mail|subjective>   resumes waiting for a deploy already sent (read only)
  confirm-deploy <mail|subjective>   waits for FINALIZED; checks deployed code, schema and prompt_hash
  terms <mail|subjective>            set_merchant for Demo Shop and waits for ACCEPTED
  confirm-terms <mail|subjective>    waits for FINALIZED and reads get_merchant in final state
  send <case> <step> [--dry]         one step of a case and waits for ACCEPTED
  confirm <case> <step>              waits for FINALIZED, reads the verdict in final state and compares it
  status                             everything logged

Run rules:
- one transaction in flight per contract; a step only after the previous one is confirmed;
- no consensus (transaction not executed, no verdict, or verdict NO_CONSENSUS): the same step is sent
  again with send, and it counts as a resend;
- a verdict different from the expected one accepted by a majority: results/br-STOP is written and
  nothing else is sent until it is reviewed;
- the verdict is confirmed by reading it in LATEST_FINAL (get_verdict of the step's chain), not from
  the transaction status.
Log: results/br-log.jsonl. relayer/e2e.py reuses the connection, send and wait helpers.
"""
import argparse
import base64
import contextlib
import datetime
import io
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lacre_boot  # noqa: E402,F401  (local.env, OS certificates and User-Agent; before genlayer_py)

LACRE = Path(os.environ.get("LACRE_DIR", ""))  # a clone of github.com/eudomar500/lacre (set in local.env)
SIGNER_ENV = Path(os.environ.get("SIGNER_ENV", ""))  # file with PRIVATE_KEY= (set in local.env)
sys.path[:0] = [str(LACRE), str(LACRE / "tools")]

import chain  # noqa: E402  (Lacre)
import txstate  # noqa: E402  (Lacre)
from genlayer_py.types import TransactionHashVariant  # noqa: E402

FINAL = TransactionHashVariant.LATEST_FINAL
LOG = ROOT / "results" / "br-log.jsonl"
STOP = ROOT / "results" / "br-STOP"
CASES = json.loads((ROOT / "cases" / "br-cases.json").read_text(encoding="ascii"))
CONTRACT = {"mail": ROOT / "contracts" / "judge_mail.py", "subjective": ROOT / "contracts" / "judge_subjective.py"}
FINAL_BUDGET_S, FINAL_POLL_S, PROGRESS_S = 4 * 3600, 30, 300
_VIEWS = ["get_claim", "get_merchant", "get_verdict", "judge", "owner", "prompt_hash", "set_merchant"]
EXPECTED_METHODS = {"mail": sorted(_VIEWS + ["router"]), "subjective": sorted(_VIEWS)}


def expected_prompt_hash(kind):
    """The prompt_hash the contract has to return: the one of the measured modules (B3; C3 and ND)."""
    sys.path.insert(0, str(ROOT / "arbiter"))
    import mail_llm_v3
    import not_delivered
    import subjective_v3
    if kind == "mail":
        return mail_llm_v3.PROMPT_SHA256
    return subjective_v3.PROMPT_SHA256 + "|" + not_delivered.PROMPT_SHA256


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def cj(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def private_key():
    for line in SIGNER_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("PRIVATE_KEY="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            return value if value.startswith("0x") else "0x" + value
    sys.exit("no PRIVATE_KEY in %s" % SIGNER_ENV)


def rows():
    return [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()] if LOG.exists() else []


def append(row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(row, at=now()), ensure_ascii=False) + "\n")


def last(**match):
    found = [r for r in rows() if all(r.get(k) == v for k, v in match.items())]
    return found[-1] if found else None


def connect(dry=False):
    os.environ["PROBE_PK"] = "0x" + secrets.token_hex(32) if dry else private_key()
    try:
        return chain.connect("bradbury")
    finally:
        os.environ.pop("PROBE_PK", None)


class Tee(io.StringIO):
    def write(self, s):
        sys.__stdout__.write(s)
        return super().write(s)


def send_captured(net, client, account, encoded, gas):
    """Lacre's chain.send, keeping what it prints to read the L2 hash and the receipt cost."""
    buf = Tee()
    with contextlib.redirect_stdout(buf):
        tx_id, used = chain.send(net, client, account, encoded, gas)
    text = buf.getvalue()
    pick = lambda pat: (re.findall(pat, text, re.M) or [""])[-1]  # noqa: E731
    return tx_id, {"l2_hash": pick(r"^L2 TX HASH\s*:\s*(\S+)"), "l2_gas_used": used,
                   "l2_cost_wei": pick(r"^L2 cost\s*:\s*(\d+) wei")}


def gen(wei):
    return "%.9f GEN" % (int(wei or 0) / 1e18)


def deployed(kind):
    r = last(op="deploy", kind=kind)
    if not r or not r.get("address"):
        sys.exit("%s is not deployed" % kind)
    return r


def stopped():
    if STOP.exists():
        sys.exit("STOPPED: %s. Nothing is sent until it is reviewed." % STOP.read_text(encoding="utf-8").strip())


def in_flight(kind):
    """A transaction in flight to this contract (sent and not confirmed)."""
    for r in reversed(rows()):
        if r.get("contract") == kind and r.get("op") in ("deploy", "terms", "judge"):
            if r.get("state") == "sent":
                done = [x for x in rows() if x.get("tx") == r.get("tx") and x.get("state") != "sent"]
                return None if done else r
            return None
    return None


def wait_final(client, tx):
    print("waiting for FINALIZED of %s (up to %d hours) ..." % (tx, FINAL_BUDGET_S // 3600))
    return txstate.wait_stored(client, tx, statuses=txstate.FINAL, budget=FINAL_BUDGET_S, interval=FINAL_POLL_S,
                               progress=PROGRESS_S)


def votes(tx):
    out = subprocess.run(["node", str(ROOT / "tools" / "tx_votes.mjs"), tx], capture_output=True, text=True, cwd=str(ROOT))
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else {}


# ---- deploy and terms ------------------------------------------------------------------------

def cmd_deploy(kind, dry):
    stopped()
    prev = last(op="deploy", kind=kind)
    if prev and prev.get("state") != "not_executed":
        sys.exit("%s already has a deploy logged (%s); not repeated. If it failed, run confirm-deploy %s first"
                 % (kind, prev.get("state"), kind))
    source = CONTRACT[kind].read_bytes()
    args = [CASES["router"]] if kind == "mail" else []
    account, client, net = connect(dry)
    print("signer %s, balance %s" % (account.address, gen(client.w3.eth.get_balance(account.address))))
    encoded = chain.deploy_calldata(client, account, source, args)
    gas = chain.estimate(net, client, account, encoded, final=dry)
    if dry:
        print("--dry: nothing sent")
        return
    tx, cost = send_captured(net, client, account, encoded, gas)
    append({"op": "deploy", "kind": kind, "contract": kind, "state": "sent", "tx": tx, "estimated_gas": gas,
            "bytes": len(source), **cost})
    receipt = chain.wait_accepted(client, tx)
    decoded = receipt.get("tx_data_decoded") or {}
    address = decoded.get("contract_address") or receipt.get("recipient")
    append({"op": "deploy", "kind": kind, "contract": kind, "state": "sent", "tx": tx, "address": address,
            "estimated_gas": gas, "bytes": len(source), **cost})
    print("DEPLOYED %s at %s; tx %s; L2 receipt cost %s (gas %s)" % (kind, address, tx, gen(cost["l2_cost_wei"]),
                                                                           cost["l2_gas_used"]))


def cmd_recover_deploy(kind):
    """Resumes waiting for a deploy already sent (for example after Ctrl+C): read only, sends nothing;
    stores the contract address."""
    r = last(op="deploy", kind=kind)
    if not r:
        sys.exit("%s has no deploy logged" % kind)
    if r.get("address"):
        print("%s already has an address: %s" % (kind, r["address"]))
        return
    _, client, net = connect(dry=True)
    receipt = chain.wait_accepted(client, r["tx"])
    decoded = receipt.get("tx_data_decoded") or {}
    address = decoded.get("contract_address") or receipt.get("recipient")
    if not address:
        sys.exit("the receipt has no address; report it")
    append(dict({k: v for k, v in r.items() if k != "at"}, address=address))
    print("RECOVERED %s at %s; tx %s; L2 receipt cost %s (gas %s)" % (
        kind, address, r["tx"], gen(r.get("l2_cost_wei")), r.get("l2_gas_used")))


def cmd_confirm_deploy(kind):
    r = deployed(kind)
    _, client, net = connect(dry=True)
    state = wait_final(client, r["tx"])
    row = {"op": "deploy", "kind": kind, "contract": kind, "tx": r["tx"], "address": r["address"],
           "final_status": state["status"], "final_result": state["result"], "execution": state["execution"],
           "votes": votes(r["tx"]), **{k: r.get(k) for k in ("l2_hash", "l2_gas_used", "l2_cost_wei", "bytes")}}
    if state["status"] != "FINALIZED" or not txstate.executed(state):
        append(dict(row, state="not_executed"))
        sys.exit("the deploy did not end FINALIZED and executed (%s %s %s); report it" % (
            state["status"], state["result"], state["execution"]))
    # Outside Studio, genlayer-js reads the schema in two steps: gen_getContractCode({address}) returns
    # the code in base64 and gen_getContractSchema({code}) parses it (with [address] Bradbury answers
    # "invalid parameter: expected object").
    code = chain.rpc_read(net, "gen_getContractCode", [{"address": r["address"]}])
    same_code = not code.get("error") and base64.b64decode(code["result"]) == CONTRACT[kind].read_bytes()
    schema = chain.rpc_read(net, "gen_getContractSchema", [{"code": code["result"]}]) if not code.get("error") else code
    methods = sorted(m for m in (schema.get("result") or {}).get("methods", {}) if not m.startswith("_")) if not schema.get("error") else []
    ph = chain.read(net, client, r["address"], "prompt_hash", [], FINAL)
    # If the code, schema or prompt_hash are not the expected ones, stop before sending any case.
    ok = same_code and methods == EXPECTED_METHODS[kind] and ph == expected_prompt_hash(kind)
    append(dict(row, state="final" if ok else "stop", same_code=same_code, schema_methods=methods,
                schema_error=schema.get("error"), prompt_hash=ph, as_expected=ok))
    print("FINALIZED %s %s; code equal to local %s; methods %s; prompt_hash %s" % (
        state["result"], state["execution"], same_code, methods, ph))
    if not ok:
        STOP.write_text("deploy of %s: schema %s / prompt_hash %s differ from the expected ones (%s / %s)" % (
            kind, methods, ph, EXPECTED_METHODS[kind], expected_prompt_hash(kind)), encoding="utf-8")
        sys.exit("STOP: the deployed contract's schema or prompt_hash are not the expected ones")
    print("schema and prompt_hash as expected")


def terms_json():
    return json.dumps({"domain": CASES["domain"], "structure": CASES["structure"], "profile": CASES["profile"],
                       "terms_hash": CASES["terms_hash"]})


def cmd_terms(kind):
    stopped()
    d = deployed(kind)
    if last(op="deploy", kind=kind, state="final") is None:
        sys.exit("first confirm-deploy %s" % kind)
    if in_flight(kind):
        sys.exit("a transaction to %s is in flight; confirm it first" % kind)
    account, client, net = connect()
    encoded = chain.write_calldata(client, account, d["address"], "set_merchant", [CASES["merchant"], terms_json()])
    gas = chain.estimate(net, client, account, encoded, final=False)
    tx, cost = send_captured(net, client, account, encoded, gas)
    append({"op": "terms", "contract": kind, "state": "sent", "tx": tx, **cost})
    chain.wait_accepted(client, tx)
    print("TERMS sent to %s; tx %s; cost %s" % (kind, tx, gen(cost["l2_cost_wei"])))


def cmd_confirm_terms(kind):
    d = deployed(kind)
    r = last(op="terms", contract=kind, state="sent")
    if not r:
        sys.exit("no terms sent to %s" % kind)
    _, client, net = connect(dry=True)
    state = wait_final(client, r["tx"])
    got = chain.read(net, client, d["address"], "get_merchant", [CASES["merchant"]], FINAL)
    want = cj({"domain": CASES["domain"], "structure": CASES["structure"], "profile": CASES["profile"],
               "terms_hash": CASES["terms_hash"]})
    ok = txstate.executed(state) and got == want
    append({"op": "terms", "contract": kind, "state": "final" if ok else "not_executed", "tx": r["tx"],
            "final_status": state["status"], "final_result": state["result"], "execution": state["execution"],
            "votes": votes(r["tx"]), "as_expected": ok, **{k: r.get(k) for k in ("l2_hash", "l2_gas_used", "l2_cost_wei")}})
    print("TERMS %s: %s" % (kind, "loaded as expected" if ok else "DO NOT MATCH (report it)"))


# ---- cases -----------------------------------------------------------------------------------

def case_of(cid):
    for c in CASES["cases"]:
        if c["id"] == cid:
            return c
    sys.exit("no case %s" % cid)


def cmd_send(cid, step, dry):
    stopped()
    c = case_of(cid)
    kind = c["contract"]
    d = deployed(kind)
    if not dry and last(op="terms", contract=kind, state="final") is None:
        sys.exit("first terms and confirm-terms %s" % kind)
    if not 1 <= step <= len(c["steps"]):
        sys.exit("%s has %d steps" % (cid, len(c["steps"])))
    if step > 1 and (last(op="judge", case=cid, step=step - 1) or {}).get("state") != "as_expected":
        sys.exit("step %d of %s is not confirmed as expected" % (step - 1, cid))
    prev = last(op="judge", case=cid, step=step)
    if prev and prev.get("state") in ("sent", "as_expected", "stop"):
        sys.exit("step %d of %s is already %s" % (step, cid, prev["state"]))
    if in_flight(kind):
        sys.exit("a transaction to %s is in flight; confirm it first" % kind)
    chain_prev = c["chain0"] if step == 1 else c["chains"][step - 2]
    step_json = cj({"chain": chain_prev, "submissions": c["steps"][step - 1]})
    attempt = 1 + sum(1 for r in rows() if r.get("op") == "judge" and r.get("case") == cid and r.get("step") == step
                      and r.get("state") == "sent")
    account, client, net = connect(dry)
    encoded = chain.write_calldata(client, account, d["address"], "judge", [c["claim"], step_json])
    gas = chain.estimate(net, client, account, encoded, final=dry)
    if dry:
        print("--dry %s step %d (attempt %d): %d bytes of calldata; nothing sent" % (cid, step, attempt, len(encoded)))
        return
    tx, cost = send_captured(net, client, account, encoded, gas)
    append({"op": "judge", "contract": kind, "case": cid, "step": step, "attempt": attempt, "state": "sent", "tx": tx,
            "chain": c["chains"][step - 1], **cost})
    try:
        receipt = chain.wait_accepted(client, tx)
    except KeyError as error:
        # genlayer-py has no name for some Bradbury statuses (14) and fails while waiting; the send is
        # already logged and confirm reads the stored status with Lacre's txstate.
        print("SENT %s step %d (attempt %d); tx %s; the SDK wait failed on status %s; continue with "
              "confirm %s %d; cost %s" % (cid, step, attempt, tx, error, cid, step, gen(cost["l2_cost_wei"])))
        return
    print("SENT %s step %d (attempt %d); tx %s; %s %s; cost %s" % (
        cid, step, attempt, tx, receipt.get("status_name"), receipt.get("result_name"), gen(cost["l2_cost_wei"])))


def cmd_confirm(cid, step):
    c = case_of(cid)
    r = last(op="judge", case=cid, step=step, state="sent")
    if not r or [x for x in rows() if x.get("tx") == r["tx"] and x.get("state") != "sent"]:
        sys.exit("no unconfirmed send of %s step %d" % (cid, step))
    d = deployed(c["contract"])
    _, client, net = connect(dry=True)
    state = wait_final(client, r["tx"])
    row = {"op": "judge", "contract": c["contract"], "case": cid, "step": step, "attempt": r["attempt"], "tx": r["tx"],
           "final_status": state["status"], "final_result": state["result"], "execution": state["execution"],
           "rounds": state.get("rounds"), "votes": votes(r["tx"]),
           **{k: r.get(k) for k in ("l2_hash", "l2_gas_used", "l2_cost_wei")}}
    if state["status"] != "FINALIZED":
        print("not FINALIZED yet (%s); run confirm again later" % state["status"])
        return
    raw = chain.read(net, client, d["address"], "get_verdict", [c["chains"][step - 1]], FINAL) if txstate.executed(state) else ""
    v = json.loads(raw) if isinstance(raw, str) and raw else {}
    want = c["expected_steps"][step - 1]
    got = {k: v.get(k) for k in want}
    if not v or v.get("outcome") == "NO_CONSENSUS":
        append(dict(row, state="resend", verdict=v))
        print("NO CONSENSUS (%s %s, verdict %s): send again with send %s %d; counts as a resend" % (
            state["result"], state["execution"], v.get("outcome", "none"), cid, step))
        return
    if got != want or v.get("chain") != c["chains"][step - 1] or v.get("claim_hash") != c["claim_hash"]:
        append(dict(row, state="stop", verdict=v, expected=want))
        STOP.write_text("%s step %d: verdict %s, expected %s (tx %s)" % (cid, step, got, want, r["tx"]), encoding="utf-8")
        sys.exit("STOP: wrong verdict accepted by a majority in %s step %d: %s, expected %s" % (cid, step, got, want))
    append(dict(row, state="as_expected", verdict=v))
    print("CONFIRMED %s step %d: %s %s %s; votes %s; cost %s" % (
        cid, step, v["outcome"], v["refund_cents"], v["reason"], row["votes"].get("counts", "-"), gen(row["l2_cost_wei"])))


def cmd_status():
    for r in rows():
        print("%s %-7s %-10s %-4s %s %-12s %s %s %s" % (
            r["at"], r.get("op"), r.get("contract", ""), r.get("case", ""), r.get("step", ""), r.get("state"),
            (r.get("tx") or "")[:12], gen(r.get("l2_cost_wei")) if r.get("l2_cost_wei") else "",
            (r.get("votes") or {}).get("counts", "")))
    if STOP.exists():
        print("STOPPED:", STOP.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("deploy", "recover-deploy", "confirm-deploy", "terms", "confirm-terms", "send", "confirm", "status"))
    ap.add_argument("target", nargs="?")
    ap.add_argument("step", nargs="?", type=int)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.command == "status":
        return cmd_status()
    if a.command in ("deploy", "recover-deploy", "confirm-deploy", "terms", "confirm-terms") and a.target not in CONTRACT:
        sys.exit("contract: mail or subjective")
    {"deploy": lambda: cmd_deploy(a.target, a.dry), "recover-deploy": lambda: cmd_recover_deploy(a.target),
     "confirm-deploy": lambda: cmd_confirm_deploy(a.target),
     "terms": lambda: cmd_terms(a.target), "confirm-terms": lambda: cmd_confirm_terms(a.target),
     "send": lambda: cmd_send(a.target, a.step, a.dry), "confirm": lambda: cmd_confirm(a.target, a.step)}[a.command]()


if __name__ == "__main__":
    main()
