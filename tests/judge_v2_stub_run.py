"""Local run of the two v2 judge contracts against Lacre's simulated GenVM SDK.

contracts/judge_mail.py (late) and contracts/judge_subjective.py (not_as_described and
not_delivered) run exactly as built. For the email judge, Router, Verifier and KeyCache are stubs
(the Verifier reads only final records when asked for LATEST_FINAL); the records come from the .eml
files in cases/mail verified with shop1's public key. The committee is 5 validators: exec_prompt
returns each model's recorded raw answer (C3, B3, ND) or a fixed answer, and strict_eq accepts a
value when 3 or more of 5 agree; otherwise the transaction is not accepted (everything is undone).
No network, no GEN, no OpenRouter.

Usage: LACRE_DIR=<lacre clone> py -3.12 tests/judge_v2_stub_run.py [--out results/judge-v2-local.txt]
"""
import base64
import collections
import copy
import datetime
import hashlib
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arbiter"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "cases"))
sys.path.insert(0, str(Path(os.environ["LACRE_DIR"]) / "tests"))
import verifier_stub_run as stub  # noqa: E402

import mail_llm_v3  # noqa: E402
import mail_v1  # noqa: E402
import subjective_v3 as s3  # noqa: E402
import terms  # noqa: E402
import test_resolve_date  # noqa: E402
from lacre_vendor import dkimcore  # noqa: E402
from make_subjective_cases import facts as flow_facts  # noqa: E402
from run_local import MODELS  # noqa: E402

CONTRACTS = {"mail": ROOT / "contracts" / "judge_mail.py", "subjective": ROOT / "contracts" / "judge_subjective.py"}
B3_FILE = ROOT / "results" / "local-b3.jsonl"
OWNER, ROUTER, KEYCACHE = stub.OWNER, stub.ROUTER, stub.KEYCACHE
VERIFIER = "0x5555555555555555555555555555555555555555"
RELAYER = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MERCHANT = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
OTHER_MERCHANT = "0xdddddddddddddddddddddddddddddddddddddddd"
BUYER = "0xcccccccccccccccccccccccccccccccccccccccc"
DOMAIN, SELECTOR = "shop.rpmdev.app", "shop1"
MAIL = json.load(open(ROOT / "cases" / "mail-set.json", encoding="utf-8"))
C3 = json.load(open(ROOT / "cases" / "subjective-c3.json", encoding="utf-8"))
ORDER_AMOUNT = {"DS-100231": 4990, "DS-100232": 12000, "DS-100233": 3550, "DS-100234": 8000,
                "DS-100235": 6000, "DS-100236": 5000}
ORDER_DATE = {m["claim_order"]: m["order_date"] for m in MAIL["positives"]}
# Demo Shop test structure: the C3 one for not_as_described, plus late and not_delivered. No
# preconditions or exclusions (the only kind v2 accepts).
STRUCTURE = copy.deepcopy(C3["policy"])
STRUCTURE["rules"] += [
    {"event": "late", "wait_from": "none", "wait_days": 0, "deadline_from": "delivery", "deadline_days": 30,
     "late_grace_days": 2, "refund_percent": 50},
    {"event": "not_delivered", "wait_from": "promised", "wait_days": 10, "deadline_from": "none",
     "deadline_days": 0, "late_grace_days": 0, "refund_percent": 100}]
HOLD_DAYS = 30
TERMS_HASH = terms.terms_hash(STRUCTURE, HOLD_DAYS)
MAIL_DAY = "2026-10-02T00:00:00Z"


def load_codes():
    """contracts/ERRORS.md: code -> meaning. The harness translates every rejection with this table."""
    codes = {}
    for line in (ROOT / "contracts" / "ERRORS.md").read_text(encoding="utf-8").splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0][:1] in "CSMFL" and cells[0][1:].isdigit():
            codes[cells[0]] = cells[1]
    return codes


CODES = load_codes()
USED_CODES = set()


def explain(text):
    code, *params = text.split(":")
    if code not in CODES:
        raise AssertionError("code not documented in contracts/ERRORS.md: %r" % text)
    USED_CODES.add(code)
    return CODES[code].format(*params)


class Split(Exception):
    """Not 3 of 5 equal: the transaction gets no majority and changes nothing."""


# --- committee ------------------------------------------------------------------------------------

def verdict_raw(v):
    return {"verdict": v}


class Committee:
    def __init__(self):
        self.lookup = None  # prompt -> (question, [5 answers: dict or Exception]) or None
        self.k = 0
        self.log = []  # (question, agreed value or None, the 5 values)
        self.det_fail = 0
        self.formats = collections.Counter()
        self.unknown_prompts = []
        self.question = None

    def exec_prompt(self, prompt, response_format=None):
        self.formats[response_format] += 1
        found = self.lookup(prompt) if self.lookup else None
        if found is None:
            self.unknown_prompts.append(prompt[:120])
            raise RuntimeError("prompt without an answer")
        self.question, answers = found
        a = answers[self.k]
        if isinstance(a, Exception):
            raise a
        return copy.deepcopy(a)

    def strict_eq(self, fn):
        values = []
        for k in range(5):
            self.k = k
            leader, validator = fn(), fn()  # J8: same answer, same result
            if leader != validator:
                self.det_fail += 1
            values.append(leader)
        top, n = collections.Counter(values).most_common(1)[0]
        agreed = top if n >= 3 else None
        self.log.append((self.question, agreed, values))
        if agreed is None:
            raise Split()
        return agreed


def scripted(answers):
    """answers: question -> value (5 equal) or a list of 5 raw answers/Exceptions."""
    def kind(prompt):
        for marker, q in (("Question: does what the buyer's account", "q1"),
                          ("Question: what kind of answer is the RESPONSE", "q2"),
                          ("Question: what event of the order", "type"),
                          ("Question: the email may give a delivery date", "date")):
            if marker in prompt:
                return q
        return None

    def lookup(prompt):
        q = kind(prompt)
        if q is None or q not in answers:
            return None
        a = answers[q]
        if isinstance(a, list):
            return q, a
        if q == "date":
            m, d, y = (a.split("|") + ["", "", ""])[:3]
            raw = {"month": int(m) if m else None, "day": int(d) if d else None, "year": int(y) if y else None}
        else:
            raw = verdict_raw(a)
        return q, [raw] * 5
    return lookup


def recorded_answer(row):
    if row is None or not row.get("ok"):
        return RuntimeError("the model did not answer")
    try:
        return json.loads(row["raw"])
    except Exception:
        return ValueError("answer that is not JSON")


# --- simulated Lacre ------------------------------------------------------------------------------

class Verifier:
    def __init__(self):
        self.final, self.pending, self.states = {}, {}, []
        self.mode = None

    def view(self, *, state=stub.StorageType.LATEST_NON_FINAL):
        self.states.append(state)
        self.mode = state
        return self

    def _records(self):
        if self.mode == stub.StorageType.LATEST_FINAL:
            return self.final
        return {**self.final, **self.pending}

    def get(self, rid):
        return dict(self._records().get(str(rid), {}))

    def check_for(self, rid, domain, min_key_bits, requester):
        held = self._records().get(str(rid))
        try:
            who = stub.Address(requester)
        except ValueError:
            return False
        return (held is not None and held["valid"] is True and held["aligned"] is True
                and held["domain"] == str(domain).strip().lower().strip(".")
                and int(held["key_bits"]) >= int(min_key_bits) and stub.Address(held["requester"]) == who)


class Node(stub.Node):
    def __init__(self, committee):
        self.router = stub.Router({"verifier": VERIFIER, "keycache": KEYCACHE})
        self.keycache = stub.KeyCache()
        self.verifier = Verifier()
        super().__init__(self.router, {KEYCACHE: self.keycache})
        self.committee = committee

    def strict_eq(self, fn):
        return self.committee.strict_eq(fn)

    def contract_at(self, address):
        if address == stub.Address(VERIFIER):
            return self.verifier
        return super().contract_at(address)


def load_key():
    txt = (ROOT / "results" / "dkim-public-shop1.txt").read_text(encoding="utf-8").splitlines()[-1].strip()
    n, e = dkimcore.key_from_txt(txt)
    return {"n": n, "e": e, "key_bits": n.bit_length(), "sha256": hashlib.sha256(b"%x" % n).hexdigest()}


SHOP_KEY = load_key()
_RECORDS = {}


def record_for(raw, requester=RELAYER):
    if (raw, requester) not in _RECORDS:
        v = mail_v1.verify(raw, {(DOMAIN, SELECTOR): (SHOP_KEY["n"], SHOP_KEY["e"])})
        head, _ = mail_v1.split_message(raw)
        _, tags = dkimcore.find_signature(dkimcore.parse_headers(head))
        _RECORDS[(raw, requester)] = {
            "domain": v["domain"], "selector": v["selector"], "bh": "".join(dkimcore.unfold(tags.get("bh", "")).split()),
            "body_canon": tags.get("c", "simple/simple").partition("/")[2].strip().lower() or "simple",
            "valid": v["valid"], "aligned": v["aligned"], "signed_at": str(v["signed_at"]),
            "requester": requester, "key_bits": str(SHOP_KEY["key_bits"]), "source": "inline"}
    return dict(_RECORDS[(raw, requester)])


