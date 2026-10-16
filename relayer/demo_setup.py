"""One-time setup of the demo mode (README.md, "The Demo Shop runs on minutes"): the demo escrow on Arc testnet and the two demo
judges on GenLayer Bradbury, with the demo store's terms. Every write is signed by the signer wallet
(owner); one command at a time. Nothing here touches the contracts of the live test.

It reuses relayer/e2e.py (Arc) and tools/judge_send.py (Bradbury) with the demo log, state and
terms, so the deploy, wait and check code is the one already used for the live test.

    python tools/lacre_boot.py relayer/demo_setup.py <command>

  terms-preview                 demo terms: structure, rendered text and hash (read only)
  escrow-deploy                 demo escrow (evm/out-demo): owner signer, relayer = demo relayer,
                                guardian, USDC cap 1.00, verdict delay 2 minutes
  escrow-terms                  setMerchantTerms(demo store, 30 days, demo terms hash), signed by
                                the demo relayer (the escrow's relayer)
  judge-deploy <mail|subjective>          deploy, waits for ACCEPTED
  judge-recover-deploy <mail|subjective>  resumes waiting for a deploy already sent (read only)
  judge-confirm-deploy <mail|subjective>  waits for FINALIZED; same code, schema and prompt_hash
  judge-terms <mail|subjective>           set_merchant(demo store, demo terms)
  judge-confirm-terms <mail|subjective>   waits for FINALIZED; get_merchant in final state
  status                                  what is deployed (read only)

Logs: results/demo-log.jsonl (Arc), results/demo-judges-log.jsonl (Bradbury); state:
relayer/demo-state.json. A STOP file (results/demo-STOP, results/demo-judges-STOP) halts every write.
"""
import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["E2E_STATE"] = str(ROOT / "relayer" / "demo-state.json")
os.environ["E2E_LOG"] = str(ROOT / "results" / "demo-log.jsonl")
sys.path[:0] = [str(ROOT / "relayer"), str(ROOT / "tools"), str(ROOT / "arbiter")]
import e2e as E  # noqa: E402  (Arc helpers; module globals point to the demo log and state)
import judge_send as J  # noqa: E402  (Bradbury helpers)
import terms  # noqa: E402

DEMO_ART = ROOT / "evm" / "out-demo" / "RefundEscrow.sol" / "RefundEscrow.json"
DEMO_SRC = ROOT / "evm" / "demo" / "RefundEscrow.sol"
CAP = 1_000_000  # 1.00 USDC per order (DM-P2)
VERDICT_DELAY = 120  # 2 minutes (DM-P1)
HOLD_DAYS = 30
DOMAIN, SELECTOR = "demo.rpmdev.app", "demo1"
WINDOWS = {"response": "5 minutes", "proof": "5 minutes"}  # the demo escrow's constants (DM-P1)

E.KEY_FILES.update({"demo_relayer": (E.KEYS / "demo-relayer.env", "DEMO_RELAYER_KEY"),
                    "demo_store": (E.KEYS / "demo-store.env", "DEMO_STORE_KEY")})


def demo_structure():
    """Demo Shop's structure with the two changes of DM-P4: late grace 0, not_delivered without wait."""
    s = copy.deepcopy(E.BR["structure"])
    for r in s["rules"]:
        if r["event"] == "late":
            r["late_grace_days"] = 0
        if r["event"] == "not_delivered":
            r["wait_from"], r["wait_days"] = "none", 0
    return s


def demo_profile():
    """Demo Shop's profile (order and date patterns) under the demo domain and selector."""
    return dict(E.BR["profile"], domain=DOMAIN, selector=SELECTOR)


STRUCTURE = demo_structure()
TERMS_HASH = terms.terms_hash(STRUCTURE, HOLD_DAYS, WINDOWS)


def demo_cases():
    """What judge_send reads as CASES: router, demo domain, terms and the demo store."""
    return {"router": E.BR["router"], "domain": DOMAIN, "structure": STRUCTURE, "profile": demo_profile(),
            "terms_hash": TERMS_HASH, "merchant": E.address("demo_store").lower(), "cases": []}


def use_demo_judges():
    J.LOG = ROOT / "results" / "demo-judges-log.jsonl"
    J.STOP = ROOT / "results" / "demo-judges-STOP"
    J.CASES = demo_cases()


