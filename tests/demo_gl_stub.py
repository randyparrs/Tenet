"""Simulated Bradbury and Lacre for the rehearsal of the demo Worker (worker/test/rehearsal.mjs): the
two judge contracts exactly as built (contracts/judge_*.py) in Lacre's simulated SDK, a committee that
answers as it did in the local measurements (K08, K12, K17B and G1D unanimous), and a Lacre Verifier
that records emails signed with the rehearsal's throwaway DKIM key. Local HTTP on 127.0.0.1 only;
it lives while the rehearsal runs (worker/test/rehearsal.mjs starts and stops it).

A transaction reads ACCEPTED on its first status read and FINALIZED from the second, so the Worker
sees "decided, finalizing" before the final verdict. Like Bradbury (measured on 2026-10-16), a read in
final state answers with the accepted state: a verdict or a Lacre record comes back before its
transaction is FINALIZED. Each such early answer is counted ("early_final_reads"); the Worker must
never need one. Controls: split the next judge step (no majority, to exercise the resend) and hold
every judge step (never final, to exercise the stall).

    python tools/lacre_boot.py tests/demo_gl_stub.py <port> <dkim n hex> <e>
"""
import datetime
import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "relayer"), str(ROOT / "tools")]
import demo_setup as S  # noqa: E402  (demo terms; puts Lacre's tools on the path)
import headers_blob  # noqa: E402  (Lacre)
import judge_v2_stub_run as H  # noqa: E402
import mail_v1  # noqa: E402

# The rehearsal passes its own copy (store and relayer are anvil test accounts there).
DATA = json.loads(Path(os.environ.get("DEMO_DATA") or ROOT / "worker" / "src" / "demo-data.json").read_text(encoding="utf-8"))
SC = {s["id"]: s for s in DATA["scenarios"]}
LIVE_MERCHANT = "0x13e2ddb489ee77d87846e7ba36bf5f89e8abff32"  # Demo Shop of the live test (isolation check)


def answers(split):
    """The committee as measured: a question and five equal answers (or five different ones)."""
    r2 = SC["N2"]["closing"]["store"]

    def lookup(prompt):
        if "Question: does what the buyer's account" in prompt:
            return "q1", [H.verdict_raw("differs")] * 5
        if "Question: what kind of answer is the RESPONSE" in prompt or "the buyer says the order never arrived" in prompt:
            if split:
                return "q2", [H.verdict_raw(v) for v in ("admits", "general_denial", "disputes_with_fact", "admits", "general_denial")]
            for text, v in ((r2, "disputes_with_fact"), (SC["N2"]["response"], "disputes_with_fact"),
                            (SC["N1"]["response"], "admits"), (SC["N3"]["response"], "general_denial"),
                            (SC["D1"]["response"], "general_denial")):
                if text in prompt:
                    return "q2", [H.verdict_raw(v)] * 5
            return None
        if "Question: what event of the order" in prompt:
            v = "order_confirmed" if "Thanks for your order" in prompt else "delivered" if "was delivered on" in prompt else "other"
            return "type", [H.verdict_raw(v)] * 5
        return None
    return lookup


