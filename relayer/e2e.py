"""End-to-end test with Demo Shop: escrow v3 on Arc testnet and the v2 judges already deployed on
GenLayer Bradbury. One command per step.

Roles: the signer wallet is the escrow owner and the relayer, and sends the Bradbury transactions;
the buyer and the store are separate wallets, each signs its own actions. Keys live outside the
repository and are never printed.

    <venv with genlayer-py and web3>/python tools/lacre_boot.py relayer/e2e.py <command> [args]

Setup: newkey buyer|merchant, fund-buyer [usdc], deploy, terms, gl-merchant <mail|subjective>,
gl-merchant-confirm <mail|subjective>.
Orders: pay <case>, mail <X01|X02> (signs with the store's DKIM key; then tools/attest_mail.py),
claim <case>, submit <case> <submission>, mark <case> no_response|closing_timeout.
Judgment (relayer): judge <case>, confirm <case>, act <case> (opens the closing round, requests
proof or proposes the verdict).
Settlement: execute <case>, unproven <case>, withdraw buyer|merchant.
Reads: status [case], checks <case> (calls that must revert, no transaction).

What is registered on Arc comes from this tool's receipts (ClaimOpened and Submitted events); each
judgment step is exactly what was registered since the last judged chain, and before sending it the
tool checks that folding it gives the chain the escrow holds.

The local rehearsal (tests/e2e_rehearsal.py) uses these same functions against anvil and the judges
in the simulated SDK; the E2E_* variables change the network, state, log and keys.
Local paths (LACRE_DIR, SIGNER_ENV, E2E_KEYS) come from local.env through tools/lacre_boot.py.
"""
import base64
import datetime
import email.utils
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.logs import DISCARD as _DISCARD

ROOT = Path(__file__).resolve().parents[1]
LACRE = Path(os.environ.get("LACRE_DIR", ""))
sys.path[:0] = [str(ROOT / "arbiter"), str(ROOT / "tools"), str(LACRE), str(LACRE / "tools")]
import mail_v1  # noqa: E402

ARC_RPC = os.environ.get("E2E_RPC", "https://rpc.testnet.arc.network")
CHAIN_ID = int(os.environ.get("E2E_CHAIN_ID", "5042002"))
KEYS = Path(os.environ.get("E2E_KEYS", ""))  # folder with guardian.env, buyer.env and merchant.env
SIGNER_ENV = Path(os.environ.get("SIGNER_ENV", ""))  # file with PRIVATE_KEY= of the signer wallet
STATE = Path(os.environ.get("E2E_STATE", ROOT / "relayer" / "e2e-state.json"))
LOG = Path(os.environ.get("E2E_LOG", ROOT / "results" / "e2e-log.jsonl"))
STOP = LOG.with_name(LOG.stem.replace("-log", "") + "-STOP")  # e2e-log.jsonl -> e2e-STOP; one per test
MAIL_DIR = Path(os.environ.get("E2E_MAIL_DIR", ROOT / "cases" / "e2e"))
ATTEST_LOG = ROOT / "results" / "attest-mail.jsonl"

USDC = Web3.to_checksum_address(os.environ.get("E2E_USDC", "0x3600000000000000000000000000000000000000"))
CAP = 5_000_000  # 5.00 USDC per order
VERDICT_DELAY = 600  # 10 minutes on testnet
HOLD = 30 * 86400  # store hold: the one in the terms hash the judges hold
BUYER_FUNDS = 11_000_000
MIN_FEE = 20 * 10**9  # Arc: maxFeePerGas >= 20 gwei
CENT = 10**4
DAY = 86400
BR = json.loads((ROOT / "cases" / "br-cases.json").read_text(encoding="ascii"))
TERMS_HASH = BR["terms_hash"]
TERMS = {"domain": BR["domain"], "structure": BR["structure"], "profile": BR["profile"], "terms_hash": TERMS_HASH}
JUDGES = {"mail": "0x7e3251e7A9479280a6b8c93FD2E852291abd105c", "subjective": "0x2a0126530321FF7886A568b9439d3535A27EfA91"}
OUTCOME = {"REFUND": 1, "DENY": 2, "INVALID_CLAIM": 3}

C3 = {c["id"]: c for c in json.loads((ROOT / "cases" / "subjective-c3.json").read_text(encoding="utf-8"))["cases"]}
K12 = C3["K12"]
# Case B: K17 with the store's answer reworded without a September date (cases/k17b.json). Measured
# with the local committee like K17 (results/local-k17b.jsonl): q1, q2 and q2r2 50 of 50 as expected.
K17 = json.loads((ROOT / "cases" / "k17b.json").read_text(encoding="utf-8"))["cases"][0]

