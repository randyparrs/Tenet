# Common part of the two v2 judge contracts. Not a contract: contracts/build_judge_v2.py inserts it
# into each template in place of # <<COMMON>>. Compact version: the same logic as arbiter/
# (policy_v2.decide for the structures v2 accepts, mail_v1.order_ref) without dead code;
# tests/judge_v2_stub_run.py compares it with the measured modules.

CV = "claim-v1"
CK = ("v", "order_ref", "order_number", "buyer", "merchant", "amount_cents", "paid_at", "claimed_at",
      "terms_hash", "event")
NUM = ("amount_cents", "paid_at", "claimed_at")
UNR = "unreadable"


class _NR(Exception):
    pass


def _f(m):
    raise gl.vm.UserError("[EXPECTED] " + m)


def _cj(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _h(t):
    return "0x" + hashlib.sha256(t.encode("utf-8")).hexdigest()


def _t(s):
    s = str(s).strip()
    d = datetime.datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    if d.tzinfo is None:
        raise ValueError("tz")
    return d.astimezone(datetime.timezone.utc)


def _days(a, b, dt):
    # policy_v2._days: b - a, calendar or business days.
    x, y = datetime.date.fromisoformat(a), datetime.date.fromisoformat(b)
    if dt == "calendar":
        return (y - x).days
    s, n, d = (1, 0, x) if y >= x else (-1, 0, y)
    e = y if y >= x else x
    while d < e:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return s * n


def _pol(p, ev, an, cd, amt):
    # policy_v2.decide for the structures v2 accepts (no preconditions, exclusions or seller types).
    if not p.get("clear"):
        return "NO_DECISION", 0
    r = next((x for x in p["rules"] if x["event"] == ev), None)
    if r is None:
        return "DENY", 0
    dt = p["day_type"]
    if r["deadline_days"]:
        s = an.get(r["deadline_from"])
        if s and _days(s, cd, dt) > r["deadline_days"]:
            return "DENY", 0
    if ev == "late":
        dl = an.get("delivery")
        if not dl or _days(an["promised"], dl, dt) <= r["late_grace_days"]:
            return "DENY", 0
    if r["wait_days"]:
        s = an.get(r["wait_from"])
        if not s or _days(s, cd, dt) < r["wait_days"]:
            return "NOT_YET", 0
    return "REFUND", amt * r["refund_percent"] // 100


def _ask(prompt, read):
    """One closed question under strict_eq; a reading no majority can use raises _NR."""
    def run() -> str:
        try:
            raw = gl.nondet.exec_prompt(prompt, response_format="json")
        except Exception:
            return UNR
        try:
            v = read(raw)
        except Exception:
            v = None
        return UNR if v is None else str(v)
    a = str(gl.eq_principle.strict_eq(run))
    if a == UNR:
        raise _NR()
    return a


def _js(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    return raw if isinstance(raw, dict) else None


class _Bad(Exception):
    pass


EV = ("late", "not_as_described", "not_delivered")


def _nodup(ps):
    d = {}
    for k, v in ps:
        if k in d:
            raise _Bad()
        d[k] = v
    return d


def _canon(t):
    """The parsed JSON when t is canonical (sorted keys, no spaces, ASCII, no repeated key), else None."""
    try:
        x = json.loads(t, object_pairs_hook=_nodup)
        return x if _cj(x) == t else None
    except Exception:
        return None


def _d(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()


def _pos(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _claim(t, kinds):
    """The claim the buyer opened in the escrow. One the judge cannot read raises _Bad (INVALID_CLAIM);
    one for the other judge contract is an error, so it can be sent there."""
    c = _canon(t)
    if not isinstance(c, dict) or c.get("v") != CV or c.get("event") not in EV:
        raise _Bad()
    if c["event"] not in kinds:
        _f("C3")
    keys = CK + kinds[c["event"]]
    ok = (set(c) == set(keys) and all(_pos(c[k]) for k in NUM)
          and all(isinstance(c[k], str) for k in keys if k not in NUM)
          and c["paid_at"] <= c["claimed_at"] and c["order_ref"] == _h(c["order_number"]))
    try:
        for k in ("delivered_date", "promised_date"):
            if ok and c.get(k):
                datetime.date.fromisoformat(c[k])
    except Exception:
        ok = False
    if not ok:
        raise _Bad()
    c["merchant"] = c["merchant"].lower()
    return c


def _fold(cur, raw):
    # The escrow's chain: sha256(chain || sha256(submission)).
    return "0x" + hashlib.sha256(bytes.fromhex(cur[2:]) + bytes.fromhex(_h(raw)[2:])).hexdigest()


def _run(ct, claim, step, ks, gd, em, ok, ap, de):
    """One judge step on the chain the escrow keeps. State and verdicts are keyed by chain, so a
    submission that was never registered in the escrow opens a branch the escrow never accepts."""
    now = _t(gl.message_raw["datetime"]).isoformat()
    try:
        s = json.loads(str(step))
        p0, rs = s["chain"].lower(), s["submissions"]
        bytes.fromhex(p0[2:])
        if (set(s) != {"chain", "submissions"} or len(p0) != 66 or not isinstance(rs, list) or len(rs) > 8
                or not all(isinstance(r, str) for r in rs)):
            raise ValueError()
    except Exception:
        _f("S1")
    t = str(claim)
    h = _h(t)
    cur = p0
    for r in rs:
        cur = _fold(cur, r)
    try:
        c = _claim(t, ks)
        if not gd(c):
            raise _Bad()
    except _Bad:
        ct.vd[cur] = _cj({"claim_hash": h, "chain": cur, "outcome": "INVALID_CLAIM", "refund_cents": 0,
                          "reason": "invalid claim", "action": "decide", "final": True, "judged_at": now})
        return "INVALID_CLAIM"
    m = json.loads(ct.mer.get(c["merchant"], "") or "null")
    if not m:
        _f("M4")
    if c["terms_hash"] != m["terms_hash"]:
        _f("M5")
    hd = ct.cl.get(p0, "")
    if hd:
        st = json.loads(hd)
    elif p0 == "0x" + hashlib.sha256(bytes.fromhex(h[2:])).hexdigest():
        st = dict(em, claim_hash=h, steps=0, final=False)
    else:
        _f("S2")
    if st["claim_hash"] != h:
        _f("S2")
    if st["final"]:
        _f("F2")
    if cur != p0 and ct.cl.get(cur, ""):
        return json.loads(ct.vd[cur])["outcome"]
    v = {"order_ref": c["order_ref"], "claim_hash": h, "chain": cur, "buyer": c["buyer"].lower(),
         "merchant": c["merchant"], "amount_cents": c["amount_cents"], "terms_hash": c["terms_hash"],
         "event": c["event"], "step": st["steps"] + 1, "judged_at": now}
    try:
        # <<EACH>> (each template brings its own loop over the submissions; see build_judge_v2.py)
        act, out, amt, why = de(st, c, m["structure"])
    except _NR:
        v.update({"outcome": "NO_CONSENSUS", "refund_cents": 0, "reason": "no majority reading", "action": "resend",
                  "final": False})
        ct.vd[cur] = _cj(v)
        return "NO_CONSENSUS"
    if out == "REFUND" and not 0 < amt <= c["amount_cents"]:
        _f("F7")
    st["steps"] += 1
    st["final"] = out in ("REFUND", "DENY")
    v.update({"outcome": out, "refund_cents": amt if out == "REFUND" else 0, "reason": why, "action": act,
              "final": st["final"]})
    ct.cl[cur] = _cj(st)
    ct.vd[cur] = _cj(v)
    return out


def _terms(text):
    """D1: the owner loads the confirmed structure; v2 only takes what it can judge."""
    try:
        t = json.loads(str(text))
        s, p = t["structure"], t["profile"]
        ok = (s["preconditions"] == [] and s["seller_types"] == "any" and s["excluded_payments"] == []
              and s["category_exclusions"] is False and s["excluded_causes"] == []
              and isinstance(s["rules"], list) and isinstance(t["terms_hash"], str)
              and all(isinstance(p[k], str) for k in ("order_pattern", "date_pattern")))
    except Exception:
        ok = False
    if not ok:
        _f("M3")
    return _cj({"domain": str(t["domain"]).strip().lower(), "structure": s, "profile": p,
                "terms_hash": t["terms_hash"]})


def _k(x):
    return str(x).strip().lower()


def _addr(m):
    k = _k(m)
    try:
        Address(k)
    except Exception:
        _f("M2")
    return k