class Chain:
    def __init__(self, n, e):
        H.DOMAIN, H.SELECTOR = DATA["terms"]["domain"], DATA["terms"]["selector"]
        H.SHOP_KEY = {"n": n, "e": e, "key_bits": n.bit_length(), "sha256": hashlib.sha256(b"%x" % n).hexdigest()}
        self.w = {k: H.World(k) for k in ("mail", "subjective")}
        terms = json.dumps({"domain": DATA["terms"]["domain"], "structure": DATA["terms"]["structure"],
                            "profile": DATA["terms"]["profile"], "terms_hash": DATA["terms"]["terms_hash"]})
        live = json.dumps({"domain": "shop.rpmdev.app", "structure": S.E.BR["structure"], "profile": S.E.BR["profile"],
                           "terms_hash": S.E.BR["terms_hash"]})
        for w in self.w.values():
            assert w.write(H.OWNER, "2026-10-14T00:00:00Z", "set_merchant", DATA["addresses"]["store"].lower(), terms)[0] == "ok"
            assert w.write(H.OWNER, "2026-10-14T00:00:00Z", "set_merchant", LIVE_MERCHANT, live)[0] == "ok"
        self.tx, self.records, self.rec_tx, self.split_next, self.hold = {}, {}, {}, False, False
        self.judge_sends, self.early = 0, 0

    def new_tx(self, item):
        t = "0x%064x" % (len(self.tx) + 1)
        self.tx[t] = dict(item, reads=0)
        return t

    def judge(self, kind, claim, step, when, sender):
        w = self.w[kind]
        w.committee.lookup = answers(self.split_next)
        split, self.split_next = self.split_next, False
        r = w.write(sender, when, "judge", claim, step)
        self.judge_sends += 1
        st = json.loads(step)
        to = st["chain"]
        for raw in st["submissions"]:
            to = H.fold(to, raw)
        return self.new_tx({"kind": "judge", "result": r[0], "to": to, "hold": self.hold})

    def status(self, t):
        x = self.tx[t]
        x["reads"] += 1
        if x.get("hold"):
            x["last"] = "ACCEPTED"
            return {"status": "ACCEPTED", "result": "AGREE", "done": False}
        final = x["reads"] >= 2
        x["last"] = "FINALIZED" if final else "ACCEPTED"
        result = "NO_MAJORITY" if x.get("result") == "split" else "AGREE"
        if final and x["kind"] == "attest":
            self.w["mail"].node.verifier.final.update(x["record"])
        return {"status": "FINALIZED" if final else "ACCEPTED", "result": result, "done": final}

    def verdict(self, kind, chain, final):
        raw = self.w[kind].c.get_verdict(chain)
        if not raw:
            return None
        if final and not any(x["kind"] == "judge" and x["to"] == chain and x["result"] == "ok" and x.get("last") == "FINALIZED"
                             for x in self.tx.values()):
            self.early += 1  # decided but not FINALIZED yet: Bradbury answers anyway
        return json.loads(raw)

    def attest(self, blob, domain, selector, raw, requester):
        raw_b = raw.encode("latin-1")
        want = headers_blob.build(raw_b, domain, selector)
        if blob != want:
            raise ValueError("the blob is not the one Lacre's headers_blob cuts")
        rec = H.record_for(raw_b, requester=requester)
        if not (rec["valid"] and rec["aligned"]):
            raise ValueError("signature not valid or not aligned")
        rid = str(200 + len(self.records))
        self.records[rid] = rec
        t = self.new_tx({"kind": "attest", "record": {rid: rec}})
        self.rec_tx[rid] = t
        return t

    def find(self, bh, final):
        for rid, rec in self.records.items():
            if rec["bh"] == bh:
                if final and self.tx[self.rec_tx[rid]].get("last") != "FINALIZED":
                    self.early += 1  # the attestation is not FINALIZED yet: Bradbury answers anyway
                return rid
        return None

    def isolation(self, evidence):
        """DEMO8: an email signed with the demo key, as evidence for the live test's store (shop.rpmdev.app)."""
        w = self.w["mail"]
        w.committee.lookup = answers(False)
        order = "DS-100999"
        claim = H.cj({"v": "claim-v1", "order_ref": mail_v1.order_ref(order), "order_number": order,
                      "buyer": H.RELAYER, "merchant": LIVE_MERCHANT, "amount_cents": 100, "paid_at": 1791900000,
                      "claimed_at": 1791990000, "terms_hash": S.E.BR["terms_hash"], "event": "late"})
        step = H.cj({"chain": H.chain0(H.sha(claim)), "submissions": [evidence]})
        r = w.write(H.RELAYER, "2026-10-14T12:00:00Z", "judge", claim, step)
        v = w.c.get_verdict(H.fold(H.chain0(H.sha(claim)), evidence))
        return {"write": r[0], "verdict": json.loads(v) if v else None}


def serve(port, chain):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])) or b"{}")
            try:
                out = route(self.path, body)
                code = 200
            except Exception as error:  # reported to the rehearsal, which fails on it
                out, code = {"error": "%s: %s" % (type(error).__name__, error)}, 500
            data = json.dumps(out).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def route(path, b):
        if path == "/judge":
            when = datetime.datetime.fromtimestamp(b["when"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {"tx": chain.judge(b["kind"], b["claim"], b["step"], when, b["sender"])}
        if path == "/status":
            return chain.status(b["tx"])
        if path == "/verdict":
            return {"verdict": chain.verdict(b["kind"], b["chain"], b["final"])}
        if path == "/attest":
            return {"tx": chain.attest(b["blob"], b["domain"], b["selector"], b["raw"], b["requester"])}
        if path == "/record":
            return {"record": chain.find(b["bh"], b["final"])}
        if path == "/control":
            chain.split_next = b.get("split_next", chain.split_next)
            chain.hold = b.get("hold", chain.hold)
            return {"ok": True}
        if path == "/count":
            return {"judge_sends": chain.judge_sends, "attests": len(chain.records), "early_final_reads": chain.early}
        if path == "/isolation":
            return chain.isolation(b["evidence"])
        raise ValueError("no route " + path)

    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    port, n_hex, e = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    chain = Chain(int(n_hex, 16), e)
    print("READY", flush=True)
    serve(port, chain)


if __name__ == "__main__":
    main()
