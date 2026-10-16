"""Full local rehearsal of the end-to-end test, with no network and no real keys: escrow v3 on anvil
(a child process that lives only while this command runs), the two v2 judges in Lacre's simulated
SDK, and the same commands of relayer/e2e.py, in calendar order (days 0, 4, 7, 11 and 14, with
anvil's clock moved forward).

- USDC: the test token of the Foundry tests (Stable, 6 decimals) placed at 0x3600...0000, the USDC
  address on Arc. Anvil gas is ETH.
- Keys: signer and guardian are anvil accounts (public test keys); buyer and store are created by
  `newkey` in a temporary folder that is deleted at the end.
- Emails: signed by tools/sign_mail.mjs with a throwaway test DKIM key (not the store's real key),
  at anvil's clock time; the simulated Verifier and KeyCache use that key.
- Committee: fixed answers per step. The first attempt of A splits (no majority) to exercise the
  resend.

Usage: LACRE_DIR=<lacre clone> <venv>/python tools/lacre_boot.py tests/e2e_rehearsal.py
"""
import base64
import datetime
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Foundry's anvil: $ANVIL, else the one on PATH (as in CI), else the default foundryup location.
ANVIL = os.environ.get("ANVIL") or shutil.which("anvil") or str(Path.home() / ".foundry" / "bin" / ("anvil.exe" if os.name == "nt" else "anvil"))
SIGNER_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"  # anvil 0 (public test key)
GUARDIAN_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"  # anvil 1
SIGNER_USDC = 19_940_512  # what the signer held on Arc when the live test started
OUT = ROOT / "results" / "e2e-rehearsal.txt"
DAY = 86400

LINES = []


def say(text):
    print(text)
    LINES.append(text)