# The cases of the live test. The expected verdict of every judgment step is fixed here, before running.
CASES = {
    "A": {"judge": "mail", "event": "late", "order": "DS-310001", "amount": 4_000_000,
          "steps": [{"outcome": "REFUND", "refund_cents": 200, "reason": "per policy", "action": "decide"}],
          "settle": {"buyer": 2_000_000, "merchant": 2_000_000}},
    "B": {"judge": "subjective", "event": "not_as_described", "order": "DS-310002", "amount": 3_000_000, "c3": K17,
          "steps": [{"outcome": "NOT_YET", "refund_cents": 0, "reason": "closing round", "action": "open_closing_round"},
                    {"outcome": "DENY", "refund_cents": 0, "reason": "claim not proven", "action": "decide"}],
          "settle": {"buyer": 0, "merchant": 3_000_000}},
    "C": {"judge": "subjective", "event": "not_delivered", "order": "DS-310003", "amount": 2_000_000,
          "steps": [{"outcome": "REFUND", "refund_cents": 200, "reason": "per policy", "action": "decide"}],
          "settle": {"buyer": 2_000_000, "merchant": 0}},
    "D": {"judge": "subjective", "event": "not_as_described", "order": "DS-310004", "amount": 1_000_000, "c3": K12,
          "steps": [{"outcome": "NOT_YET", "refund_cents": 0, "reason": "proof required", "action": "request_proof"}],
          "settle": {"buyer": 0, "merchant": 1_000_000}},
    # Added after day 0: the store admits (texts of C3 K07, case S1 of the Bradbury run); full
    # refund the same day.
    "E": {"judge": "subjective", "event": "not_as_described", "order": "DS-310005", "amount": 1_000_000, "c3": C3["K07"],
          "steps": [{"outcome": "REFUND", "refund_cents": 100, "reason": "per policy", "action": "decide"}],
          "settle": {"buyer": 1_000_000, "merchant": 0}},
}
# Each party's submissions as the judge reads them: {party, kind, content} in canonical JSON.
SUBMISSIONS = {
    ("A", "X01"): ("buyer", "evidence", None), ("A", "X02"): ("buyer", "evidence", None),
    ("B", "response"): ("merchant", "response", K17["response"]),
    ("B", "closing_proof"): ("buyer", "closing_proof", K17["round2"]["proof"]),
    ("B", "closing_response"): ("merchant", "closing_response", K17["round2"]["response"]),
    ("D", "response"): ("merchant", "response", K12["response"]),
    ("E", "response"): ("merchant", "response", C3["K07"]["response"]),
}
# Case A emails: confirmation on the payment day (estimated delivery the next day) and delivery from
# day 4 (3 days late, with 2 days of grace).
MAILS = {"X01": {"case": "A", "min_days": 0}, "X02": {"case": "A", "min_days": 4}}


# ---- utilities -----------------------------------------------------------------------------------

def cj(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha_hex(data):
    return "0x" + hashlib.sha256(data).hexdigest()


def chain0(claim_hash):
    return sha_hex(bytes.fromhex(claim_hash[2:]))


def fold(cur, raw):
    return sha_hex(bytes.fromhex(cur[2:]) + hashlib.sha256(raw.encode("utf-8")).digest())


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def day_of(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date()


def rows():
    return [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines()] if LOG.exists() else []


def append(row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(row, at=now_iso()), ensure_ascii=False) + "\n")


def state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1) + "\n", encoding="utf-8")


def stopped():
    if STOP.exists():
        sys.exit("STOPPED: %s. Nothing is sent until it is reviewed." % STOP.read_text(encoding="utf-8").strip())


def stop(msg):
    STOP.write_text(msg, encoding="utf-8")
    sys.exit("STOP: " + msg)


def case_of(cid):
    if cid not in CASES:
        sys.exit("case: A, B, C, D or E")
    return CASES[cid]


# ---- keys ---------------------------------------------------------------------------------------

KEY_FILES = {"signer": (SIGNER_ENV, "PRIVATE_KEY"), "guardian": (KEYS / "guardian.env", "GUARDIAN_KEY"),
             "buyer": (KEYS / "buyer.env", "BUYER_KEY"), "merchant": (KEYS / "merchant.env", "MERCHANT_KEY")}


def account(who):
    path, name = KEY_FILES[who]
    if not path.exists():
        sys.exit("%s does not exist (key of %s; set E2E_KEYS and SIGNER_ENV in local.env)" % (path, who))
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            v = line.split("=", 1)[1].strip().strip("\"'")
            return Account.from_key(v if v.startswith("0x") else "0x" + v)
    sys.exit("no %s in %s" % (name, path))


def address(who):
    return account(who).address


def cmd_newkey(who):
    if who not in ("buyer", "merchant"):
        sys.exit("newkey buyer|merchant")
    path, name = KEY_FILES[who]
    if path.exists():
        print("the %s key already exists: %s (not overwritten)" % (who, address(who)))
        return
    acct = Account.create()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as fh:
        fh.write("%s=%s\n" % (name, acct.key.hex() if acct.key.hex().startswith("0x") else "0x" + acct.key.hex()))
    print("%s key created in %s; address %s" % (who, path, acct.address))


# ---- Arc ------------------------------------------------------------------------------------------

_W3 = None


def w3():
    global _W3
    if _W3 is None:
        _W3 = Web3(Web3.HTTPProvider(ARC_RPC, request_kwargs={"timeout": 60}))
    return _W3