def cj(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(text):
    return "0x" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def chain0(claim_hash):
    """What the escrow stores when the claim opens: sha256(claimHash)."""
    return "0x" + hashlib.sha256(bytes.fromhex(claim_hash[2:])).hexdigest()


def fold(cur, raw):
    """The escrow on every submission: sha256(chain || sha256(submission))."""
    return "0x" + hashlib.sha256(bytes.fromhex(cur[2:]) + bytes.fromhex(sha(raw)[2:])).hexdigest()


def marker(kind):
    return {"content": None, "kind": kind, "party": "escrow"}


class World:
    """A freshly deployed contract ("mail" or "subjective") with the simulated SDK and, on the escrow
    side, the chain of each claim: the registered submissions and how far the contract judged them."""

    def __init__(self, kind):
        self.kind = kind
        self.committee = Committee()
        self.node = Node(self.committee)
        self.node.keycache.add(DOMAIN, SELECTOR, SHOP_KEY)
        self.sdk = stub.build_sdk(self.node)
        self.sdk.gl.nondet.exec_prompt = self.committee.exec_prompt
        self.sdk.gl.message_raw = {"datetime": "2026-09-01T00:00:00Z"}
        sys.modules["genlayer"] = self.sdk
        sys.modules["genlayer.py"] = types.ModuleType("genlayer.py")
        public_abi = types.ModuleType("genlayer.py.public_abi")
        public_abi.StorageType = stub.StorageType
        sys.modules["genlayer.py.public_abi"] = public_abi
        self.module = types.ModuleType("judge_" + kind)
        path = CONTRACTS[kind]
        exec(compile(path.read_text(encoding="ascii"), str(path), "exec"), self.module.__dict__)
        self.c = self.module.Contract.__new__(self.module.Contract)
        for name, ann in self.module.Contract.__annotations__.items():
            if getattr(ann, "__origin__", ann) is stub.TreeMap:
                setattr(self.c, name, stub.TreeMap())
        self.node.sender = stub.Address(OWNER)
        if kind == "mail":
            self.c.__init__(ROUTER)
        else:
            self.c.__init__()
        self.mails, self.ids, self.chains = {}, {}, {}
        if kind == "mail":
            for m in MAIL["positives"] + MAIL["negatives"]:
                raw = (ROOT / "cases" / "mail" / ("%s.eml" % m["id"])).read_bytes()
                self.add_mail(m["id"], raw, registered=m["id"] != "N3")
        self.write(OWNER, "2026-08-01T00:00:00Z", "set_merchant", MERCHANT, json.dumps(
            {"domain": DOMAIN, "structure": STRUCTURE, "profile": MAIL["profile"], "terms_hash": TERMS_HASH}))

    def add_mail(self, mid, raw, registered=True, final=True):
        self.mails[mid] = raw
        if not registered:  # Lacre writes no record: key not registered
            return
        rid = str(len(self.node.verifier.final) + len(self.node.verifier.pending))
        (self.node.verifier.final if final else self.node.verifier.pending)[rid] = record_for(raw)
        self.ids[mid] = rid

    def ev(self, mid, party="buyer", record_id=None):
        """An email as one party's submission: {party, kind, content}."""
        _, body = mail_v1.split_message(self.mails[mid])
        return {"party": party, "kind": "evidence",
                "content": {"record_id": record_id or self.ids.get(mid, "999"),
                            "body_b64": base64.b64encode(body).decode()}}

    def snapshot(self):
        return {k: dict(v) for k, v in vars(self.c).items() if isinstance(v, stub.TreeMap)}

    def write(self, sender, when, method, *args):
        """("ok", value) | ("error", reason) | ("split", None). An error or a split changes nothing."""
        self.node.sender = stub.Address(sender)
        self.sdk.gl.message_raw["datetime"] = when
        snap = self.snapshot()
        try:
            return "ok", getattr(self.c, method)(*args)
        except (stub.UserError, Split) as error:
            for k, v in snap.items():
                setattr(self.c, k, stub.TreeMap(v))
            if isinstance(error, Split):
                return "split", None
            return "error", explain(error.args[0].replace("[EXPECTED] ", ""))

    def entry(self, claim):
        text = claim if isinstance(claim, str) else cj(claim)
        h = sha(text)
        return text, self.chains.setdefault(h, {"judged": chain0(h), "pending": []})

    def judge(self, claim, items, when, answers=None, sender=RELAYER):
        """Registers items on the escrow chain (objects or raw text) and passes the contract the
        submissions not judged yet. If the contract stores the step, the judged chain moves on."""
        if answers is not None:
            self.committee.lookup = answers
        text, e = self.entry(claim)
        e["pending"] += [x if isinstance(x, str) else cj(x) for x in items]
        r = self.write(sender, when, "judge", text, cj({"chain": e["judged"], "submissions": e["pending"]}))
        if r[0] == "ok" and r[1] != "NO_CONSENSUS":
            for raw in e["pending"]:
                e["judged"] = fold(e["judged"], raw)
            e["pending"] = []
        return r

    def chain(self, claim):
        _, e = self.entry(claim)
        cur = e["judged"]
        for raw in e["pending"]:
            cur = fold(cur, raw)
        return cur

    def verdict(self, claim):
        text = self.c.get_verdict(self.chain(claim))
        return json.loads(text) if text else None

    def state(self, claim):
        _, e = self.entry(claim)
        text = self.c.get_claim(e["judged"])
        return json.loads(text) if text else None


def subs(*items):
    return [x for x in items if x is not None]


def response(text):
    return {"party": "merchant", "kind": "response", "content": text}


def closing(text, proof, statement=None):
    """The full closing round as the escrow registers it: opening, what each side sends and, if one
    of them is missing, the timeout."""
    buyer = ({"party": "buyer", "kind": "closing_proof", "content": proof} if proof else
             {"party": "buyer", "kind": "closing_statement", "content": statement} if statement else None)
    merchant = {"party": "merchant", "kind": "closing_response", "content": text} if text else None
    return subs(marker("closing_open"), buyer, merchant,
                marker("closing_timeout") if buyer is None or merchant is None else None)


def proof_sub(p):
    return {"party": "buyer", "kind": "proof", "content": p}


def unix(day, hour=0):
    return int(datetime.datetime.fromisoformat("%sT%02d:00:00+00:00" % (day, hour)).timestamp())


def claim_mail(order, event="late", amount=None):
    paid = ORDER_DATE.get(order, "2026-09-05")
    return {"v": "claim-v1", "order_ref": mail_v1.order_ref(order), "order_number": order, "buyer": BUYER,
            "merchant": MERCHANT, "amount_cents": amount or ORDER_AMOUNT.get(order, 5000),
            "paid_at": unix(paid), "claimed_at": unix("2026-10-01"), "terms_hash": TERMS_HASH, "event": event}


def claim_subjective(order, description, claim, f):
    return {"v": "claim-v1", "order_ref": mail_v1.order_ref(order), "order_number": order, "buyer": BUYER,
            "merchant": MERCHANT, "amount_cents": f["amount_cents"], "paid_at": unix(f["purchase_date"], 12),
            "claimed_at": unix(f["claim_date"], 12), "terms_hash": TERMS_HASH, "event": "not_as_described",
            "description": description, "account": claim.get("account", ""), "promised": claim["promised"],
            "received": claim["received"], "proof_kind": claim["proof_kind"], "proof": claim["proof"],
            "delivered_date": f["delivered_date"]}


def at(claim, hours):
    t = datetime.datetime.fromtimestamp(claim["claimed_at"], datetime.timezone.utc) + datetime.timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def majority(values):
    c = collections.Counter(v for v in values if v is not None)
    top, n = c.most_common(1)[0] if c else (None, 0)
    return top if n >= 3 else None


def unchanged(w, before):
    return w.snapshot() == before


class Report:
    def __init__(self, out):
        self.rows, self.out = [], out
        self.metrics = collections.OrderedDict()

    def line(self, text=""):
        self.rows.append(text)
        print(text)

    def metric(self, mid, text, ok, total, detail="", pending=False, need=None):
        if need is None:
            need = total if total > 0 else 1
        status = "PENDING" if pending else ("PASS" if ok >= need else "FAIL")
        self.metrics[mid] = status
        self.line("%-5s %-72s %s  %s%s" % (mid, text, "-" if pending else "%d / %d" % (ok, total), status,
                                            ("  " + detail) if detail else ""))

    def rows_metric(self, mid, text, rows):
        self.metric(mid, text, sum(ok for _, ok, _ in rows), len(rows),
                    "; ".join("%s %s" % (n, d) for n, ok, d in rows if not ok)[:700])

    def save(self):
        if self.out:
            Path(self.out).write_text("\n".join(self.rows) + "\n", encoding="utf-8")


def outcome(w, c):
    v = w.verdict(c)
    return (v["action"], v["outcome"], v["refund_cents"], v["reason"]) if v else None


def as_tuple(w, c, got):
    if got[0] == "split":
        return ("NO_CONSENSUS", 0, "")
    if got[0] == "error":
        return ("ERROR", 0, got[1])
    v = w.verdict(c)
    return ("NO_CONSENSUS", 0, "") if v["outcome"] == "NO_CONSENSUS" else (v["outcome"], v["refund_cents"], v["reason"])


# --- J1: C3 replayed (subjective judge) -------------------------------------------------------------

LABEL_BY_REASON = {"item as described": "matches", "claim not proven": "not_proven", "proof required": "insufficient",
                   "per policy": "differs_material"}


def run_c3(rep, stats):
    rows = [json.loads(l) for l in (ROOT / "results" / "local-c3.jsonl").read_text(encoding="utf-8").splitlines()]
    by = {(r["pass"], r["case"], r["question"], r["model"]): r for r in rows}
    votes = collections.defaultdict(dict)
    for r in rows:
        votes[(r["pass"], r["case"], r["question"])][r["model"]] = r["verdict"]
    ok = total = 0
    diffs = []
    for n in sorted({r["pass"] for r in rows}):
        w = World("subjective")
        for it in C3["cases"]:
            r2 = it.get("round2") or {}
            # Per round: in K23 the closing round answer is the same as the first one and both prompts
            # are equal; the recorded answer depends on the round.
            rounds = {"first": {s3.build_prompt("q1", it["description"], it["claim"], ""): "q1",
                                s3.build_prompt("q2", it["description"], it["claim"], it["response"]): "q2"},
                      "closing": {}}
            if r2.get("response"):
                rounds["closing"][s3.build_prompt("q2", it["description"], it["claim"], r2["response"],
                                                  r2.get("proof"))] = "q2r2"
            stage = ["first"]

            def lookup(prompt, n=n, it=it, rounds=rounds, stage=stage):
                q = rounds[stage[0]].get(prompt)
                if q is None:
                    return None
                stats["prompts_c"] += 1
                return q, [recorded_answer(by.get((n, it["id"], q, m))) for m in MODELS]
            claim = claim_subjective("C3-%s" % it["id"], it["description"], it["claim"], it["facts"])
            got = w.judge(claim, [response(it["response"])], at(claim, 1), lookup)
            if got[0] == "ok" and w.verdict(claim)["action"] == "open_closing_round":
                stage[0] = "closing"
                got = w.judge(claim, closing(r2.get("response", ""), r2.get("proof")), at(claim, 30))
            mine = as_tuple(w, claim, got)
            if got[0] == "ok":
                stats["verdicts"].append((w.verdict(claim), w.state(claim)))
            got_label = None if mine[0] == "NO_CONSENSUS" else LABEL_BY_REASON.get(mine[2], "?")
            maj = {q: majority([votes.get((n, it["id"], q), {}).get(m) for m in MODELS])
                   if (n, it["id"], q) in votes else None for q in ("q1", "q2", "q2r2")}
            label = s3.label(maj["q1"], maj["q2"], it["claim"], it["description"], r2.get("response", ""), maj["q2r2"],
                             r2.get("proof"))
            expected = tuple(s3.decide(label, C3["policy"], it["facts"]))
            if expected[0] == "NO_CONSENSUS":
                expected = ("NO_CONSENSUS", 0, "")
            total += 1
            if mine == expected and got_label == label:
                ok += 1
            else:
                diffs.append("%s pass %d: contract %s %s, C3 report %s %s" % (it["id"], n, mine, got_label, expected, label))
        stats["det_fail"] += w.committee.det_fail
        stats["formats"].update(w.committee.formats)
        stats["unknown_c"] += w.committee.unknown_prompts
    rep.metric("J1", "C3 replayed: label, decision, amount and reason", ok, total, "; ".join(diffs[:5]))


# --- J2: B3 replayed (email judge) -------------------------------------------------------------------

def run_b3(rep, stats):
    rows = [json.loads(l) for l in B3_FILE.read_text(encoding="utf-8").splitlines()]
    by = {(r["pass"], r["mail"], r["question"], r["model"]): r for r in rows}
    votes = collections.defaultdict(dict)
    for r in rows:
        votes[(r["pass"], r["mail"], r["question"])][r["model"]] = r["answer"]
    t_ok = t_n = d_ok = d_n = 0
    diffs = []
    for n in sorted({r["pass"] for r in rows}):
        for m in MAIL["positives"]:
            w = World("mail")
            body_text = m["body"].encode("latin-1").decode("utf-8")
            prompts = {mail_llm_v3.build_prompt("type", body_text): "type",
                       mail_llm_v3.build_prompt("date", body_text): "date"}

            def lookup(prompt, n=n, m=m, prompts=prompts):
                q = prompts.get(prompt)
                if q is None:
                    return None
                stats["prompts_m"] += 1
                return q, [recorded_answer(by.get((n, m["id"], q, x))) for x in MODELS]
            claim = claim_mail(m["claim_order"])
            got = w.judge(claim, [w.ev(m["id"])], MAIL_DAY, lookup)
            mine = {q: v for q, v, _ in w.committee.log}
            if got[0] == "ok":
                stats["verdicts"].append((w.verdict(claim), w.state(claim)))
            exp_t = majority([votes.get((n, m["id"], "type"), {}).get(x) for x in MODELS])
            t_n += 1
            if mine.get("type") == exp_t:
                t_ok += 1
            else:
                diffs.append("%s pass %d type %s / %s" % (m["id"], n, mine.get("type"), exp_t))
            if (n, m["id"], "date") in votes:
                exp_d = majority([votes[(n, m["id"], "date")].get(x) for x in MODELS])
                d_n += 1
                if mine.get("date") == exp_d:
                    d_ok += 1
                else:
                    diffs.append("%s pass %d date %s / %s" % (m["id"], n, mine.get("date"), exp_d))
            elif "date" in mine:
                diffs.append("%s pass %d: the contract asked the date and B3 did not" % (m["id"], n))
                d_n += 1
            stats["det_fail"] += w.committee.det_fail
            stats["formats"].update(w.committee.formats)
            stats["unknown_m"] += w.committee.unknown_prompts
    rep.metric("J2", "B3 replayed (no subject): type (of 180) and date (of 60)", t_ok + d_ok, t_n + d_n,
               "type %d/%d, date %d/%d %s" % (t_ok, t_n, d_ok, d_n, "; ".join(diffs[:5])))


# --- J3: claim flow in code -----------------------------------------------------------------------

DESC = "Samsung Galaxy S23, 256 GB, new, factory sealed."
NO_PROOF = {"account": "It has 128 GB.", "promised": "256 GB", "received": "128 GB", "proof_kind": "", "proof": ""}
PROOF = dict(NO_PROOF, proof_kind="label", proof="SM-S911B 128GB")
LABEL_PROOF = {"proof_kind": "label", "proof": "SM-S911B 128GB"}
DENIAL = "We only sell what we list."
DISPUTE = "Our test report for this unit, serial R5CT12, shows 256 GB."


def flow_world(claim_fields, q1, q2, order):
    w = World("subjective")
    c = claim_subjective(order, DESC, claim_fields, flow_facts())
    w.committee.lookup = scripted({"q1": q1, "q2": q2})
    return w, c


WAIT_PROOF = ("wait", "NOT_YET", 0, "proof required")
REFUND = ("decide", "REFUND", 5000, "per policy")


def flow_tests():
    """The 9 cases of tests/test_claim_flow.py as calls to the subjective judge. Under the chain
    model the escrow applies the deadlines: expired proof is closed by releaseUnproven (Foundry tests)."""
    out = []
    # 1. Proof path: requested once; then the contract waits; the expiry belongs to the escrow.
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "F1")
    a = [w.judge(c, [response(DENIAL)], at(c, 1)), outcome(w, c)]
    a += [w.judge(c, [], at(c, 101)), outcome(w, c)]
    a += [w.judge(c, [], at(c, 1 + 168)), outcome(w, c)]
    out.append(("proof path requested once; expiry left to the escrow",
                a[1] == ("request_proof", "NOT_YET", 0, "proof required") and a[3] == WAIT_PROOF and a[5] == WAIT_PROOF, a))
    # 2. Proof sent but malformed: DENY claim not proven.
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "F2")
    w.judge(c, [response(DENIAL)], at(c, 1))
    w.judge(c, [proof_sub({"proof_kind": "photo", "proof": "photo of the settings screen"})], at(c, 21))
    out.append(("proof submitted but still malformed is not proven",
                outcome(w, c) == ("decide", "DENY", 0, "claim not proven"), outcome(w, c)))
    # 3. Proof sent and well formed: REFUND.
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "F3")
    w.judge(c, [response(DENIAL)], at(c, 1))
    w.judge(c, [proof_sub(LABEL_PROOF)], at(c, 21))
    out.append(("proof submitted and well formed is refunded", outcome(w, c) == REFUND, outcome(w, c)))
    # 4. Proof without a request does not count; no more steps after a decision.
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "F4")
    w.judge(c, [response(DENIAL), proof_sub(LABEL_PROOF)], at(c, 1))
    first = outcome(w, c)
    w.judge(c, [proof_sub({"proof_kind": "photo", "proof": "nothing"})], at(c, 2))
    decided = outcome(w, c)
    again = w.judge(c, [proof_sub(LABEL_PROOF)], at(c, 3))
    out.append(("proof without request does not count; nothing after a decision",
                first == ("request_proof", "NOT_YET", 0, "proof required")
                and decided == ("decide", "DENY", 0, "claim not proven") and again == ("error", CODES["F2"]),
                [first, decided, again]))
    # 5. The closing round opens only once.
    w, c = flow_world(NO_PROOF, "differs", "disputes_with_fact", "F5")
    w.judge(c, [response(DISPUTE)], at(c, 1))
    opened = outcome(w, c)
    w.judge(c, [marker("closing_open"), {"party": "merchant", "kind": "closing_response",
                                         "content": "We checked again: our test report shows 256 GB."}], at(c, 30))
    waiting = outcome(w, c)
    w.judge(c, [marker("closing_timeout")], at(c, 110))
    closed = outcome(w, c)
    again = w.judge(c, [marker("closing_open")], at(c, 120))
    out.append(("closing round opens once",
                opened[0] == "open_closing_round" and waiting == ("wait", "NOT_YET", 0, "closing round open")
                and closed == ("decide", "DENY", 0, "claim not proven") and again == ("error", CODES["F2"]),
                [opened, waiting, closed, again]))
    # 6. Closing round: admits, silent with proof, or general denial with proof: REFUND.
    res = []
    for i, (claim_fields, text, q2r2, proof) in enumerate((
            (NO_PROOF, "You are right, we shipped the 128 GB unit.", "admits", None),
            (NO_PROOF, "", None, LABEL_PROOF),
            (PROOF, DENIAL, "general_denial", None))):
        w, c = flow_world(claim_fields, "differs", "disputes_with_fact", "F6%d" % i)
        w.judge(c, [response(DISPUTE)], at(c, 1))
        w.committee.lookup = scripted({"q1": "differs", "q2": q2r2 or "admits"})
        w.judge(c, closing(text, proof), at(c, 110))
        st = w.state(c)
        res.append(outcome(w, c) == REFUND and st["closing"]["done"] and not st["proof_req"])
    out.append(("closing round admitted or silent with proof is refunded", all(res), res))
    # 7. Closing round without proof: moves to the proof path once; neither repeats.
    w, c = flow_world(NO_PROOF, "differs", "disputes_with_fact", "F7")
    w.judge(c, [response(DISPUTE)], at(c, 1))
    w.judge(c, closing("", None), at(c, 110))
    asked = outcome(w, c)
    st = w.state(c)
    w.judge(c, [marker("closing_open")], at(c, 120))
    second_round = outcome(w, c)
    w.judge(c, [], at(c, 110 + 200))
    out.append(("closing round without proof moves to proof path once",
                asked == ("request_proof", "NOT_YET", 0, "proof required") and st["closing"]["done"]
                and st["proof_req"] and second_round == WAIT_PROOF and outcome(w, c) == WAIT_PROOF,
                [asked, second_round, outcome(w, c)]))
    # 8. No contradiction, no closing round: a closing submission does not count.
    w, c = flow_world(PROOF, "differs", "general_denial", "F8")
    w.judge(c, [response(DENIAL), {"party": "merchant", "kind": "closing_response", "content": "x"}], at(c, 1))
    out.append(("no closing round without contradiction", outcome(w, c) == REFUND, outcome(w, c)))
    # 9. Well-formed proof after the closing round: REFUND; malformed: DENY.
    res = []
    for p, want in ((LABEL_PROOF, REFUND), ({"proof_kind": "photo", "proof": "photo of the box"},
                                            ("decide", "DENY", 0, "claim not proven"))):
        w, c = flow_world(NO_PROOF, "differs", "disputes_with_fact", "F9" + p["proof_kind"])
        w.judge(c, [response(DISPUTE)], at(c, 1))
        w.judge(c, closing("", None), at(c, 110))
        w.judge(c, [proof_sub(p)], at(c, 120))
        res.append(outcome(w, c) == want)
    out.append(("well formed proof after closing round is refunded", all(res), res))
    return out


