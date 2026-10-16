# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
# Refund arbiter, judge contract v2 for late claims: signed store emails that the buyer presents,
# attested by Lacre. Contains code from Lacre (github.com/eudomar500/lacre), Copyright (c) 2026
# Insidr Labs, MIT License: permission is granted, free of charge, to deal in the software without
# restriction, provided this notice is included; the software is provided "as is", without
# warranty of any kind.

from genlayer import *
from genlayer.py.public_abi import StorageType
import base64
import datetime
import hashlib
import json
import re

# <<CONST>>

# <<COMMON>>

# <<EACH-BEGIN>>
        v["ignored"] = ig = []
        for r in rs:
            # A registered submission never stops the claim: one the judge cannot use is ignored,
            # and the verdict lists it with the code of why (contracts/ERRORS.md, I1 to I9).
            x = _canon(r)
            if not (isinstance(x, dict) and set(x) == {"party", "kind", "content"}):
                w = "I1"
            elif (x["party"], x["kind"]) not in ok:
                w = "I2"
            else:
                w = ap(ct, st, c, m, x["kind"], x["content"])
            if w:
                ig.append([_h(r), w])
# <<EACH-END>>

# Compact copies of arbiter/mail_llm_v3.py (prompts from the module, inserted by the builder),
# mail_llm_v2.canonical and resolve_date, mail_v1.extract and Lacre's dkimbody.body_hash_b64.
PR = {q: r + "\nBEGIN-<<TAG>>-EMAIL\n<<EMAIL>>\nEND-<<TAG>>-EMAIL\n\n" + r for q, r in (("type", H + QT), ("date", H + QD))}
PH = hashlib.sha256("\x00".join(PR[k] for k in sorted(PR)).encode()).hexdigest()
FOLD = str.maketrans("\xe1\xe9\xed\xf3\xfa\xfc\xf1", "aeiouun")
WSP = re.compile(rb"[ \t]+")


def _pm(q, text):
    t = text.replace("\r\n", "\n").replace("\r", "\n")[:4000]
    return PR[q].replace("<<TAG>>", hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]).replace(
        "<<EMAIL>>", json.dumps(t, ensure_ascii=True))


def _ct(raw):
    r = _js(raw)
    return r["verdict"] if r is not None and set(r) == {"verdict"} and r["verdict"] in TYPES else None


def _cd(raw):
    r = _js(raw)
    if r is None or set(r) != {"month", "day", "year"}:
        return None
    out = []
    for k, lo, hi in (("month", 1, 12), ("day", 1, 31), ("year", 1000, 9999)):
        v = r[k]
        if v is None:
            out.append("")
        elif isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            return None
        else:
            out.append(str(v))
    return "|".join(out)


def _rd(parts, text, od):
    if not parts:
        return ""
    mo, dy, yr = [int(p) if p else None for p in parts.split("|")]
    w = re.findall(r"[a-z]+|\d+", text.lower().translate(FOLD))
    nums = {int(x) for x in w if x.isdigit()}
    if mo is None or dy is None or dy not in nums:
        return ""
    if mo not in nums and not any(n in w for n in MONTHS[mo]):
        return ""
    if yr is not None and yr not in nums:
        yr = None
    st = datetime.date.fromisoformat(od)
    if yr is None:
        for y in (st.year, st.year + 1):
            try:
                c = datetime.date(y, mo, dy)
            except ValueError:
                continue
            if c >= st:
                yr = y
                break
        if yr is None:
            return ""
    try:
        d = datetime.date(yr, mo, dy)
    except ValueError:
        return ""
    nm = [i for i, ns in enumerate(WEEKDAYS) if any(n in w for n in ns)]
    if nm and d.weekday() not in nm:
        return ""
    if not st <= d <= st + datetime.timedelta(days=120):
        return ""
    return d.isoformat()


def _bh(b, canon):
    if canon == "simple":
        if b and not b.endswith(b"\r\n"):
            b += b"\r\n"
        while b.endswith(b"\r\n\r\n"):
            b = b[:-2]
        b = b or b"\r\n"
    elif canon == "relaxed":
        ls = [WSP.sub(b" ", x).rstrip(b" ") for x in b.split(b"\r\n")]
        while ls and not ls[-1]:
            ls.pop()
        b = b"\r\n".join(ls) + b"\r\n" if ls else b""
    else:
        raise ValueError("canon")
    return base64.b64encode(hashlib.sha256(b).digest()).decode("ascii")