ART = json.loads((ROOT / "evm" / "out" / "RefundEscrow.sol" / "RefundEscrow.json").read_text(encoding="utf-8"))
ERC20_ABI = [
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "transfer", "stateMutability": "nonpayable",
     "inputs": [{"name": "t", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}], "outputs": [{"type": "uint256"}]}]
ERRORS = {Web3.keccak(text="%s(%s)" % (e["name"], ",".join(i["type"] for i in e["inputs"])))[:4].hex().removeprefix("0x"): e["name"]
          for e in ART["abi"] if e["type"] == "error"}


def escrow():
    st = state()
    if not st.get("escrow"):
        sys.exit("the escrow is not deployed (deploy)")
    return w3().eth.contract(address=Web3.to_checksum_address(st["escrow"]), abi=ART["abi"])


def usdc():
    return w3().eth.contract(address=USDC, abi=ERC20_ABI)


def revert_name(error):
    text = " ".join(str(x) for x in (getattr(error, "data", ""), getattr(error, "message", ""), error))
    for sel in re.findall(r"0x([0-9a-fA-F]{8})", text):
        if sel.lower() in ERRORS:
            return ERRORS[sel.lower()]
    return "%s: %s" % (type(error).__name__, str(error)[:200])


def fees():
    base = w3().eth.gas_price
    try:
        tip = w3().eth.max_priority_fee
    except Exception:
        tip = 10**9
    top = max(2 * base, MIN_FEE)
    return {"maxFeePerGas": top, "maxPriorityFeePerGas": min(tip, top)}