def demo_art():
    if not DEMO_ART.exists():
        sys.exit("build the demo escrow first: py -3.12 tools/make_demo_escrow.py, then in evm/: "
                 "FOUNDRY_PROFILE=demo forge build")
    art = json.loads(DEMO_ART.read_text(encoding="utf-8"))
    if art["metadata"]["sources"].get("demo/RefundEscrow.sol") is None:
        sys.exit("%s was not built from evm/demo/RefundEscrow.sol" % DEMO_ART)
    return art


def cmd_terms_preview():
    print(terms.render(STRUCTURE, HOLD_DAYS, WINDOWS))
    print("rules:", json.dumps(STRUCTURE["rules"]))
    print("terms hash:", TERMS_HASH)
    print("live Demo Shop terms hash (unchanged):", E.TERMS_HASH)


def cmd_escrow_deploy():
    E.ART = demo_art()
    st = E.state()
    if st.get("escrow"):
        sys.exit("there is already a demo escrow in the state: %s" % st["escrow"])
    signer, relayer, guardian = E.address("signer"), E.address("demo_relayer"), E.address("guardian")
    c = E.w3().eth.contract(abi=E.ART["abi"], bytecode=E.ART["bytecode"]["object"])
    receipt = E.send("signer", c.constructor(signer, relayer, guardian, [E.USDC], [CAP], VERDICT_DELAY), "deploy")
    st.update(escrow=receipt["contractAddress"], deploy_block=receipt["blockNumber"], usdc=E.USDC)
    E.save_state(st)
    e = E.escrow()
    got = (e.functions.owner().call(), e.functions.relayer().call(), e.functions.guardian().call(),
           e.functions.capPerOrder(E.USDC).call(), e.functions.verdictDelay().call(),
           e.functions.RESPONSE_WINDOW().call(), e.functions.CLOSING_WINDOW().call(),
           e.functions.PROOF_WINDOW().call(), e.functions.MIN_VERDICT_DELAY().call())
    want = (signer, relayer, guardian, CAP, VERDICT_DELAY, 300, 300, 300, 60)
    print("DEMO ESCROW %s; owner, relayer, guardian, cap, delay and windows %s" % (
        receipt["contractAddress"], "as expected" if got == want else "DIFFERENT: %s" % (got,)))
    if got != want:
        E.stop("demo escrow parameters differ from the expected ones")


def cmd_escrow_terms():
    E.ART = demo_art()
    store = E.address("demo_store")
    hold = HOLD_DAYS * 86400
    # setMerchantTerms is the escrow's relayer call: the demo relayer key signs it (it needs USDC for gas).
    E.send("demo_relayer", E.escrow().functions.setMerchantTerms(store, hold, bytes.fromhex(TERMS_HASH[2:])), "terms")
    e = E.escrow()
    ok = (e.functions.merchantHold(store).call() == hold
          and "0x" + e.functions.merchantTermsHash(store).call().hex().removeprefix("0x") == TERMS_HASH)
    print("TERMS of the demo store %s: %s" % (store, "as expected" if ok else "DIFFERENT"))


def cmd_status():
    st = E.state()
    print("demo escrow:", st.get("escrow") or "not deployed")
    print("demo relayer %s, demo store %s" % (E.address("demo_relayer"), E.address("demo_store")))
    use_demo_judges()
    for kind in ("mail", "subjective"):
        d = J.last(op="deploy", kind=kind)
        t = J.last(op="terms", contract=kind)
        print("judge %-10s %s %s; terms %s" % (kind, (d or {}).get("address") or "not deployed",
                                             (d or {}).get("state", ""), (t or {}).get("state", "not sent")))
    print("demo terms hash:", TERMS_HASH)


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    judge_cmds = {"judge-deploy": lambda k: J.cmd_deploy(k, False), "judge-recover-deploy": J.cmd_recover_deploy,
                  "judge-confirm-deploy": J.cmd_confirm_deploy, "judge-terms": J.cmd_terms,
                  "judge-confirm-terms": J.cmd_confirm_terms}
    if cmd == "terms-preview":
        cmd_terms_preview()
    elif cmd == "escrow-deploy":
        cmd_escrow_deploy()
    elif cmd == "escrow-terms":
        cmd_escrow_terms()
    elif cmd in judge_cmds and len(a) == 2 and a[1] in ("mail", "subjective"):
        use_demo_judges()
        judge_cmds[cmd](a[1])
    elif cmd == "status":
        cmd_status()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