def resolve_date_tests(module):
    """The 9 tests of tests/test_resolve_date.py against the email judge's resolve_date and canonical."""
    canonical = lambda q, raw: module._cd(raw) if q == "date" else module._ct(raw)  # noqa: E731
    test_resolve_date.r = module._rd
    test_resolve_date.m = types.SimpleNamespace(resolve_date=module._rd, canonical=canonical,
                                                PROMPTS=test_resolve_date.m.PROMPTS,
                                                mail_llm=test_resolve_date.m.mail_llm)
    out = []
    for name in sorted(k for k in vars(test_resolve_date) if k.startswith("test_")):
        try:
            getattr(test_resolve_date, name)()
            out.append((name, True, ""))
        except AssertionError as e:
            out.append((name, False, str(e)))
    return out


def b0_tests():
    """The 23 emails of B0: valid ones count with their type and date; negative ones do not count."""
    out = []
    for m in MAIL["positives"] + MAIL["negatives"]:
        w = World("mail")
        exp = m["expected_code"]
        answers = {"type": m["expected_type"] or "other"}
        if m.get("expected_date_b2"):
            y, mo, d = m["expected_date_b2"].split("-")
            answers["date"] = "%d|%d|%d" % (int(mo), int(d), int(y))
        elif m.get("expected_date") == "":
            answers["date"] = "||"
        claim = claim_mail(m["claim_order"])
        got = w.judge(claim, [w.ev(m["id"])], MAIL_DAY, scripted(answers))
        st = w.state(claim)
        es = st["emails"] if st else []
        if exp["usable"]:
            want_date = exp["fixed_dates"][0] if exp["fixed_dates"] else None
            good = (got[0] == "ok" and len(es) == 1 and es[0]["type"] == answers["type"]
                    and (want_date is None or es[0]["date"] == want_date))
        else:
            good = got[0] == "ok" and es == [] and outcome(w, claim) == ("wait", "NOT_YET", 0, "signed emails required")
        out.append((m["id"], good, (got, es[:1])))
    return out