def _fin(a):
    return gl.get_contract_at(a).view(state=StorageType.LATEST_FINAL)


def _res(r, name):
    f = str(_fin(r).resolve(name))
    return Address(f) if f else None


def _decm(st, c, pol):
    # A store email counts only when the buyer presents it, and only against the store.
    es = sorted(st["emails"], key=lambda e: e["signed_at"])
    pr = next((e["date"] for e in es if e["type"] in ("order_confirmed", "shipped") and e["date"]), "")
    dl = next((e["date"] for e in es if e["type"] == "delivered" and e["date"]), "")
    if not (pr and dl):
        return "wait", "NOT_YET", 0, "signed emails required"
    out, amt = _pol(pol, "late", {"purchase": _d(c["paid_at"]), "promised": pr, "delivery": dl}, _d(c["claimed_at"]),
                    c["amount_cents"])
    return "decide", out, amt, "per policy"


def _apm(ct, st, c, m, k, v):
    r = ct._mail(v, c, m, [e["key"] for e in st["emails"]])
    if isinstance(r, str):
        return r
    st["emails"].append(r)
    ct.used[r["key"]] = c["order_ref"]


class Contract(gl.Contract):
    own: Address
    rtr: Address
    mer: TreeMap[str, str]
    cl: TreeMap[str, str]
    vd: TreeMap[str, str]
    # signed values of a message (domain|selector|bh|signed_at) -> order ref that used it
    used: TreeMap[str, str]

    def __init__(self, router: str):
        self.own = gl.message.sender_address
        self.rtr = Address(str(router))

    @gl.public.write
    def set_merchant(self, merchant: str, terms: str) -> str:
        if gl.message.sender_address != self.own:
            _f("M1")
        k = _addr(merchant)
        self.mer[k] = _terms(terms)
        return k

    @gl.public.write
    def judge(self, claim: str, step: str) -> str:
        return _run(self, claim, step, {"late": ()}, lambda c: True, {"emails": []}, {("buyer", "evidence")}, _apm,
                    _decm)

    def _mail(self, e, c, m, seen):
        """A reading of one email the buyer registered, or the code of why it cannot count
        (contracts/ERRORS.md, I3 to I9). Only an unreadable Lacre is an error."""
        if not isinstance(e, dict) or set(e) != {"record_id", "body_b64"}:
            return "I4"
        rid = str(e["record_id"]).strip()
        try:
            ver = _res(self.rtr, "verifier")
            rec = dict(_fin(ver).get(rid))
            ok = bool(rec) and _fin(ver).check_for(rid, m["domain"], 1024, str(rec.get("requester", ""))) is True
            ks = dict(_fin(_res(self.rtr, "keycache")).key_status(rec.get("domain", ""), rec.get("selector", "")))
        except Exception:
            _f("L2")
        key = "|".join(str(rec.get(f, "")) for f in ("domain", "selector", "bh", "signed_at"))
        if not ok:
            return "I5"
        if ks.get("state") != "active":
            return "I6"
        if key in seen:
            return "I3"
        if self.used.get(key, c["order_ref"]) != c["order_ref"]:
            return "I8"
        try:
            b = base64.b64decode(str(e["body_b64"]), validate=True)
            ok = len(b) <= 32768 and _bh(b, rec.get("body_canon", "")) == rec.get("bh")
        except Exception:
            ok = False
        if not ok:
            return "I7"
        text = b.decode("utf-8", "replace")
        p = m["profile"]
        if sorted(set(re.findall(p["order_pattern"], text))) != [c["order_number"]]:
            return "I8"
        paid = _d(c["paid_at"])
        if datetime.datetime.fromtimestamp(int(rec["signed_at"]), datetime.timezone.utc).date().isoformat() < paid:
            return "I9"  # signed before the order: not about it (as in B2)
        fixed = re.findall(p["date_pattern"], text)
        r = {"key": key, "record": ver.as_hex.lower() + "/" + rid, "signed_at": int(rec["signed_at"]),
             "type": _ask(_pm("type", text), _ct), "date": ""}
        if r["type"] in DATE_TYPES and not fixed:
            r["date"] = _ask(_pm("date", text), lambda raw: (lambda q: None if q is None else _rd(q, text, paid))(_cd(raw)))
        elif fixed:
            r["date"] = fixed[0]
        return r

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
        return PH

    @gl.public.view
    def owner(self) -> str:
        return self.own.as_hex

    @gl.public.view
    def router(self) -> str:
        return self.rtr.as_hex