def send(who, fn, op, case=None, **extra):
    """Signs and sends an Arc transaction. It is simulated first (gas estimate): if it reverts,
    nothing is sent. Returns the receipt; logs who signed it, gas and gas cost in USDC."""
    stopped()
    acct = account(who)
    try:
        tx = fn.build_transaction({"from": acct.address, "chainId": CHAIN_ID, **fees(),
                                   "nonce": w3().eth.get_transaction_count(acct.address, "pending")})
    except Exception as error:
        sys.exit("NOT SENT %s: the simulation reverts (%s)" % (op, revert_name(error)))
    tx["gas"] = int(tx["gas"] * 13 // 10)
    signed = acct.sign_transaction(tx)
    h = w3().eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3().eth.wait_for_transaction_receipt(h, timeout=300)
    cost = receipt["gasUsed"] * receipt.get("effectiveGasPrice", tx["maxFeePerGas"])
    row = {"op": op, "case": case, "from": acct.address, "role": who, "tx": "0x" + bytes(h).hex().removeprefix("0x"),
           "block": receipt["blockNumber"], "status": receipt["status"], "gas_used": receipt["gasUsed"],
           "cost_wei": str(cost), **extra}
    if receipt["status"] != 1:
        append(dict(row, state="reverted"))
        stop("the %s transaction from %s reverted on Arc (%s)" % (op, who, row["tx"]))
    append(dict(row, state="ok", events=events_of(receipt)))
    print("OK %s%s: tx %s, gas %d, cost %.6f USDC" % (op, " " + case if case else "", row["tx"], receipt["gasUsed"],
                                                       cost / 1e18))
    return receipt


def events_of(receipt):
    """ClaimOpened and Submitted from the receipt, with the registered text as is."""
    out = []
    if not state().get("escrow"):
        return out
    c = escrow()
    for name in ("ClaimOpened", "Submitted", "OrderSettled", "VerdictProposed", "ProofRequested"):
        for ev in c.events[name]().process_receipt(receipt, errors=_DISCARD):
            a = dict(ev["args"])
            item = {"name": name, "orderRef": "0x" + a["orderRef"].hex().removeprefix("0x")}
            if name == "ClaimOpened":
                item.update(claim=a["claim"].decode("utf-8"), chain="0x" + a["chain"].hex().removeprefix("0x"),
                            claim_hash="0x" + a["claimHash"].hex().removeprefix("0x"))
            elif name == "Submitted":
                item.update(submission=a["submission"].decode("utf-8"), chain="0x" + a["chain"].hex().removeprefix("0x"),
                            by=a["by"])
            elif name == "OrderSettled":
                item.update(refund=a["refund"], released=a["released"])
            out.append(item)
    return out


def call_reverts(who_address, fn):
    """A read call (eth_call) from who_address: the error name if it reverts, or None."""
    try:
        fn.call({"from": who_address})
    except Exception as error:
        return revert_name(error)
    return None


def order_ref(cid):
    return mail_v1.order_ref(case_of(cid)["order"])


def get_order(cid):
    o = escrow().functions.getOrder(bytes.fromhex(order_ref(cid)[2:])).call()
    keys = ("buyer", "merchant", "token", "amount", "paidAt", "expiresAt", "claimedAt", "proofRequestedAt",
            "proofSubmittedAt", "closingOpenedAt", "flags", "state", "termsHash", "claimHash", "chain")
    d = dict(zip(keys, o))
    for k in ("termsHash", "claimHash", "chain"):
        d[k] = "0x" + bytes(d[k]).hex()
    return d


def block_time():
    return w3().eth.get_block("latest")["timestamp"]


# ---- setup ----------------------------------------------------------------------------------------

def cmd_fund_buyer(extra=None):
    """Without an amount: tops the buyer up to 11.00 (day 0). With an amount (in USDC): transfers exactly
    that (order E, added after day 0)."""
    buyer = address("buyer")
    if extra is not None:
        units = round(float(extra) * 10**6)
        if not 0 < units <= 2_000_000:
            sys.exit("amount between 0 and 2.00 USDC")
        send("signer", usdc().functions.transfer(buyer, units), "fund-buyer", amount=units)
        return
    have = usdc().functions.balanceOf(buyer).call()
    if have >= BUYER_FUNDS:
        print("the buyer already has %.6f USDC; nothing transferred" % (have / 1e6))
        return
    send("signer", usdc().functions.transfer(buyer, BUYER_FUNDS - have), "fund-buyer")


def cmd_deploy():
    st = state()
    if st.get("escrow"):
        sys.exit("there is already an escrow in the state: %s" % st["escrow"])
    signer, guardian = address("signer"), address("guardian")
    c = w3().eth.contract(abi=ART["abi"], bytecode=ART["bytecode"]["object"])
    fn = c.constructor(signer, signer, guardian, [USDC], [CAP], VERDICT_DELAY)
    receipt = send("signer", fn, "deploy")
    st.update(escrow=receipt["contractAddress"], deploy_block=receipt["blockNumber"], usdc=USDC)
    save_state(st)
    e = escrow()
    got = (e.functions.owner().call(), e.functions.relayer().call(), e.functions.guardian().call(),
           e.functions.capPerOrder(USDC).call(), e.functions.verdictDelay().call())
    want = (signer, signer, guardian, CAP, VERDICT_DELAY)
    print("ESCROW %s; owner, relayer, guardian, cap and delay %s" % (
        receipt["contractAddress"], "as expected" if got == want else "DIFFERENT: %s" % (got,)))
    if got != want:
        stop("escrow parameters differ from the expected ones")


def cmd_terms():
    merchant = address("merchant")
    send("signer", escrow().functions.setMerchantTerms(merchant, HOLD, bytes.fromhex(TERMS_HASH[2:])), "terms")
    e = escrow()
    ok = (e.functions.merchantHold(merchant).call() == HOLD
          and "0x" + e.functions.merchantTermsHash(merchant).call().hex().removeprefix("0x") == TERMS_HASH)
    print("TERMS of store %s: %s" % (merchant, "as expected" if ok else "DIFFERENT"))


# ---- orders ---------------------------------------------------------------------------------------

def cmd_pay(cid):
    c = case_of(cid)
    if get_order(cid)["state"] != 0:
        sys.exit("the order of %s already exists" % cid)
    send("buyer", usdc().functions.approve(escrow().address, c["amount"]), "approve", cid)
    send("buyer", escrow().functions.pay(bytes.fromhex(order_ref(cid)[2:]), address("merchant"), USDC, c["amount"], HOLD,
                                         bytes.fromhex(TERMS_HASH[2:])), "pay", cid)


def claim_text(cid, claimed_at):
    c, o = case_of(cid), get_order(cid)
    paid = day_of(o["paidAt"])
    cl = {"v": "claim-v1", "order_ref": order_ref(cid), "order_number": c["order"], "buyer": o["buyer"].lower(),
          "merchant": o["merchant"].lower(), "amount_cents": o["amount"] // CENT, "paid_at": o["paidAt"],
          "claimed_at": claimed_at, "terms_hash": o["termsHash"], "event": c["event"]}
    if c["event"] == "not_delivered":
        promised = (paid + datetime.timedelta(days=1)).isoformat()
        cl.update(account="My order never arrived. The promised date was %s and nothing came." % promised,
                  promised_date=promised)
    elif c["event"] == "not_as_described":
        k = c["c3"]
        cl.update(description=k["description"], account=k["claim"]["account"], promised=k["claim"]["promised"],
                  received=k["claim"]["received"], proof_kind=k["claim"]["proof_kind"], proof=k["claim"]["proof"],
                  delivered_date=paid.isoformat())
    return cj(cl)


def cmd_claim(cid):
    o = get_order(cid)
    if o["state"] != 1 or o["claimedAt"]:
        sys.exit("the order of %s is not open or already has a claim" % cid)
    t = block_time()
    if cid == "C" and (day_of(t) - (day_of(o["paidAt"]) + datetime.timedelta(days=1))).days < 10:
        sys.exit("C: the claim goes 10 days after the promised date (payment + 1): from %s" % (
            day_of(o["paidAt"]) + datetime.timedelta(days=11)))
    if cid == "A" and not all(record_id(m) for m in ("X01", "X02")):
        sys.exit("A: first the two attested emails (X01 and X02)")
    text = claim_text(cid, t)
    send("buyer", escrow().functions.openClaim(bytes.fromhex(order_ref(cid)[2:]), text.encode("utf-8")), "claim", cid,
         claim=text)


def record_id(mid):
    """Lacre record of the email, from tools/attest_mail.py (or from the simulated judge in the rehearsal)."""
    if JUDGE_BACKEND.records is not None:
        return JUDGE_BACKEND.records.get(mid)
    if not ATTEST_LOG.exists():
        return None
    rid = None
    for line in ATTEST_LOG.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("id") == mid and r.get("state") == "confirmed" and r.get("as_expected"):
            rid = r["record_id"]
    return rid


def submission(cid, name):
    if (cid, name) not in SUBMISSIONS:
        sys.exit("submissions of %s: %s" % (cid, ", ".join(n for c, n in SUBMISSIONS if c == cid)))
    party, kind, content = SUBMISSIONS[(cid, name)]
    if kind == "evidence":
        rid = record_id(name)
        if not rid:
            sys.exit("%s has no confirmed Lacre record" % name)
        _, body = mail_v1.split_message((MAIL_DIR / "mail" / ("%s.eml" % name)).read_bytes())
        content = {"record_id": str(rid), "body_b64": base64.b64encode(body).decode()}
    return party, cj({"party": party, "kind": kind, "content": content})


def cmd_submit(cid, name):
    party, text = submission(cid, name)
    send(party, escrow().functions.submit(bytes.fromhex(order_ref(cid)[2:]), text.encode("utf-8")), "submit", cid,
         name=name, submission=text)


def cmd_mark(cid, kind):
    fn = {"no_response": "markNoResponse", "closing_timeout": "markClosingTimeout"}.get(kind)
    if not fn:
        sys.exit("mark <case> no_response|closing_timeout")
    send("signer", getattr(escrow().functions, fn)(bytes.fromhex(order_ref(cid)[2:])), "mark", cid, name=kind)


# ---- case A emails ----------------------------------------------------------------------------------

def cmd_mail(mid):
    """Builds the email with today's date and signs the E2E set with the store's DKIM key
    (tools/sign_mail.mjs, key file in DKIM_KEY_FILE). Only sign_mail.mjs reads the private key."""
    if mid not in MAILS:
        sys.exit("mail X01|X02")
    o = get_order(MAILS[mid]["case"])
    if o["state"] == 0:
        sys.exit("first the payment of A")
    now = int(os.environ.get("E2E_NOW") or datetime.datetime.now(datetime.timezone.utc).timestamp())
    if now < o["paidAt"]:
        sys.exit("the email has to come after the payment")
    paid, today = day_of(o["paidAt"]), day_of(now)
    if (today - paid).days < MAILS[mid]["min_days"]:
        sys.exit("%s goes from %s" % (mid, paid + datetime.timedelta(days=MAILS[mid]["min_days"])))
    order = CASES["A"]["order"]
    set_file = MAIL_DIR / "mail-set.json"
    data = json.loads(set_file.read_text(encoding="utf-8")) if set_file.exists() else {"positives": []}
    if any(m["id"] == mid for m in data["positives"]):
        sys.exit("%s is already built; not changed" % mid)
    if mid == "X01":
        subject = "Order %s confirmed" % order
        body = ("Hi,\r\n\r\nThanks for your order %s.\r\nTotal: USD %.2f\r\nEstimated delivery: %s\r\n\r\nDemo Shop\r\n"
                % (order, CASES["A"]["amount"] / 1e6, (paid + datetime.timedelta(days=1)).isoformat()))
    else:
        if not any(m["id"] == "X01" for m in data["positives"]):
            sys.exit("first X01")
        subject = "Order %s delivered" % order
        body = "Your package for order %s was delivered on %s.\r\n" % (order, today.isoformat())
    data["positives"].append({
        "id": mid, "lang": "en", "claim_order": order, "order_date": paid.isoformat(),
        "headers": {"From": "Demo Shop Orders <orders@shop.rpmdev.app>", "To": "buyer@example.com", "Subject": subject,
                    "Date": email.utils.formatdate(now, usegmt=True).replace("GMT", "+0000"),
                    "Message-ID": "<%s.%d@shop.rpmdev.app>" % (mid.lower(), now)},
        "body": body, "sign": {"domain": "shop.rpmdev.app", "selector": "shop1", "tamper": None},
        "expected_type": "order_confirmed" if mid == "X01" else "delivered"})
    set_file.parent.mkdir(parents=True, exist_ok=True)
    set_file.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    env = dict(os.environ, MAIL_SET=str(set_file), MAIL_OUT=str(MAIL_DIR / "mail"))
    out = subprocess.run(["node", str(ROOT / "tools" / "sign_mail.mjs")], cwd=str(ROOT), env=env, capture_output=True,
                         text=True)
    if out.returncode != 0:
        sys.exit("sign_mail.mjs failed: %s" % out.stderr[-400:])
    raw = (MAIL_DIR / "mail" / ("%s.eml" % mid)).read_bytes()
    print("EMAIL %s signed (%s): %s" % (mid, subject, body.strip().splitlines()[-1] if mid == "X02" else
                                         body.strip().splitlines()[3]))
    append({"op": "mail", "case": "A", "name": mid, "state": "ok", "signed_at": now, "bytes": len(raw)})


# ---- judgment -------------------------------------------------------------------------------------

def registered(cid):
    """Claim and submissions registered on Arc for the case, in order, from the receipts."""
    ref = order_ref(cid)
    claim, subs = None, []
    for r in rows():
        for ev in r.get("events", []):
            if ev["orderRef"] != ref:
                continue
            if ev["name"] == "ClaimOpened":
                claim, subs = ev, []
            elif ev["name"] == "Submitted":
                subs.append(ev)
    return claim, subs


def judge_rows(cid):
    return [r for r in rows() if r.get("op") == "judge" and r.get("case") == cid]


def judged_chain(cid, claim):
    done = [r for r in judge_rows(cid) if r.get("state") == "as_expected"]
    return done[-1]["chain"] if done else claim["chain"]


def cmd_judge(cid):
    stopped()
    c = case_of(cid)
    claim, subs = registered(cid)
    if not claim:
        sys.exit("%s has no registered claim" % cid)
    js = judge_rows(cid)
    if js and js[-1].get("state") == "sent":
        sys.exit("a step of %s is in flight; confirm it first" % cid)
    if js and js[-1].get("state") == "as_expected" and not js[-1].get("acted"):
        sys.exit("the last verdict of %s has not been taken to Arc yet (act %s)" % (cid, cid))
    all_rows = rows()
    done = {r["tx"] for r in all_rows if r.get("op") == "judge" and r.get("state") != "sent"}
    busy = [r for r in all_rows if r.get("op") == "judge" and r.get("contract") == c["judge"] and r.get("state") == "sent"
            and r["tx"] not in done]
    if busy:
        sys.exit("a submission to the %s judge is in flight (%s); confirm it first" % (c["judge"], busy[-1]["case"]))
    judged = judged_chain(cid, claim)
    chains = [claim["chain"]] + [s["chain"] for s in subs]
    if judged not in chains:
        stop("%s: the judged chain is not among the registered ones" % cid)
    pending = [s["submission"] for s in subs[chains.index(judged):]]
    if not pending:
        sys.exit("%s: no new submissions since the last step" % cid)
    cur = judged
    for raw in pending:
        cur = fold(cur, raw)
    o = get_order(cid)
    claim_hash = sha_hex(claim["claim"].encode("utf-8"))
    if cur != o["chain"] or claim_hash != o["claimHash"]:
        stop("%s: what was registered does not fold to the escrow chain (%s / %s)" % (cid, cur, o["chain"]))
    step = cj({"chain": judged, "submissions": pending})
    n = len({r["step"] for r in js if r.get("state") == "as_expected"}) + 1
    attempt = 1 + len([r for r in js if r.get("step") == n and r.get("state") == "resend"])
    tx, extra = JUDGE_BACKEND.send(c["judge"], claim["claim"], step, block_time())
    append({"op": "judge", "contract": c["judge"], "case": cid, "step": n, "attempt": attempt, "state": "sent",
            "tx": tx, "chain": cur, "claim_hash": claim_hash, "submissions": len(pending), **extra})
    print("SENT %s step %d (attempt %d): %d submissions; tx %s" % (cid, n, attempt, len(pending), tx))


def cmd_confirm(cid):
    js = judge_rows(cid)
    if not js or js[-1].get("state") != "sent":
        sys.exit("no unconfirmed step of %s" % cid)
    r = js[-1]
    c = case_of(cid)
    got = JUDGE_BACKEND.confirm(c["judge"], r["tx"], r["chain"])
    if got is None:
        print("not FINALIZED yet; run confirm %s again" % cid)
        return
    v, info = got
    base = {k: r[k] for k in ("op", "contract", "case", "step", "attempt", "tx", "chain", "claim_hash")}
    if not v or v.get("outcome") == "NO_CONSENSUS":
        append(dict(base, state="resend", verdict=v, **info))
        print("NO CONSENSUS (%s): send again with judge %s; counts for E2E7" % (info.get("final_result", "-"), cid))
        return
    want = c["steps"][r["step"] - 1]
    seen = {k: v.get(k) for k in want}
    ok = seen == want and v.get("chain") == r["chain"] and v.get("claim_hash") == r["claim_hash"] \
        and (c["judge"] != "mail" or v.get("ignored", []) == [])
    if not ok:
        append(dict(base, state="stop", verdict=v, expected=want, **info))
        stop("%s step %d: verdict %s, expected %s (tx %s)" % (cid, r["step"], seen, want, r["tx"]))
    append(dict(base, state="as_expected", verdict=v, **info))
    print("CONFIRMED %s step %d: %s %s %s, action %s; votes %s" % (
        cid, r["step"], v["outcome"], v["refund_cents"], v["reason"], v["action"], info.get("votes", "-")))


def cmd_act(cid):
    js = judge_rows(cid)
    if not js or js[-1].get("state") != "as_expected":
        sys.exit("%s has no confirmed verdict" % cid)
    r = js[-1]
    if any(x.get("op") == "act" and x.get("case") == cid and x.get("tx_judge") == r["tx"] for x in rows()):
        sys.exit("that verdict was already taken to Arc")
    v, ref = r["verdict"], bytes.fromhex(order_ref(cid)[2:])
    o = get_order(cid)
    if o["chain"] != v["chain"] or o["claimHash"] != v["claim_hash"]:
        stop("%s: the escrow changed since the verdict (different chain or claim)" % cid)
    e = escrow().functions
    if v["action"] == "open_closing_round":
        send("signer", e.openClosingRound(ref), "act", cid, name="open_closing_round", tx_judge=r["tx"])
    elif v["action"] == "request_proof":
        send("signer", e.requestProof(ref), "act", cid, name="request_proof", tx_judge=r["tx"])
    elif v["action"] == "decide" and v["outcome"] in OUTCOME:
        verdict_ref = bytes.fromhex(r["tx"][2:].rjust(64, "0"))[-32:]
        send("signer", e.proposeVerdict(ref, OUTCOME[v["outcome"]], v["refund_cents"], bytes.fromhex(v["claim_hash"][2:]),
                                        bytes.fromhex(v["chain"][2:]), verdict_ref),
             "act", cid, name="propose", tx_judge=r["tx"])
    else:
        sys.exit("action %s: nothing to take to Arc" % v["action"])
    _mark_acted(r)


def _mark_acted(r):
    append(dict({k: r[k] for k in ("op", "contract", "case", "step", "attempt", "tx", "chain", "claim_hash", "verdict")},
                state="as_expected", acted=True))


# ---- settlement ------------------------------------------------------------------------------------

def cmd_execute(cid):
    send("signer", escrow().functions.executeVerdict(bytes.fromhex(order_ref(cid)[2:])), "execute", cid)


def cmd_unproven(cid):
    send("signer", escrow().functions.releaseUnproven(bytes.fromhex(order_ref(cid)[2:])), "unproven", cid)


def cmd_withdraw(who):
    if who not in ("buyer", "merchant"):
        sys.exit("withdraw buyer|merchant")
    send(who, escrow().functions.withdraw(USDC), "withdraw", None, name=who)


# ---- reads -----------------------------------------------------------------------------------------

def cmd_checks(cid):
    """E2E-R (c) and E2E6: read calls that must revert. No transaction is sent."""
    ref = bytes.fromhex(order_ref(cid)[2:])
    e = escrow().functions
    relayer = address("signer")
    o = get_order(cid)
    out = {"openClaim from the relayer": (call_reverts(relayer, e.openClaim(ref, claim_text(cid, block_time()).encode())),
                                          "NotBuyer")}
    if o["claimedAt"]:
        sub = cj({"party": "buyer", "kind": "closing_statement", "content": "relayer"})
        out["submit of a buyer submission from the relayer"] = (call_reverts(relayer, e.submit(ref, sub.encode())),
                                                                    "NotParty")
        bad = bytes.fromhex(("%064x" % (int(o["claimHash"], 16) ^ 1)))
        out["proposeVerdict with another claim hash"] = (call_reverts(relayer, e.proposeVerdict(
            ref, 2, 0, bad, bytes.fromhex(o["chain"][2:]), b"\x00" * 32)), "BadVerdict")
        out["proposeVerdict with another chain"] = (call_reverts(relayer, e.proposeVerdict(
            ref, 2, 0, bytes.fromhex(o["claimHash"][2:]), bytes.fromhex("%064x" % (int(o["chain"], 16) ^ 1)), b"\x00" * 32)),
            "BadVerdict")
    if o["proofRequestedAt"] and block_time() < o["proofRequestedAt"] + 7 * DAY:
        out["releaseUnproven before 7 days"] = (call_reverts(relayer, e.releaseUnproven(ref)), "TooEarly")
    ok = all(got == want for got, want in out.values())
    for what, (got, want) in out.items():
        print("%-55s %-12s %s" % (what, got, "ok" if got == want else "EXPECTED %s" % want))
    append({"op": "checks", "case": cid, "state": "ok" if ok else "fail",
            "results": {k: {"got": g, "want": w} for k, (g, w) in out.items()}})
    if not ok:
        stop("%s: a call that had to revert did not revert as expected" % cid)
    return out


def cmd_status(cid=None):
    st = state()
    print("escrow %s" % st.get("escrow", "sin desplegar"))
    for who in ("signer", "buyer", "merchant"):
        try:
            a = address(who)
        except SystemExit:
            continue
        line = "%-8s %s USDC %.6f" % (who, a, usdc().functions.balanceOf(a).call() / 1e6)
        if st.get("escrow"):
            line += " claimable %.6f" % (escrow().functions.claimable(a, USDC).call() / 1e6)
        print(line)
    if st.get("escrow"):
        print("escrow USDC %.6f" % (usdc().functions.balanceOf(escrow().address).call() / 1e6))
        for c in ([cid] if cid else CASES):
            o = get_order(c)
            print("%s %s state %d amount %.2f paid %s claimed %s proof_req %s closing %s chain %s" % (
                c, CASES[c]["order"], o["state"], o["amount"] / 1e6, o["paidAt"], o["claimedAt"], o["proofRequestedAt"],
                o["closingOpenedAt"], o["chain"][:12]))
    if STOP.exists():
        print("STOPPED:", STOP.read_text(encoding="utf-8"))


# ---- judges -----------------------------------------------------------------------------------------

class LiveJudge:
    """Bradbury through Lacre's tools (like tools/judge_send.py); the signer pays the GEN."""
    records = None

    def __init__(self):
        self._js = None

    def js(self):
        if self._js is None:
            import judge_send  # noqa: E402  (Lacre, LATEST_FINAL, votos crudos)
            self._js = judge_send
        return self._js

    def send(self, kind, claim, step, _when):
        js = self.js()
        account, client, net = js.connect()
        encoded = js.chain.write_calldata(client, account, JUDGES[kind], "judge", [claim, step])
        gas = js.chain.estimate(net, client, account, encoded, final=False)
        tx, cost = js.send_captured(net, client, account, encoded, gas)
        try:
            js.chain.wait_accepted(client, tx)
        except KeyError as error:
            print("the SDK wait failed on status %s; continue with confirm" % error)
        return tx, cost

    def confirm(self, kind, tx, chain_hex):
        js = self.js()
        _, client, net = js.connect(dry=True)
        st = js.wait_final(client, tx)
        if st["status"] != "FINALIZED":
            return None
        raw = js.chain.read(net, client, JUDGES[kind], "get_verdict", [chain_hex], js.FINAL) if js.txstate.executed(st) else ""
        votes = js.votes(tx)
        info = {"final_result": st["result"], "execution": st["execution"], "votes": votes.get("counts")}
        return (json.loads(raw) if isinstance(raw, str) and raw else {}), info

    def merchant(self, kind, merchant, terms):
        js = self.js()
        account, client, net = js.connect()
        encoded = js.chain.write_calldata(client, account, JUDGES[kind], "set_merchant", [merchant, terms])
        gas = js.chain.estimate(net, client, account, encoded, final=False)
        tx, cost = js.send_captured(net, client, account, encoded, gas)
        js.chain.wait_accepted(client, tx)
        return tx, cost

    def merchant_confirm(self, kind, tx, merchant):
        js = self.js()
        _, client, net = js.connect(dry=True)
        st = js.wait_final(client, tx)
        return st, js.chain.read(net, client, JUDGES[kind], "get_merchant", [merchant], js.FINAL)


JUDGE_BACKEND = LiveJudge()


def cmd_gl_merchant(kind):
    if kind not in JUDGES:
        sys.exit("gl-merchant mail|subjective")
    m = address("merchant").lower()
    tx, cost = JUDGE_BACKEND.merchant(kind, m, json.dumps(TERMS))
    append({"op": "gl-merchant", "contract": kind, "state": "sent", "tx": tx, "merchant": m, **cost})
    print("TERMS of store %s sent to the %s judge; tx %s" % (m, kind, tx))


def cmd_gl_merchant_confirm(kind):
    sent = [r for r in rows() if r.get("op") == "gl-merchant" and r.get("contract") == kind and r.get("state") == "sent"]
    if not sent:
        sys.exit("no terms sent to the %s judge" % kind)
    r = sent[-1]
    st, got = JUDGE_BACKEND.merchant_confirm(kind, r["tx"], r["merchant"])
    ok = st["status"] == "FINALIZED" and got == cj(TERMS)
    append({"op": "gl-merchant", "contract": kind, "state": "final" if ok else "not_as_expected", "tx": r["tx"],
            "merchant": r["merchant"], "final_status": st["status"]})
    print("TERMS %s: %s" % (kind, "loaded as expected" if ok else "DO NOT MATCH (report it)"))


# ---- main ---------------------------------------------------------------------------------------------

COMMANDS = {
    "newkey": (cmd_newkey, 1), "fund-buyer": (cmd_fund_buyer, None), "deploy": (cmd_deploy, 0), "terms": (cmd_terms, 0),
    "gl-merchant": (cmd_gl_merchant, 1), "gl-merchant-confirm": (cmd_gl_merchant_confirm, 1),
    "pay": (cmd_pay, 1), "mail": (cmd_mail, 1), "claim": (cmd_claim, 1), "submit": (cmd_submit, 2), "mark": (cmd_mark, 2),
    "judge": (cmd_judge, 1), "confirm": (cmd_confirm, 1), "act": (cmd_act, 1), "execute": (cmd_execute, 1),
    "unproven": (cmd_unproven, 1), "withdraw": (cmd_withdraw, 1), "checks": (cmd_checks, 1), "status": (cmd_status, None),
}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        sys.exit("commands: " + ", ".join(COMMANDS))
    fn, n = COMMANDS[argv[0]]
    args = argv[1:]
    if n is not None and len(args) != n:
        sys.exit("%s takes %d arguments" % (argv[0], n))
    return fn(*args)


if __name__ == "__main__":
    main(sys.argv[1:])