def check(cond, what):
    say("%s %s" % ("ok  " if cond else "BAD ", what))
    if not cond:
        raise AssertionError(what)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def rpc(url, method, params):
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                       "params": params}).encode(),
                                 headers={"content-type": "application/json"})
    out = json.load(urllib.request.urlopen(req, timeout=30))
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def expect_exit(fn, *args):
    try:
        fn(*args)
    except SystemExit as error:
        return str(error)
    raise AssertionError("expected %s to stop" % fn.__name__)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="e2e-rehearsal-"))
    port = free_port()
    url = "http://127.0.0.1:%d" % port
    keys = tmp / "keys"
    keys.mkdir()
    (keys / "signer.env").write_text("PRIVATE_KEY=%s\n" % SIGNER_PK)
    (keys / "guardian.env").write_text("GUARDIAN_KEY=%s\n" % GUARDIAN_PK)
    dkim = tmp / "dkim-test.pem"
    jwk = json.loads(subprocess.run(["node", "-e", (
        "const c=require('crypto');const k=c.generateKeyPairSync('rsa',{modulusLength:2048,publicExponent:65537});"
        "require('fs').writeFileSync(process.argv[1],k.privateKey.export({type:'pkcs8',format:'pem'}));"
        "console.log(JSON.stringify(k.publicKey.export({format:'jwk'})))"), str(dkim)],
        capture_output=True, text=True, check=True).stdout)
    b64 = lambda s: int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")  # noqa: E731
    n, e = b64(jwk["n"]), b64(jwk["e"])
    os.environ.update(E2E_RPC=url, E2E_CHAIN_ID="5042002", E2E_KEYS=str(keys), SIGNER_ENV=str(keys / "signer.env"),
                      E2E_STATE=str(tmp / "state.json"), E2E_LOG=str(tmp / "e2e-log.jsonl"),
                      E2E_MAIL_DIR=str(tmp / "e2e"), DKIM_KEY_FILE=str(dkim))
    anvil = subprocess.Popen([str(ANVIL), "--port", str(port), "--chain-id", "5042002", "--silent"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                rpc(url, "eth_chainId", [])
                break
            except Exception:
                time.sleep(0.2)
        run(url, tmp, n, e)
    finally:
        anvil.kill()
        anvil.wait()
        shutil.rmtree(tmp, ignore_errors=True)
        OUT.write_text("\n".join(LINES) + "\n", encoding="utf-8")


def run(url, tmp, n, e):
    sys.path[:0] = [str(ROOT / "relayer"), str(ROOT / "tests")]
    import e2e as E
    import judge_v2_stub_run as H
    from eth_account import Account
    from web3 import Web3

    H.SHOP_KEY = {"n": n, "e": e, "key_bits": n.bit_length(), "sha256": hashlib.sha256(b"%x" % n).hexdigest()}
    w3 = E.w3()
    signer = Account.from_key(SIGNER_PK)

    def block_time():
        return w3.eth.get_block("latest")["timestamp"]

    def warp(seconds):
        rpc(url, "evm_increaseTime", [int(seconds)])
        rpc(url, "evm_mine", [])

    def day():
        return (E.day_of(block_time()) - d0).days

    # test USDC at the Arc address
    stable = json.loads((ROOT / "evm" / "out" / "RefundEscrow.t.sol" / "Stable.json").read_text(encoding="utf-8"))
    c = w3.eth.contract(abi=stable["abi"], bytecode=stable["bytecode"]["object"])
    tx = c.constructor("USDC").build_transaction({"from": signer.address, "nonce": w3.eth.get_transaction_count(signer.address),
                                                  "chainId": 5042002, **E.fees()})
    rec = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signer.sign_transaction(tx).raw_transaction))
    rpc(url, "anvil_setCode", [E.USDC, "0x" + bytes(w3.eth.get_code(rec["contractAddress"])).hex()])
    token = w3.eth.contract(address=E.USDC, abi=stable["abi"])
    tx = token.functions.mint(signer.address, SIGNER_USDC).build_transaction(
        {"from": signer.address, "nonce": w3.eth.get_transaction_count(signer.address), "chainId": 5042002, **E.fees()})
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signer.sign_transaction(tx).raw_transaction))

    class StubJudge:
        """The two v2 judges exactly as built, in the simulated SDK; the transaction is immediate."""

        def __init__(self):
            self.records, self.answers, self.results = {}, None, {}
            self.worlds = {k: H.World(k) for k in ("mail", "subjective")}

        def iso(self, ts):
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        def tx(self, kind, result):
            t = "0x%064x" % (len(self.results) + 1)
            self.results[t] = (kind, result)
            return t

        def merchant(self, kind, merchant, terms):
            return self.tx(kind, self.worlds[kind].write(H.OWNER, self.iso(block_time()), "set_merchant", merchant, terms)), {}

        def merchant_confirm(self, kind, tx, merchant):
            assert self.results[tx][1][0] == "ok", self.results[tx]
            return {"status": "FINALIZED"}, self.worlds[kind].c.get_merchant(merchant)

        def attest(self, mid):
            raw = (tmp / "e2e" / "mail" / ("%s.eml" % mid)).read_bytes()
            rid = str(100 + len(self.records))
            rec = H.record_for(raw, requester=signer.address)
            check(rec["valid"] and rec["aligned"], "E2E0 %s: valid and aligned signature (test key)" % mid)
            self.worlds["mail"].node.verifier.final[rid] = rec
            self.records[mid] = rid

        def send(self, kind, claim, step, when):
            w = self.worlds[kind]
            w.committee.lookup = self.answers
            r = w.write(H.RELAYER, self.iso(when), "judge", claim, step)
            assert r[0] in ("ok", "split"), r
            return self.tx(kind, r), {"l2_cost_wei": "0"}

        def confirm(self, kind, tx, chain_hex):
            r = self.results[tx][1]
            if r[0] == "split":
                return {}, {"final_result": "NO_MAJORITY"}
            raw = self.worlds[kind].c.get_verdict(chain_hex)
            return (json.loads(raw) if raw else {}), {"final_result": "AGREE", "votes": {"1:FINISHED_WITH_RETURN": 5}}

    J = StubJudge()
    E.JUDGE_BACKEND = J
    ans = lambda **a: H.scripted(a)  # noqa: E731
    mail_types = lambda p: (("type", [{"verdict": "delivered" if "was delivered on" in p else "order_confirmed"}] * 5)  # noqa: E731
                            if "Question: what event of the order" in p else None)
    split = lambda p: (("type", [{"verdict": v} for v in ("delivered", "order_confirmed", "shipped", "other", "delivered")])  # noqa: E731
                       if "Question: what event of the order" in p else None)

    def judge_step(cid, answers):
        J.answers = answers
        E.cmd_judge(cid)
        E.cmd_confirm(cid)

    def claimable(who):
        return E.escrow().functions.claimable(E.address(who), E.USDC).call()

    def settled(cid, before):
        want = E.CASES[cid]["settle"]
        o = E.get_order(cid)
        got = {w: claimable(w) - before[w] for w in ("buyer", "merchant")}
        check(o["state"] == 2 and got == want and sum(got.values()) == E.CASES[cid]["amount"],
              "E2E5 %s: settled; credited %s = expected %s" % (cid, got, want))

    def snap():
        return {w: claimable(w) for w in ("buyer", "merchant")}

    # ---- day 0 --------------------------------------------------------------------------------------
    say("== day 0")
    E.cmd_newkey("buyer")
    E.cmd_newkey("merchant")
    for who in ("buyer", "merchant"):  # anvil gas (on Arc: the buyer's 11 USDC and the store's faucet funds)
        rpc(url, "anvil_setBalance", [E.address(who), hex(10**18)])
    E.cmd_fund_buyer()
    check(token.functions.balanceOf(E.address("buyer")).call() == E.BUYER_FUNDS, "buyer holds 11.00 USDC from the signer")
    E.cmd_deploy()
    E.cmd_terms()
    for kind in ("mail", "subjective"):
        E.cmd_gl_merchant(kind)
        E.cmd_gl_merchant_confirm(kind)
    rows = E.rows()
    check(all(r["state"] == "final" for r in rows if r["op"] == "gl-merchant" and r["state"] != "sent"),
          "E2E1 the new store's terms in both judges")
    for cid in "ABCD":
        E.cmd_pay(cid)
    E.cmd_fund_buyer("1")  # case E, added after day 0
    E.cmd_pay("E")
    d0 = E.day_of(E.get_order("A")["paidAt"])
    os.environ["E2E_NOW"] = str(block_time())
    E.cmd_mail("X01")
    J.attest("X01")
    say(expect_exit(E.cmd_mail, "X02"))  # delivery goes from day 4

    say("-- B: not_as_described with a closing round")
    E.cmd_claim("B")
    E.cmd_submit("B", "response")
    E.cmd_checks("B")
    judge_step("B", ans(q1="differs", q2="disputes_with_fact"))
    say(expect_exit(E.cmd_judge, "B"))  # no new step until the verdict is taken to Arc
    E.cmd_act("B")
    check(E.get_order("B")["closingOpenedAt"] > 0, "E2E4 B: closing round open on Arc")
    E.cmd_submit("B", "closing_proof")
    E.cmd_submit("B", "closing_response")
    judge_step("B", ans(q1="differs", q2="disputes_with_fact"))
    E.cmd_act("B")
    say(expect_exit(E.cmd_execute, "B"))  # before the verdict delay: TooEarly
    before = snap()
    warp(E.VERDICT_DELAY + 1)
    E.cmd_execute("B")
    settled("B", before)

    say("-- E: not_as_described, the store admits")
    E.cmd_claim("E")
    E.cmd_submit("E", "response")
    judge_step("E", ans(q1="differs", q2="admits"))
    E.cmd_act("E")
    before = snap()
    warp(E.VERDICT_DELAY + 1)
    E.cmd_execute("E")
    settled("E", before)

    say("-- D: proof expired")
    E.cmd_claim("D")
    E.cmd_submit("D", "response")
    judge_step("D", ans(q1="differs", q2="general_denial"))
    E.cmd_act("D")
    check(E.get_order("D")["proofRequestedAt"] > 0, "E2E4 D: proof requested on Arc")
    E.cmd_checks("D")
    say(expect_exit(E.cmd_claim, "C"))  # C goes from day 11

    # ---- day 4 ---------------------------------------------------------------------------------------
    warp(4 * DAY)
    say("== day %d" % day())
    os.environ["E2E_NOW"] = str(block_time())
    E.cmd_mail("X02")
    J.attest("X02")
    say("-- A: late with a refund")
    E.cmd_claim("A")
    E.cmd_submit("A", "X01")
    E.cmd_submit("A", "X02")
    judge_step("A", split)  # first attempt without a majority: sent again (E2E7)
    judge_step("A", mail_types)
    E.cmd_act("A")
    before = snap()
    warp(E.VERDICT_DELAY + 1)
    E.cmd_execute("A")
    settled("A", before)

    # ---- day 7 ---------------------------------------------------------------------------------------
    warp(E.get_order("D")["proofRequestedAt"] + 7 * DAY - block_time() + 1)
    say("== day %d" % day())
    before = snap()
    E.cmd_unproven("D")
    settled("D", before)

    # ---- days 11 and 14 --------------------------------------------------------------------------------
    warp((d0 + datetime.timedelta(days=11) - E.day_of(block_time())).days * DAY)
    say("== day %d" % day())
    say("-- C: not_delivered with no_response")
    E.cmd_claim("C")
    say(expect_exit(E.cmd_mark, "C", "no_response"))  # before 72 h: TooEarly
    warp(72 * 3600 + 1)
    say("== day %d" % day())
    E.cmd_mark("C", "no_response")
    judge_step("C", None)
    E.cmd_act("C")
    before = snap()
    warp(E.VERDICT_DELAY + 1)
    E.cmd_execute("C")
    settled("C", before)

    # ---- withdrawals and wrap-up --------------------------------------------------------------------------
    E.cmd_withdraw("buyer")
    E.cmd_withdraw("merchant")
    bal = {w: token.functions.balanceOf(E.address(w)).call() for w in ("signer", "buyer", "merchant")}
    check(bal == {"signer": SIGNER_USDC - E.BUYER_FUNDS - 1_000_000, "buyer": 6_000_000, "merchant": 6_000_000}
          and token.functions.balanceOf(E.escrow().address).call() == 0,
          "E2E5 final balances (signer, buyer, store) %s and escrow at 0" % bal)
    rows = E.rows()
    buyer = E.address("buyer")
    mine = [r for r in rows if r.get("op") in ("pay", "approve", "claim") or (r.get("op") == "submit" and r.get("name") in
                                                                              ("X01", "X02", "closing_proof"))]
    check(mine and all(r["from"] == buyer and r["role"] == "buyer" for r in mine),
          "E2E-R (a) the buyer's payments, claims and submissions signed by the buyer's wallet (%d tx)" % len(mine))
    judged = [r for r in rows if r.get("op") == "judge" and r.get("state") == "as_expected" and not r.get("acted")]
    check(len(judged) == 6, "E2E2 6 of 6 steps with the expected verdict")
    check(all(r["verdict"]["chain"] == r["chain"] and r["verdict"]["claim_hash"] == r["claim_hash"] for r in judged),
          "E2E3 and E2E-R (b) chain and claim hash of every verdict = the escrow's")
    resends = [r for r in rows if r.get("op") == "judge" and r.get("state") == "resend"]
    check(len(resends) == 1 and resends[0]["case"] == "A", "E2E7 one resend (A, no majority) and it reached the verdict")
    checks = [r for r in rows if r.get("op") == "checks"]
    check(len(checks) == 2 and all(r["state"] == "ok" for r in checks),
          "E2E-R (c) and E2E6: calls revert as expected (%s)" % sorted(
              {k for r in checks for k in r["results"]}))
    gas = sum(r.get("gas_used", 0) for r in rows if r.get("state") == "ok" and "gas_used" in r)
    say("total gas on anvil: %d (on Arc at 25 gwei: %.3f USDC)" % (gas, gas * 25e9 / 1e18))
    say("REHEARSAL PASS")


if __name__ == "__main__":
    main()