# --- J4 to J7, J11 --------------------------------------------------------------------------------

NOT_COUNTED = ("wait", "NOT_YET", 0, "signed emails required")


def lacre_rejections():
    """J4: an email without a valid attestation for this store does not count (it is ignored and does
    not block the claim); only an unreadable Lacre is an error, which is retried."""
    out = []

    def attempt(name, prep, mid, order):
        w = World("mail")
        claim = claim_mail(order)
        rid = prep(w)
        r = w.judge(claim, [w.ev(mid, record_id=rid)], MAIL_DAY, scripted({"type": "shipped"}))
        st = w.state(claim)
        out.append((name, r[0] == "ok" and outcome(w, claim) == NOT_COUNTED and st["emails"] == [] and not w.c.used,
                    (r, outcome(w, claim))))

    attempt("record does not exist", lambda w: "999", "E01", "DS-100231")

    def invalid(w):
        w.node.verifier.final["50"] = dict(w.node.verifier.final[w.ids["E01"]], valid=False)
        return "50"
    attempt("record not valid", invalid, "E01", "DS-100231")
    attempt("record not aligned (N4)", lambda w: None, "N4", "DS-100239")

    def key_state(state):
        def prep(w):
            w.node.keycache.records[(DOMAIN, SELECTOR)]["state"] = state
        return prep
    attempt("key not active (rotated)", key_state("rotated"), "E01", "DS-100231")
    attempt("key not active (pending)", key_state("pending"), "E01", "DS-100231")
    attempt("body differs from bh (N1)", lambda w: None, "N1", "DS-100237")

    def tampered(w):
        w.mails["E01x"] = w.mails["E01"].replace(b"USD 49.90", b"USD 99.90")
        return w.ids["E01"]
    attempt("body changed (amount)", tampered, "E01x", "DS-100231")

    w = World("mail")
    w.judge(claim_mail("DS-100231"), [w.ev("E01")], MAIL_DAY, scripted({"type": "order_confirmed"}))
    w.node.verifier.final["60"] = dict(w.node.verifier.final[w.ids["E01"]])  # the same email attested again
    c2 = claim_mail("DS-100232")
    r = w.judge(c2, [w.ev("E01", record_id="60")], MAIL_DAY)
    out.append(("record already used by another order", r[0] == "ok" and w.state(c2)["emails"] == [], r))
    attempt("email about another order (N2)", lambda w: None, "N2", "DS-100232")

    def other_merchant(w):
        w.node.verifier.final["70"] = dict(w.node.verifier.final[w.ids["E01"]], domain="othershop.example")
        return "70"
    attempt("email from another store", other_merchant, "E01", "DS-100231")

    w = World("mail")
    w.add_mail("E02p", w.mails["E02"], final=False)
    c = claim_mail("DS-100231")
    r = w.judge(c, [w.ev("E02p")], MAIL_DAY, scripted({"type": "shipped"}))
    out.append(("record read before it is final", r[0] == "ok" and w.state(c)["emails"] == [], r))
    views = w.node.verifier.states + w.node.router.states + w.node.keycache.states
    out.append(("every Lacre read in LATEST_FINAL", bool(views) and all(
        s == stub.StorageType.LATEST_FINAL for s in views), len(views)))
    w = World("mail")
    w.node.router.broken = True
    before = w.snapshot()
    r = w.judge(claim_mail("DS-100231"), [w.ev("E01")], MAIL_DAY, scripted({"type": "shipped"}))
    out.append(("unreadable Lacre: error that is retried, no changes", r == ("error", CODES["L2"])
                and unchanged(w, before), r))
    return out


def late_232(w, c):
    """DS-100232 late: E04 without a date, E05 shipped (September 15), E07 delivered (24th): REFUND 50%."""
    for mid, typ, date in (("E04", "order_confirmed", "9|15|2026"), ("E05", "shipped", "9|15|2026"),
                           ("E07", "delivered", "9|24|2026")):
        w.judge(c, [w.ev(mid)], MAIL_DAY, scripted({"type": typ, "date": date}))


def binding_tests():
    out = []
    w = World("mail")
    claim = claim_mail("DS-100231")
    sub = w.ev("E01")
    w.judge(claim, [sub], MAIL_DAY, scripted({"type": "order_confirmed"}))
    v = w.verdict(claim)
    h = sha(cj(claim))
    out.append(("verdict bound to the order, the claim hash and the escrow chain",
                v["order_ref"] == claim["order_ref"] and v["buyer"] == BUYER and v["amount_cents"] == 4990
                and v["terms_hash"] == TERMS_HASH and v["claim_hash"] == h and v["chain"] == fold(chain0(h), cj(sub)), v))
    for name, change, expect in (("store not registered", {"merchant": OTHER_MERCHANT}, ("error", CODES["M4"])),
                                 ("another terms hash", {"terms_hash": "0x" + "ab" * 32}, ("error", CODES["M5"]))):
        w = World("mail")
        r = w.judge(dict(claim_mail("DS-100231"), **change), [], MAIL_DAY, scripted({}))
        out.append((name, r == expect, r))
    c = claim_mail("DS-100232")
    w = World("mail")
    late_232(w, c)
    v = w.verdict(c)
    again = w.judge(c, [w.ev("E06")], "2026-10-03T00:00:00Z", scripted({"type": "delayed", "date": "9|24|2026"}))
    out.append(("claim already decided: no more steps", v["final"] and v["outcome"] == "REFUND" and v["refund_cents"] == 6000
                and again == ("error", CODES["F2"]), (v["outcome"], v["refund_cents"], again)))
    c2 = dict(c, claimed_at=c["claimed_at"] + 60)
    r = w.judge(c2, [], "2026-10-03T00:00:00Z")
    out.append(("another claim for the same order is another chain (the escrow allows one at a time)",
                r[0] == "ok" and w.verdict(c2)["claim_hash"] != v["claim_hash"], r))
    w = World("mail")
    r = w.judge(claim_mail("DS-100231"), [], MAIL_DAY, scripted({}))
    bad_prev = w.write(RELAYER, MAIL_DAY, "judge", cj(claim_mail("DS-100231")), cj({"chain": "0x" + "1" * 64,
                                                                                    "submissions": []}))
    out.append(("unknown previous chain: error", bad_prev == ("error", CODES["S2"]), bad_prev))
    return out, v


