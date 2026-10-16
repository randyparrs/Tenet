# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
# Refund arbiter judge v2: not_as_described, not_delivered. Prompt layout after Lacre's llmfields (MIT).

from genlayer import *
import datetime
import hashlib
import json

# <<CONST>>

# <<COMMON>>

# <<EACH-BEGIN>>
        for r in rs:
            # A registered submission never stops the claim: one the judge cannot use is ignored.
            x = _canon(r)
            if isinstance(x, dict) and set(x) == {"party", "kind", "content"} and (x["party"], x["kind"]) in ok:
                ap(ct, st, c, m, x["kind"], x["content"])
# <<EACH-END>>

# Compact copies of arbiter/subjective_v3.py, subjective.concrete_with_proof and arbiter/not_delivered.py
# (prompts from the modules, inserted by the builder), with claim_flow's procedure in _step.
N2, N3, NN = ("DESCRIPTION", "CLAIM"), ("DESCRIPTION", "CLAIM", "RESPONSE"), ("CLAIM", "RESPONSE")
CF = ("account", "promised", "received", "proof_kind", "proof")
SK = {"not_as_described": ("description",) + CF + ("delivered_date",), "not_delivered": ("account", "promised_date")}
M, B, E = "merchant", "buyer", "escrow"
OKS = {(M, "response"), (M, "closing_response"), (B, "closing_proof"), (B, "closing_statement"), (B, "proof"),
       (E, "no_response"), (E, "closing_open"), (E, "closing_timeout")}
EMPTY = {"q1": None, "q2": None, "no_response": False, "closing": None, "proof_req": False, "proof": None}
V3 = ("admits", "disputes_with_fact", "general_denial")
AW = ("wait", "NOT_YET", 0, "awaiting store response")
NP = ("decide", "DENY", 0, "claim not proven")


def _cf(c):
    return {k: c.get(k) for k in CF}


def _pp(r, ns):
    return r + "".join("\nBEGIN-<<TAG>>-%s\n<<%s>>\nEND-<<TAG>>-%s\n" % (n, n, n) for n in ns) + "\n" + r


Q = {"q1": (_pp(H + T1, N2), N2, ("differs", "matches")), "q2": (_pp(H + T2, N3), N3, V3), "nd": (_pp(NH + NT, NN), NN, V3)}
PH = hashlib.sha256("\x00".join(Q[q][0] for q in ("q1", "q2")).encode()).hexdigest()
PN = hashlib.sha256(Q["nd"][0].encode()).hexdigest()


def _cl(t):
    return str(t or "").replace("\r\n", "\n").replace("\r", "\n")[:2000]


def _txt(c, x=None):
    t = ("Buyer's account: %s\n\nFields (summary):\nPromised (quoted from the description): %s\n"
         "Received: %s\nProof (%s): %s" % (c.get("account", "") or "none", c.get("promised", ""), c.get("received", ""),
                                          c.get("proof_kind", "") or "none", c.get("proof", "") or "none"))
    if x:
        t += "\nAdditional proof added in the second round (%s): %s" % (x.get("proof_kind", "") or "none",
                                                                        x.get("proof", "") or "none")
    return t


def _fill(q, ts):
    p, ns, _ = Q[q]
    p = p.replace("<<TAG>>", hashlib.sha256("\x00".join(ts[n] for n in ns).encode("utf-8")).hexdigest()[:16])
    for n in ns:
        p = p.replace("<<%s>>" % n, json.dumps(ts[n], ensure_ascii=True))
    return p


def _pq(q, desc, c, resp="", x=None):
    return _fill(q, {"DESCRIPTION": _cl(desc), "CLAIM": _cl(_txt(c, x)), "RESPONSE": _cl(resp)})


def _pn(acc, resp, s=None):
    # not_delivered.build_prompt
    t = "Buyer's account: %s" % (acc or "none")
    if s:
        t += "\nBuyer's additional statement in the second round: %s" % s
    return _fill("nd", {"CLAIM": _cl(t), "RESPONSE": _cl(resp)})


def _aq(q, p):
    def rd(raw):
        r = _js(raw)
        return r["verdict"] if r is not None and set(r) == {"verdict"} and r["verdict"] in Q[q][2] else None
    return _ask(p, rd)


def _n(t):
    return "".join(str(t or "").lower().split())


def _wf(c):
    r, p = _n(c.get("received")), _n(c.get("proof"))
    return c.get("proof_kind") in KINDS and bool(p) and bool(r) and r in p


def _ind(c, desc):
    p = _n(c.get("proof"))
    return c.get("proof_kind") in KINDS and bool(p) and p in _n(desc)


def _ncr(q1, q2, c, desc):
    return q1 == "differs" and q2 == "disputes_with_fact" and not _ind(c, desc)


def _base(c, x):
    return "differs_material" if _wf(c) or bool(x and _wf(dict(c, **x))) else "insufficient"


def _label(q1, q2, c, desc, cl=None):
    # subjective_v3.label
    if q1 == "matches":
        return "matches"
    if q2 == "admits":
        return "differs_material"
    if q2 == "general_denial":
        return "differs_material" if _wf(c) else "insufficient"
    if _ind(c, desc):
        return "matches"
    if not str(cl["response"] or "").strip():
        return _base(c, cl["proof"])
    if cl["q2"] == "disputes_with_fact":
        return "not_proven"
    if cl["q2"] == "admits":
        return "differs_material"
    return _base(c, cl["proof"])


def _proof(p):
    return isinstance(p, dict) and set(p) == {"proof_kind", "proof"} and all(isinstance(v, str) for v in p.values())