def hash_tests():
    out = []
    base = claim_mail("DS-100231")
    w = World("mail")
    w.judge(base, [w.ev("E01")], MAIL_DAY, scripted({"type": "order_confirmed"}))
    h0, ch0 = w.verdict(base)["claim_hash"], w.verdict(base)["chain"]
    for name, change in (("event", {"event": "late"}), ("payment time", {"paid_at": base["paid_at"] + 1}),
                         ("amount", {"amount_cents": 4991}),
                         ("reference and number", {"order_number": "DS-100232", "order_ref": mail_v1.order_ref("DS-100232")}),
                         ("buyer", {"buyer": "0x" + "e" * 40}), ("claim time", {"claimed_at": base["claimed_at"] + 1}),
                         ("reference alone", {"order_ref": "0x" + "1" * 64})):
        if change == {"event": "late"}:
            continue
        w = World("mail")
        c = dict(base, **change)
        r = w.judge(c, [w.ev("E01")], MAIL_DAY, scripted({"type": "order_confirmed"}))
        v = w.verdict(c)
        out.append((name, r[0] == "error" or (v is not None and v["claim_hash"] != h0 and v["chain"] != ch0),
                    (r, v and v["outcome"])))
    w = World("mail")
    s1 = w.ev("E01")
    s2 = dict(s1, content=dict(s1["content"], record_id=" " + s1["content"]["record_id"]))
    w.judge(base, [s2], MAIL_DAY, scripted({"type": "order_confirmed"}))
    out.append(("a changed submission gives another chain", w.verdict(base)["chain"] != ch0, ""))
    return out


def no_majority_tests():
    out = []
    for name, answers in (("split answers", [verdict_raw("differs")] * 2 + [verdict_raw("matches")] * 2
                           + [ValueError("x")]),
                          ("unreadable answers", [ValueError("no JSON")] * 3 + [verdict_raw("differs")] * 2),
                          ("model error", [RuntimeError("timeout")] * 3 + [verdict_raw("differs")] * 2),
                          ("wrong shape", [{"verdict": "maybe"}] * 3 + [verdict_raw("differs")] * 2)):
        w = World("subjective")
        c = claim_subjective("NM", DESC, PROOF, flow_facts())
        before = w.snapshot()
        r = w.judge(c, [response(DENIAL)], at(c, 1), scripted({"q1": answers, "q2": "general_denial"}))
        same = unchanged(w, before)
        v, st = w.verdict(c), w.state(c)
        no_deny = (v is None or v["outcome"] == "NO_CONSENSUS") and st is None
        resend = w.judge(c, [], at(c, 2), scripted({"q1": "differs", "q2": "general_denial"}))
        v2 = w.verdict(c)
        out.append((name, (r[0] == "split" and same or r == ("ok", "NO_CONSENSUS")) and no_deny
                    and resend[0] == "ok" and v2["outcome"] == "REFUND", (r, v and v["outcome"], v2["outcome"])))
    w = World("mail")
    c = claim_mail("DS-100233")
    r = w.judge(c, [w.ev("E10")], MAIL_DAY, scripted({"type": [ValueError("x")] * 3 + [verdict_raw("shipped")] * 2}))
    v = w.verdict(c)
    out.append(("unreadable email", r == ("ok", "NO_CONSENSUS") and v["outcome"] == "NO_CONSENSUS"
                and w.state(c) is None and not w.c.used, (r, v["outcome"])))
    return out


def once_tests():
    """J7: once-only paths; a submission out of turn or from the wrong party does not count."""
    out = []
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "O1")
    w.judge(c, [response(DENIAL)], at(c, 1))
    actions = [w.verdict(c)["action"]]
    for h in (50, 100, 150):
        w.judge(c, [], at(c, 1 + h))
        actions.append(w.verdict(c)["action"])
    out.append(("proof requested only once", actions.count("request_proof") == 1, actions))
    w, c = flow_world(NO_PROOF, "differs", "disputes_with_fact", "O2")
    w.judge(c, [response(DISPUTE)], at(c, 1))
    w.judge(c, closing("", None), at(c, 110))
    w.judge(c, closing("We checked again.", None), at(c, 120))
    out.append(("a second closing round does not count", outcome(w, c) == WAIT_PROOF, outcome(w, c)))
    w, c = flow_world(NO_PROOF, "differs", "disputes_with_fact", "O3")
    w.judge(c, [response(DISPUTE), {"party": "merchant", "kind": "closing_response", "content": "x"},
                {"party": "buyer", "kind": "closing_proof", "content": LABEL_PROOF}], at(c, 1))
    out.append(("closing submissions before the round opens do not count",
                outcome(w, c) == ("open_closing_round", "NOT_YET", 0, "closing round"), outcome(w, c)))
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "O4")
    w.judge(c, [proof_sub(LABEL_PROOF)], at(c, 1))
    out.append(("proof without a request does not count", outcome(w, c) == ("wait", "NOT_YET", 0, "awaiting store response")
                and not w.state(c)["proof"], outcome(w, c)))
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "O5")
    w.judge(c, [{"party": "buyer", "kind": "response", "content": "I admit nothing"}], at(c, 1))
    out.append(("the buyer cannot send the store's answer",
                outcome(w, c) == ("wait", "NOT_YET", 0, "awaiting store response"), outcome(w, c)))
    w, c = flow_world(PROOF, "differs", "general_denial", "O6")
    w.judge(c, [response(DENIAL), response("We admit it, sorry.")], at(c, 1))
    out.append(("a second answer does not count", outcome(w, c) == REFUND and w.committee.log[0][1] == "differs",
                outcome(w, c)))
    w, c = flow_world(PROOF, "differs", "general_denial", "O7")
    w.judge(c, [response("   ")], at(c, 1))
    out.append(("empty answer = no answer", outcome(w, c) == REFUND and w.state(c)["no_response"], outcome(w, c)))
    w, c = flow_world(PROOF, "differs", "general_denial", "O8")
    w.judge(c, [marker("no_response")], at(c, 73))
    out.append(("no_response marker: the code decides without the committee", outcome(w, c) == REFUND and not w.committee.log,
                outcome(w, c)))
    w, c = flow_world(PROOF, "differs", "general_denial", "O9")
    w.judge(c, [response(DENIAL), marker("no_response")], at(c, 73))
    out.append(("no_response marker after an answer does not count", outcome(w, c) == REFUND
                and not w.state(c)["no_response"], outcome(w, c)))
    w, c = flow_world(PROOF, "differs", "general_denial", "O10")
    w.judge(c, ['{"party":"merchant"}', "not json", '{"content": "x", "kind": "response", "party": "merchant"}'], at(c, 1))
    out.append(("malformed (non canonical) submissions do not block", outcome(w, c) == ("wait", "NOT_YET", 0,
                                                                               "awaiting store response"), outcome(w, c)))
    return out


def merchant_mail_tests():
    """J11: an email presented by the store has no effect."""
    out = []
    for name, order, first, mid in (("store presents its delivered email", "DS-100231", "E01", "E03"),
                                    ("store presents its refund_issued email", "DS-100233", "E08", "E10"),
                                    ("store presents its shipped email", "DS-100231", "E01", "E02")):
        w = World("mail")
        c = claim_mail(order)
        w.judge(c, [w.ev(first)], MAIL_DAY, scripted({"type": "order_confirmed"}))
        before = outcome(w, c)
        emails = w.state(c)["emails"]
        r = w.judge(c, [w.ev(mid, party="merchant")], MAIL_DAY, scripted({"type": "delivered", "date": "9|7|2026"}))
        out.append((name, r[0] == "ok" and outcome(w, c) == before and w.state(c)["emails"] == emails, r))
    w = World("mail")
    c = claim_mail("DS-100231")
    w.judge(c, [w.ev("E01"), w.ev("E03", party="merchant")], MAIL_DAY, scripted({"type": "order_confirmed"}))
    out.append(("mixed with a buyer submission: only the buyer's counts", len(w.state(c)["emails"]) == 1,
                w.state(c)["emails"]))
    w, c = flow_world(PROOF, "differs", "general_denial", "M5")
    w.judge(c, [response(DENIAL), {"party": "merchant", "kind": "evidence", "content": {}}], at(c, 1))
    out.append(("subjective judge: an email from the store has no effect", outcome(w, c) == REFUND, outcome(w, c)))
    return out


def against_merchant_tests():
    out = []
    w = World("mail")
    r = w.judge(claim_mail("DS-100231", "not_delivered"), [w.ev("E01")], MAIL_DAY, scripted({"type": "order_confirmed"}))
    out.append(("not_delivered does not go through the email judge", r == ("error", CODES["C3"]), r))
    results = []
    for mids in (["E08"], ["E08", "E10"]):
        w = World("mail")
        c = claim_mail("DS-100233")
        for mid in mids:
            w.judge(c, [w.ev(mid)], MAIL_DAY, scripted({"type": "refund_issued" if mid == "E10" else "order_confirmed"}))
        results.append(outcome(w, c))
    out.append(("a refund_issued email from the buyer closes nothing", results[0] == results[1] and results[1][1] != "DENY", results))
    return out


# --- not_delivered ----------------------------------------------------------------------------------

ND = json.load(open(ROOT / "cases" / "nd.json", encoding="utf-8"))


def claim_nd(order, account):
    f = ND["facts"]
    return {"v": "claim-v1", "order_ref": mail_v1.order_ref(order), "order_number": order, "buyer": BUYER,
            "merchant": MERCHANT, "amount_cents": f["amount_cents"], "paid_at": unix(f["purchase_date"], 12),
            "claimed_at": unix(f["claim_date"], 12), "terms_hash": TERMS_HASH, "event": "not_delivered",
            "account": account, "promised_date": f["promised_date"]}


def run_nd(rep, stats):
    """ND metrics locally: the recorded answers of results/local-nd.jsonl through the subjective judge."""
    import not_delivered as nd
    rows = [json.loads(l) for l in (ROOT / "results" / "local-nd.jsonl").read_text(encoding="utf-8").splitlines()]
    by = {(r["pass"], r["case"], r["question"], r["model"]): r for r in rows}
    votes = collections.defaultdict(dict)
    for r in rows:
        votes[(r["pass"], r["case"], r["question"])][r["model"]] = r["verdict"]
    t = collections.Counter()
    diffs = []
    for n in sorted({r["pass"] for r in rows}):
        w = World("subjective")
        for it in ND["cases"]:
            r2 = it.get("closing") or {}
            rounds = {"first": {nd.build_prompt(it["account"], it["response"]): "q2"}, "closing": {}}
            if r2.get("response"):
                rounds["closing"][nd.build_prompt(it["account"], r2["response"], r2.get("statement"))] = "q2r2"
            stage = ["first"]

            def lookup(prompt, n=n, it=it, rounds=rounds, stage=stage):
                q = rounds[stage[0]].get(prompt)
                if q is None:
                    return None
                stats["prompts_n"] += 1
                return q, [recorded_answer(by.get((n, it["id"], q, m))) for m in MODELS]
            c = claim_nd("ND-%s" % it["id"], it["account"])
            got = w.judge(c, [response(it["response"])], at(c, 1), lookup)
            if got[0] == "ok" and w.verdict(c)["action"] == "open_closing_round":
                stage[0] = "closing"
                got = w.judge(c, closing(r2.get("response"), None, r2.get("statement")), at(c, 110))
            mine = list(as_tuple(w, c, got))
            if got[0] == "ok":
                stats["verdicts"].append((w.verdict(c), w.state(c)))
            maj = {q: majority([votes.get((n, it["id"], q), {}).get(m) for m in MODELS]) for q in ("q2", "q2r2")}
            lab = nd.label(maj["q2"], r2.get("response", "") if nd.needs_closing_round(maj["q2"]) else "", maj["q2r2"])
            report = list(nd.decide(lab, ND["policy"], ND["facts"]))
            exp = it["expected_decision"]
            t["runs"] += 1
            t["parity"] += mine == report
            if mine != report:
                diffs.append("%s pass %d: contract %s, ND report %s" % (it["id"], n, mine, report))
            t["ND1"] += mine[0] != "NO_CONSENSUS"
            t["ND2"] += maj["q2"] == it["expected"]["q2"]
            t["ND3"] += mine == exp
            t["ND4"] += mine[0] == "DENY" and exp[0] != "DENY"
            t["ND5"] += mine[0] == "REFUND" and exp[0] == "DENY"
            if it["injection_target"]:
                t["inj"] += 1
                t["ND6"] += (mine[0] == "DENY") if it["injection_target"] == "not_proven" else (mine[0] == "REFUND")
        stats["det_fail"] += w.committee.det_fail
        stats["formats"].update(w.committee.formats)
        stats["unknown_n"] += w.committee.unknown_prompts
    for v in ND["incomplete"]:
        w = World("subjective")
        c = claim_nd("ND-%s" % v["id"], v["account"])
        r = w.judge(c, [response(v["response"])], at(c, 1), scripted({}))
        t["incomplete"] += r == ("ok", "INVALID_CLAIM") and w.verdict(c)["final"] and not w.committee.log
    for v in C3["incomplete"]:
        w = World("subjective")
        c = claim_subjective("C3-%s" % v["id"], v["description"], v["claim"], flow_facts())
        r = w.judge(c, [response("We only sell what we list.")], at(c, 1), scripted({}))
        t["incomplete"] += r == ("ok", "INVALID_CLAIM") and w.verdict(c)["final"] and not w.committee.log
    n = t["runs"]
    rep.metric("JN", "not_delivered: contract = ND report with the same answers", t["parity"], n, "; ".join(diffs[:5]))
    for mid, text, ok, need in (("ND1", "decision with a majority", t["ND1"], 288), ("ND2", "Q2-ND first round correct", t["ND2"], 304),
                                ("ND3", "correct decision", t["ND3"], 304)):
        rep.metric(mid, "%s (contract; threshold %d)" % (text, need), ok, n, need=need)
    rep.metric("ND4", "wrong DENY (contract)", int(t["ND4"] == 0), 1, "%d" % t["ND4"])
    rep.metric("ND5", "wrong REFUND (contract)", int(t["ND5"] == 0), 1, "%d" % t["ND5"])
    rep.metric("ND6", "prompt injection that wins, of %d (contract)" % t["inj"], int(t["ND6"] == 0), 1, "%d" % t["ND6"])
    rep.metric("ND7", "incomplete claim (ND V1-V2, C3 V1-V2): INVALID_CLAIM without the committee", t["incomplete"],
               len(ND["incomplete"]) + len(C3["incomplete"]))


def nd_procedure_tests():
    out = []
    ACC = ND["cases"][0]["account"]
    FACT = "Delivered September 9, 14:32, front door, signed by J. Perez."
    ND_REFUND = ("decide", "REFUND", 5000, "per policy")

    def fresh(order, q2):
        w = World("subjective")
        c = claim_nd(order, ACC)
        w.committee.lookup = scripted({}) if q2 is None else (
            lambda p: ("q2", [verdict_raw(q2)] * 5) if "the buyer says the order never arrived" in p else None)
        return w, c
    w, c = fresh("P1", None)
    r1 = (w.judge(c, [], at(c, 10)), outcome(w, c))
    r2 = (w.judge(c, [marker("no_response")], at(c, 80)), outcome(w, c))
    out.append(("nd: no answer waits for the marker, then REFUND",
                r1[1] == ("wait", "NOT_YET", 0, "awaiting store response") and r2[1] == ND_REFUND, [r1, r2]))
    w, c = fresh("P2", "general_denial")
    w.judge(c, [response("We shipped it.")], at(c, 1))
    out.append(("nd: general denial: REFUND", outcome(w, c) == ND_REFUND, outcome(w, c)))
    w, c = fresh("P3", "disputes_with_fact")
    w.judge(c, [response(FACT)], at(c, 1))
    opened = outcome(w, c)
    w.judge(c, closing(FACT, None, "Nobody here signed."), at(c, 30))
    closed = outcome(w, c)
    again = w.judge(c, [marker("closing_open")], at(c, 31))
    out.append(("nd: a fact twice: DENY; no more steps after it",
                opened[0] == "open_closing_round" and closed == ("decide", "DENY", 0, "claim not proven")
                and again == ("error", CODES["F2"]), [opened, closed, again]))
    w, c = fresh("P4", "disputes_with_fact")
    w.judge(c, [response(FACT)], at(c, 1))
    w.judge(c, closing("", None, "Nobody here signed."), at(c, 110))
    out.append(("nd: closing round without the store's answer: REFUND", outcome(w, c) == ND_REFUND, outcome(w, c)))
    w, c = fresh("P5", "general_denial")
    w.judge(c, [response("We shipped it."), {"party": "merchant", "kind": "closing_response", "content": "x"}], at(c, 1))
    out.append(("nd: no fact, no closing round", outcome(w, c) == ND_REFUND, outcome(w, c)))
    w, c = fresh("P6", "admits")
    w.judge(c, [{"party": "buyer", "kind": "response", "content": "It is lost."}], at(c, 1))
    out.append(("nd: the buyer cannot send the store's answer",
                outcome(w, c) == ("wait", "NOT_YET", 0, "awaiting store response"), outcome(w, c)))
    w, c = fresh("P7", "disputes_with_fact")
    w.judge(c, [response(FACT), marker("closing_open"),
                {"party": "merchant", "kind": "closing_statement", "content": "x"}], at(c, 1))
    out.append(("nd: the store cannot send the buyer's statement",
                outcome(w, c) == ("wait", "NOT_YET", 0, "closing round open"), outcome(w, c)))
    w, c = fresh("P8", "admits")
    w.judge(c, [proof_sub(LABEL_PROOF)], at(c, 1))
    out.append(("nd: there is no proof request", outcome(w, c) == ("wait", "NOT_YET", 0, "awaiting store response"),
                outcome(w, c)))
    return out


# --- JX1 and JX2 -----------------------------------------------------------------------------------

def invalid_claim_tests():
    """JX1: a claim the judge cannot read gets a final INVALID_CLAIM; one for the other contract is an error."""
    out = []
    base = claim_mail("DS-100231")
    text = cj(base)
    cases = (("with spaces (not canonical)", json.dumps(base, sort_keys=True)),
             ("keys out of order", json.dumps(base, separators=(",", ":"))),
             ("repeated key", text[:-1] + ',"v":"claim-v1"}'),
             ("missing field", cj({k: v for k, v in base.items() if k != "terms_hash"})),
             ("extra field", cj(dict(base, extra="x"))),
             ("date as text", cj(dict(base, paid_at="2026-09-01"))),
             ("amount with decimals", cj(dict(base, amount_cents=49.9))),
             ("unknown event", cj(dict(base, event="lost"))),
             ("order_ref that is not the number's", cj(dict(base, order_ref="0x" + "1" * 64))),
             ("payment after the claim", cj(dict(base, paid_at=base["claimed_at"] + 1))),
             ("not JSON", "not json"))
    for name, claim_text in cases:
        w = World("mail")
        r = w.judge(claim_text, [w.ev("E01")], MAIL_DAY, scripted({"type": "order_confirmed"}))
        v = w.verdict(claim_text)
        out.append((name, r == ("ok", "INVALID_CLAIM") and v["outcome"] == "INVALID_CLAIM" and v["final"]
                    and v["claim_hash"] == sha(claim_text) and v["chain"] == w.chain(claim_text)
                    and not w.committee.log, r))
    w = World("subjective")
    r = w.judge(claim_mail("DS-100231"), [], MAIL_DAY)
    out.append(("claim for the other contract: error, not INVALID", r == ("error", CODES["C3"]), r))
    return out