def _need(st, c, nd):
    # Is a closing round due? (a fact disputed; for not_as_described, not settled by the description)
    if nd:
        return st["q2"] == "disputes_with_fact"
    return st["q1"] is not None and _ncr(st["q1"], st["q2"], _cf(c), c["description"])


def _ap(ct, st, c, m, k, v):
    """One registered submission, applied with claim_flow's rules. Deadlines were applied by the
    escrow when it registered them; a submission out of turn is ignored."""
    nd = c["event"] == "not_delivered"
    desc, cf = c.get("description"), _cf(c)
    judged = st["q2" if nd else "q1"] is not None or st["no_response"]
    if k == "response":
        if judged:
            return
        if not (isinstance(v, str) and v.strip()):
            st["no_response"] = True  # an empty answer is no answer
        elif nd:
            st["q2"] = _aq("nd", _pn(c["account"], v))
        else:
            st["q1"] = _aq("q1", _pq("q1", desc, cf))
            if st["q1"] == "differs":
                st["q2"] = _aq("q2", _pq("q2", desc, cf, v))
    elif k == "no_response":
        if not judged:
            st["no_response"] = True
    elif k == "closing_open":
        if not st["no_response"] and st["closing"] is None and _need(st, c, nd):
            st["closing"] = {"response": "", "q2": None, "proof": None, "r": False, "b": False, "done": False}
    elif k == "proof":
        if st["proof_req"] and not st["proof"] and _proof(v):
            st["proof"] = v
    else:
        cl = st["closing"]
        if not cl or cl["done"]:
            return
        if k == "closing_response":
            cl["r"] = True
            cl["response"] = v if isinstance(v, str) else ""
        elif k != "closing_timeout":
            cl["b"] = True
            cl["proof"] = v if (isinstance(v, str) if nd else _proof(v)) else None
        if k == "closing_timeout" or cl["r"] and cl["b"]:
            cl["done"] = True
            r, x = cl["response"], cl["proof"]
            if r.strip():
                cl["q2"] = _aq("nd", _pn(c["account"], r, x)) if nd else _aq("q2", _pq("q2", desc, cf, r, x))


def _closing(st, c, nd):
    """None when the round is decided; else the step to wait for."""
    if not _need(st, c, nd):
        return None
    cl = st["closing"]
    if cl is None:
        return "open_closing_round", "NOT_YET", 0, "closing round"
    if not cl["done"]:
        return "wait", "NOT_YET", 0, "closing round open"
    return None


def _dec(st, c, pol):
    nd = c["event"] == "not_delivered"
    pd, cd = _d(c["paid_at"]), _d(c["claimed_at"])
    if nd:
        if not st["no_response"]:
            if st["q2"] is None:
                return AW
            w = _closing(st, c, nd)
            if w:
                return w
            cl = st["closing"]
            if cl and cl["response"].strip() and cl["q2"] == "disputes_with_fact":
                return NP
        out, amt = _pol(pol, "not_delivered", {"purchase": pd, "promised": c["promised_date"] or None}, cd,
                        c["amount_cents"])
        return "decide", out, amt, "per policy"
    desc, cf = c["description"], _cf(c)
    if st["proof"]:
        cf.update(st["proof"])
    if st["no_response"]:
        lab = ("differs_material" if cf["proof_kind"] in KINDS and _n(c["received"]) in _n(cf["proof"])
               else "insufficient")
    elif st["q1"] is None:
        return AW
    else:
        w = _closing(st, c, nd)
        if w:
            return w
        cl = st["closing"] if st["closing"] and st["closing"]["done"] else {"response": "", "proof": None, "q2": None}
        lab = _label(st["q1"], st["q2"], cf, desc, cl)
    if lab == "insufficient":
        if not st["proof_req"]:
            st["proof_req"] = True
            return "request_proof", "NOT_YET", 0, "proof required"
        if st["proof"]:
            return NP
        return "wait", "NOT_YET", 0, "proof required"
    if lab == "matches":
        return "decide", "DENY", 0, "item as described"
    if lab == "not_proven":
        return NP
    out, amt = _pol(pol, "not_as_described", {"purchase": pd, "delivery": c["delivered_date"] or None}, cd,
                    c["amount_cents"])
    return "decide", out, amt, "per policy"


def _good(c):
    # An incomplete claim cannot be completed (its content is fixed by its hash): INVALID_CLAIM,
    # which frees the order so the buyer can open a complete one in time.
    if c["event"] == "not_delivered":
        return bool(c["account"].strip())
    pr, rc = _n(c["promised"]), _n(c["received"])
    return bool(pr and rc and pr != rc and pr in _n(c["description"]))


class Contract(gl.Contract):
    own: Address
    mer: TreeMap[str, str]
    cl: TreeMap[str, str]
    vd: TreeMap[str, str]

    def __init__(self):
        self.own = gl.message.sender_address

    @gl.public.write
    def set_merchant(self, merchant: str, terms: str) -> str:
        if gl.message.sender_address != self.own:
            _f("M1")
        k = _addr(merchant)
        self.mer[k] = _terms(terms)
        return k

    @gl.public.write
    def judge(self, claim: str, step: str) -> str:
        return _run(self, claim, step, SK, _good, EMPTY, OKS, _ap, _dec)

    @gl.public.view
    def get_verdict(self, chain: str) -> str:
        return self.vd.get(_k(chain), "")

    @gl.public.view
    def get_claim(self, chain: str) -> str:
        return self.cl.get(_k(chain), "")

    @gl.public.view
    def get_merchant(self, merchant: str) -> str:
        return self.mer.get(_k(merchant), "")

    @gl.public.view
    def prompt_hash(self) -> str:
        return PH + "|" + PN

    @gl.public.view
    def owner(self) -> str:
        return self.own.as_hex