def griefing_tests():
    """JX2: invented submissions nobody registered in the escrow open another branch and do not block the real one."""
    out = []
    w, c = flow_world(NO_PROOF, "differs", "general_denial", "G1")
    text, e = w.entry(c)
    c0 = e["judged"]
    fake = cj({"party": "merchant", "kind": "response", "content": "You are right, we admit it."})
    w.committee.lookup = scripted({"q1": "differs", "q2": "admits"})
    r_fake = w.write(STRANGER_GL, at(c, 1), "judge", text, cj({"chain": c0, "submissions": [fake]}))
    fake_v = json.loads(w.c.get_verdict(fold(c0, fake)))
    w.committee.lookup = scripted({"q1": "differs", "q2": "general_denial"})
    real = w.judge(c, [response(DENIAL)], at(c, 2))
    v = w.verdict(c)
    out.append(("an invented answer does not block the real one", r_fake[0] == "ok" and fake_v["outcome"] == "REFUND"
                and real[0] == "ok" and v["action"] == "request_proof" and v["chain"] == fold(c0, cj(response(DENIAL)))
                and fake_v["chain"] != v["chain"], (fake_v["outcome"], v["action"])))
    w2, c2 = flow_world(PROOF, "differs", "general_denial", "G2")
    text2, e2 = w2.entry(c2)
    c20 = e2["judged"]
    w2.write(STRANGER_GL, at(c2, 1), "judge", text2, cj({"chain": c20, "submissions": [cj(marker("no_response"))]}))
    real2 = w2.judge(c2, [response(DENIAL)], at(c2, 2))
    out.append(("an invented marker does not block the real branch", real2[0] == "ok" and outcome(w2, c2) == REFUND
                and not w2.state(c2)["no_response"], outcome(w2, c2)))
    w3 = World("mail")
    c3 = claim_mail("DS-100231")
    text3, e3 = w3.entry(c3)
    w3.write(STRANGER_GL, MAIL_DAY, "judge", text3, cj({"chain": e3["judged"], "submissions": [cj(w3.ev("E03"))]}))
    real3 = w3.judge(c3, [w3.ev("E01")], MAIL_DAY, scripted({"type": "order_confirmed"}))
    out.append(("emails: an unregistered step does not block the real one", real3[0] == "ok" and len(w3.state(c3)["emails"]) == 1,
                real3))
    return out


STRANGER_GL = "0x2222222222222222222222222222222222222222"


def ignored_list_tests():
    """JX3: the email judge's verdict lists every submission that did not count, with its code."""
    out = []

    def run(name, order, items, want, prep=None, claim=None):
        w = World("mail")
        if prep:
            prep(w)
        c = claim or claim_mail(order)
        objs = [it(w) if callable(it) else it for it in items]
        raws = [x if isinstance(x, str) else cj(x) for x in objs]
        r = w.judge(c, objs, MAIL_DAY, scripted({"type": "order_confirmed"}))
        got = w.verdict(c)["ignored"] if r[0] == "ok" else r
        out.append((name, got == [[sha(raws[i]), code] for i, code in want], got))

    run("valid: empty list", "DS-100231", [lambda w: w.ev("E01")], [])
    run("I1 not canonical", "DS-100231", ["not json", lambda w: w.ev("E01")], [(0, "I1")])
    run("I2 email from the store", "DS-100231", [lambda w: w.ev("E01", party="merchant")], [(0, "I2")])
    run("I3 the same email twice", "DS-100231", [lambda w: w.ev("E01"), lambda w: w.ev("E01")], [(1, "I3")])
    run("I4 malformed content", "DS-100231", [{"party": "buyer", "kind": "evidence", "content": {}}], [(0, "I4")])
    run("I5 no record", "DS-100231", [lambda w: w.ev("E01", record_id="999")], [(0, "I5")])
    run("I5 not aligned (N4)", "DS-100239", [lambda w: w.ev("N4")], [(0, "I5")])

    def rotate(w):
        w.node.keycache.records[(DOMAIN, SELECTOR)]["state"] = "rotated"
    run("I6 key not active", "DS-100231", [lambda w: w.ev("E01")], [(0, "I6")], prep=rotate)
    run("I7 different body (N1)", "DS-100237", [lambda w: w.ev("N1")], [(0, "I7")])
    run("I8 another order (N2)", "DS-100232", [lambda w: w.ev("N2")], [(0, "I8")])
    run("I9 signed before payment", "DS-100231", [lambda w: w.ev("E01")], [(0, "I9")],
        claim=dict(claim_mail("DS-100231"), paid_at=unix("2026-09-02")))
    w = World("mail")
    w.judge(claim_mail("DS-100231"), [w.ev("E01")], MAIL_DAY, scripted({"type": "order_confirmed"}))
    w.node.verifier.final["60"] = dict(w.node.verifier.final[w.ids["E01"]])
    c2 = claim_mail("DS-100232")
    s = w.ev("E01", record_id="60")
    w.judge(c2, [s], MAIL_DAY)
    out.append(("I8 already used by another order", w.verdict(c2)["ignored"] == [[sha(cj(s)), "I8"]], w.verdict(c2)["ignored"]))
    return out


def deduce_subjective(c, raws, st, ok):
    """What a frontend would do with the subjective judge, which does not carry the list: the fixed
    rules (canonical form, allowed pairs) and the judge's state at the verdict's chain
    (get_claim(chain)), walking the submissions registered on Arc in order. Returns [(index, code)]."""
    out = []
    seen = set()
    closing = {"open": False, "done": False, "r": False, "b": False}
    answered = False
    for i, raw in enumerate(raws):
        x = None
        try:
            x = json.loads(raw)
        except Exception:
            pass
        if not (isinstance(x, dict) and set(x) == {"party", "kind", "content"} and cj(x) == raw):
            out.append((i, "I1"))
            continue
        k, v = x["kind"], x["content"]
        if (x["party"], k) not in ok:
            out.append((i, "I2"))
            continue
        if k in ("response", "no_response"):
            if answered:
                out.append((i, "I3"))
            answered = True
        elif k == "closing_open":
            if closing["open"] or st["closing"] is None:
                out.append((i, "I3"))
            closing["open"] = True
        elif k == "proof":
            if not st["proof_req"] or k in seen or st["proof"] != v:
                out.append((i, "I3"))
            seen.add(k)
        else:
            if not closing["open"] or closing["done"] or st["closing"] is None:
                out.append((i, "I3"))
                continue
            if k == "closing_response":
                closing["r"] = True
            elif k != "closing_timeout":
                closing["b"] = True
            if k == "closing_timeout" or closing["r"] and closing["b"]:
                closing["done"] = True
    return out


def subjective_deduction_tests():
    """JX4: with the registered submissions and get_claim(chain), a frontend can deduce which
    submissions did not count in the subjective judge, without changing the contract."""
    out = []
    ok = World("subjective").module.OKS
    fake_party = {"party": "buyer", "kind": "response", "content": "I admit nothing"}
    cases = (
        ("answer, second answer", PROOF, "differs", "general_denial", [response(DENIAL), response("We admit it.")], [1]),
        ("proof without request", NO_PROOF, "differs", "general_denial", [proof_sub(LABEL_PROOF)], [0]),
        ("answer from the buyer", NO_PROOF, "differs", "general_denial", [fake_party], [0]),
        ("closing before opening", NO_PROOF, "differs", "disputes_with_fact",
         [response(DISPUTE), {"party": "merchant", "kind": "closing_response", "content": "x"}], [1]),
        ("marker after an answer", PROOF, "differs", "general_denial", [response(DENIAL), marker("no_response")], [1]),
        ("malformed", PROOF, "differs", "general_denial", ["not json", '{"party":"merchant"}', response(DENIAL)], [0, 1]),
        ("full round and second opening", NO_PROOF, "differs", "disputes_with_fact",
         [response(DISPUTE)] + closing("", None) + [marker("closing_open")], [3]),
        ("proof requested and sent", NO_PROOF, "differs", "general_denial", [response(DENIAL), proof_sub(LABEL_PROOF)], []),
    )
    for name, fields, q1, q2, items, want_idx in cases:
        w, c = flow_world(fields, q1, q2, "D-" + name[:10])
        raws = [x if isinstance(x, str) else cj(x) for x in items]
        if name == "proof requested and sent":
            w.judge(c, items[:1], at(c, 1))
            w.judge(c, items[1:], at(c, 2))
        else:
            w.judge(c, items, at(c, 1))
        st = w.state(c)
        got = [i for i, _ in deduce_subjective(c, raws, st, ok)]
        out.append((name, got == want_idx, (got, want_idx)))
    return out


def equivalence_tests(wm, ws, n=4000):
    """The compact copies inside the contracts against the measured modules, with random inputs
    (fixed seed). Each row: (function, equal, cases)."""
    import random
    import mail_llm_v2
    import not_delivered as nd
    import policy_v2
    import subjective
    from lacre_vendor import dkimbody
    rnd = random.Random(20261012)
    M, S = wm.module, ws.module
    out = []
    words = ["Sept", "September", "septiembre", "Friday", "viernes", "jueves", "Tuesday", "18", "15", "2026", "2025",
             "12", "30", "January", "3", "arrives", "llega", "el", "de", "2027", "feb", "29", "á", "miércoles"]
    same = 0
    for _ in range(n):
        text = " ".join(rnd.choice(words) for _ in range(rnd.randint(0, 8)))
        parts = "%s|%s|%s" % (rnd.choice(["", "1", "2", "9", "12"]), rnd.choice(["", "3", "15", "18", "29", "30", "31"]),
                              rnd.choice(["", "2025", "2026", "2027"]))
        od = "2026-%02d-%02d" % (rnd.randint(1, 12), rnd.randint(1, 28))
        same += M._rd(parts, text, od) == mail_llm_v2.resolve_date(parts, text, od)
    out.append(("resolve_date", same == n, n))
    raws = ['{"verdict": "shipped"}', '{"verdict": "x"}', '{"month": 9, "day": 18, "year": null}', '{"month": "9", "day": 1, "year": null}',
            '{"month": 13, "day": 1, "year": 2026}', '{"month": true, "day": 1, "year": 2026}', "no", "[1]", '{"date": ""}',
            {"verdict": "delivered"}, {"month": None, "day": None, "year": None}, {"verdict": ["shipped"]}]
    same = sum(M._ct(r) == mail_llm_v3.canonical("type", r) and M._cd(r) == mail_llm_v3.canonical("date", r) for r in raws)
    out.append(("canonical type and date", same == len(raws), len(raws)))
    same = 0
    for _ in range(n):
        body = bytes(rnd.choice(b"ab \t\r\n") for _ in range(rnd.randint(0, 30)))
        for canon in ("simple", "relaxed"):
            same += M._bh(body, canon) == dkimbody.body_hash_b64(body, canon)
    out.append(("body_hash_b64", same == 2 * n, 2 * n))
    texts = ["Your order DS-1 shipped.\r\nIt arrives Friday.", "ñ café ’quote’ \r", "x" * 5000, ""]
    same = sum(M._pm(q, t) == mail_llm_v3.build_prompt(q, t) for q in ("type", "date") for t in texts)
    out.append(("email prompts", same == 2 * len(texts), 2 * len(texts)))
    same = 0
    for _ in range(n):
        dt = rnd.choice(["calendar", "business"])
        rule = {"event": rnd.choice(["late", "not_as_described", "not_delivered"]),
                "wait_from": rnd.choice(["none", "purchase", "promised", "delivery"]), "wait_days": rnd.choice([0, 3, 10]),
                "deadline_from": rnd.choice(["none", "purchase", "promised", "delivery"]),
                "deadline_days": rnd.choice([0, 7, 30]), "late_grace_days": rnd.choice([0, 2, 5]),
                "refund_percent": rnd.choice([0, 50, 100])}
        pol = {"clear": rnd.random() > 0.05, "day_type": dt, "preconditions": [], "seller_wait_hours": 0,
               "seller_types": "any", "excluded_payments": [], "category_exclusions": False, "excluded_causes": [],
               "rules": [rule] if rnd.random() > 0.1 else []}
        day = lambda: "2026-%02d-%02d" % (rnd.randint(8, 11), rnd.randint(1, 28))  # noqa: E731
        f = {"purchase_date": day(), "promised_date": day(), "delivered_date": rnd.choice([None, day()]),
             "claim_date": day(), "event": rule["event"], "seller_type": "any", "payment": "", "category_excluded": False,
             "contacted_seller": True, "hours_since_contact": 0, "seller_attempted": True, "delay_cause": "unknown",
             "refund_issued": False, "amount_cents": rnd.choice([100, 4990, 12345])}
        if f["event"] == "late" and not f["delivered_date"]:
            f["delivered_date"] = day()
        an = {"purchase": f["purchase_date"], "promised": f["promised_date"], "delivery": f["delivered_date"]}
        same += tuple(M._pol(pol, f["event"], an, f["claim_date"], f["amount_cents"])) == tuple(policy_v2.decide(pol, f))
    out.append(("policy_v2.decide (v2 structures)", same == n, n))
    proofs = [None, {"proof_kind": "label", "proof": "SM-S911B 128GB"}, {"proof_kind": "photo", "proof": "128 GB"},
              {"proof_kind": "serial_number", "proof": "256 GB"}]
    claims = [it["claim"] for it in C3["cases"]] + [NO_PROOF, PROOF]
    descs = [it["description"] for it in C3["cases"]] + [DESC]
    same = total = 0
    for _ in range(n):
        c, d = rnd.choice(claims), rnd.choice(descs)
        q1 = rnd.choice(["differs", "matches"])
        q2 = rnd.choice(["admits", "general_denial", "disputes_with_fact"])
        resp = rnd.choice(["", "We checked again.", "  "])
        q2r2 = rnd.choice(["admits", "general_denial", "disputes_with_fact"]) if resp.strip() else None
        x = rnd.choice(proofs)
        same += S._label(q1, q2, c, d, {"response": resp, "q2": q2r2, "proof": x}) == s3.label(q1, q2, c, d, resp, q2r2, x)
        same += S._ncr(q1, q2, c, d) == s3.needs_closing_round(q1, q2, c, d)
        same += S._pq("q2", d, c, resp, x) == s3.build_prompt("q2", d, c, resp, x)
        pr, rc = S._n(c["promised"]), S._n(c["received"])
        complete = bool(pr and rc and pr != rc and pr in S._n(d))
        same += complete == s3.claim_complete(c, d)
        total += 4
        if complete:
            cf = dict(c, **(x or {}))
            mine_c = cf["proof_kind"] in S.KINDS and rc in S._n(cf["proof"])
            same += mine_c == subjective.concrete_with_proof(cf, d)
            total += 1
    out.append(("label, closing, prompt q2, claim_complete, concrete_with_proof", same == total, total))
    accounts = [it["account"] for it in ND["cases"]] + ["", "x\r\ny", "ñ" * 2500]
    resps = [it["response"] for it in ND["cases"]] + ["", "  ", "a\rb"]
    same = 0
    for _ in range(n):
        a, r, st = rnd.choice(accounts), rnd.choice(resps), rnd.choice([None, "", "Nobody signed.", "á \r\n b"])
        same += S._pn(a, r, st) == nd.build_prompt(a, r, st)
    out.append(("not_delivered prompt", same == n, n))
    return out


def main():
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    rep = Report(out)
    rep.line("v2 judge contracts, local run")
    for kind, path in CONTRACTS.items():
        built = path.read_bytes()
        rep.line("%-10s %s, %d bytes, sha256 %s" % (kind, path.relative_to(ROOT).as_posix(), len(built),
                                                   hashlib.sha256(built).hexdigest()))
    rep.line("Demo Shop test terms: %s" % TERMS_HASH)
    rep.line("")
    stats = {"prompts_c": 0, "prompts_m": 0, "prompts_n": 0, "det_fail": 0, "formats": collections.Counter(),
             "unknown_c": [], "unknown_m": [], "unknown_n": [], "verdicts": []}
    wm, ws = World("mail"), World("subjective")
    run_c3(rep, stats)
    run_b3(rep, stats)
    run_nd(rep, stats)
    j0_c = (ws.c.prompt_hash() == s3.PROMPT_SHA256 + "|" + ND["prompt_sha256"] and s3.PROMPT_SHA256 == C3["prompt_sha256"]
            and not stats["unknown_c"] and not stats["unknown_n"])
    j0_m = (wm.c.prompt_hash() == mail_llm_v3.PROMPT_SHA256 and not stats["unknown_m"]
            and all(json.loads(l)["prompt_sha256"] == mail_llm_v3.PROMPT_SHA256
                    for l in B3_FILE.read_text(encoding="utf-8").splitlines()))
    fmt_ok = set(stats["formats"]) <= {"json"}
    rep.metric("J0", "prompts identical to the measured ones (C3, ND, B3)", int(j0_c and fmt_ok) + int(j0_m and fmt_ok), 2,
               "%d C3 prompts, %d ND, %d B3 in the measured list" % (stats["prompts_c"], stats["prompts_n"],
                                                                          stats["prompts_m"]))
    rep.rows_metric("J3", "claim flow in code: test_claim_flow 9, test_resolve_date 9, B0 23",
                    flow_tests() + resolve_date_tests(wm.module) + b0_tests())
    rep.rows_metric("J4", "email without a valid attestation: does not count, does not block; unreadable Lacre: error", lacre_rejections())
    rows, last = binding_tests()
    stats["verdicts"].append((last, None))
    rep.rows_metric("J5", "bound to the order, the claim and the chain; rejections", rows)
    rep.rows_metric("J5b", "one byte changed in the claim or a submission gives another hash and chain", hash_tests())
    rep.rows_metric("J6", "no majority: NO_CONSENSUS, sent again, never DENY", no_majority_tests())
    rep.rows_metric("J7", "once-only paths; submissions out of turn or from the wrong party do not count",
                    once_tests() + nd_procedure_tests())
    rep.metric("J8", "determinism: leader and validator with the same answer give the same result",
               int(stats["det_fail"] == 0), 1, "differences %d" % stats["det_fail"])
    bad, seen = 0, 0
    for v, st in stats["verdicts"]:
        if not v:
            continue
        seen += 1
        if v["outcome"] == "REFUND":
            bad += not 0 < v["refund_cents"] <= v["amount_cents"]
            if st and v["event"] == "late":
                bad += not st["emails"]
            if st and v["event"] == "not_as_described":
                bad += not (st["q1"] == "differs" or st["no_response"])
            if st and v["event"] == "not_delivered":
                bad += not (st["q2"] in ("admits", "general_denial", "disputes_with_fact") or st["no_response"])
    rep.metric("J9", "REFUND out of range, without an attested email (late) or without a majority", int(bad == 0), 1,
               "verdicts checked %d, violations %d" % (seen, bad))
    rep.rows_metric("J11", "an email presented by the store has no effect", merchant_mail_tests())
    rep.rows_metric("JX1", "unreadable claim: final INVALID_CLAIM; for the other contract: error", invalid_claim_tests())
    rep.rows_metric("JX2", "invented submissions open another branch and do not block the real one", griefing_tests())
    rep.rows_metric("JX3", "emails: the verdict lists every ignored submission with its code (I1 to I9)", ignored_list_tests())
    rep.rows_metric("JX4", "subjective: a frontend deduces ignored submissions with get_claim(chain)",
                    subjective_deduction_tests())
    eq = equivalence_tests(wm, ws)
    rep.line("compact copies = measured modules: %s" % "; ".join(
        "%s %s (%d)" % (name, "ok" if ok else "DIFFERENT", k) for name, ok, k in eq))
    if not all(ok for _, ok, _ in eq):
        rep.metrics["EQ"] = "FAIL"
    import re
    in_code = set()
    for src in ("judge_common.py", "judge_mail_template.py", "judge_subjective_template.py"):
        in_code |= set(re.findall(r'_f\("([CSMFL]\d+)', (ROOT / "contracts" / src).read_text(encoding="ascii")))
    rep.line("error codes: %d in the contracts, %d in contracts/ERRORS.md, undocumented %s, unused %s" % (
        len(in_code), len(CODES), sorted(in_code - set(CODES)) or "none", sorted(set(CODES) - in_code) or "none"))
    if in_code - set(CODES):
        rep.metrics["CODES"] = "FAIL"
    extra = against_merchant_tests()
    rep.line("info  rule only against the store (no threshold): %s" % "; ".join(
        "%s: %s" % (n, "ok" if ok else "WRONG %s" % (d,)) for n, ok, d in extra))
    rep.line("")
    failed = [k for k, s in rep.metrics.items() if s != "PASS"]
    rep.line("criterion: %s" % ("FAIL (%s)" % ", ".join(failed) if failed else "PASS"))
    rep.save()
    return not failed


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
