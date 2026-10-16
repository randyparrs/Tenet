"""Store emails, code part: verifies the DKIM signature and the body, and reads, with the patterns
the store declares, the order number, the amounts and the dates in a fixed format. No LLM. What has
no fixed format (the email type and a date written in words) is answered by the committee
(arbiter/mail_llm.py).

Uses lacre_vendor/dkimcore.py and dkimbody.py (copied unchanged from github.com/eudomar500/lacre,
MIT, Copyright (c) 2026 Insidr Labs). Alignment follows Lacre's Verifier
(contracts/verifier/verifier.py: from_domain and the domain comparison). Standard library only.
"""
import hashlib
import re

from lacre_vendor import dkimbody, dkimcore


def split_message(raw):
    """(header block, body) split at the first empty line; CRLF as on the wire."""
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        raise ValueError("no blank line between headers and body")
    return head + b"\r\n", body


def from_domain(value):
    text = re.sub(r'"(?:[^"\\]|\\.)*"', "", value.decode("latin-1"))
    addr = text.rpartition("<")[2].partition(">")[0] if "<" in text else text
    if "@" not in addr or text.count("@") > 1 or text.count("<") > 1:
        return ""
    return addr.rpartition("@")[2].strip().lower().strip(".")


def verify(raw, keys):
    """keys: {(domain, selector): (n, e)} as Lacre's KeyCache gives them for active keys."""
    head, body = split_message(raw)
    fields = dkimcore.parse_headers(head)
    index, tags = dkimcore.find_signature(fields)
    out = {"valid": False, "aligned": False, "body_ok": False, "domain": tags.get("d", "").lower(),
           "selector": tags.get("s", "").lower(), "signed_at": int(tags.get("t", "0") or 0), "reason": ""}
    key = keys.get((out["domain"], out["selector"]))
    if index < 0:
        out["reason"] = "no DKIM-Signature header"
        return out
    if key is None:
        out["reason"] = "no key for selector"
        return out
    names = [n.strip().lower() for n in tags.get("h", "").split(":") if n.strip()]
    ok, info = dkimcore.verify_headers(head, *key)
    out["valid"] = ok and "from" in names
    froms = [v for n, v in fields if dkimcore.field_name(n) == b"from"]
    sender = from_domain(froms[0]) if len(froms) == 1 else ""
    signer = out["domain"]
    out["aligned"] = out["valid"] and sender != "" and (
        sender == signer or sender.endswith("." + signer) or signer.endswith("." + sender))
    body_canon = tags.get("c", "simple/simple").partition("/")[2].strip().lower() or "simple"
    out["body_ok"] = out["valid"] and dkimbody.body_hash_b64(body, body_canon) == dkimcore.unfold(tags.get("bh", ""))
    out["body"] = body
    out["reason"] = info["reason"] if not ok else ""
    return out


def extract(body, profile):
    text = body.decode("utf-8", "replace")
    return {"orders": sorted(set(re.findall(profile["order_pattern"], text))),
            "amounts": re.findall(profile["amount_pattern"], text),
            "fixed_dates": re.findall(profile["date_pattern"], text),
            "text": text}


def order_ref(order_number):
    """Hash of the order number: what is stored and compared, never the number itself."""
    return "0x" + hashlib.sha256(order_number.encode("utf-8")).hexdigest()


def check(raw, keys, profile, claim_order):
    """Everything the code decides about an email presented for the order claim_order."""
    v = verify(raw, keys)
    result = {k: v[k] for k in ("valid", "aligned", "body_ok", "domain", "selector", "signed_at")}
    result.update({"orders": [], "amounts": [], "fixed_dates": [], "usable": False, "reason": v["reason"]})
    if not v["valid"]:
        result["reason"] = result["reason"] or "signature not valid"
        return result
    if not v["body_ok"]:
        result["reason"] = "body hash mismatch"
        return result
    x = extract(v["body"], profile)
    result.update({"orders": x["orders"], "amounts": x["amounts"], "fixed_dates": x["fixed_dates"]})
    if not v["aligned"] or v["domain"] != profile["domain"]:
        result["reason"] = "from not aligned"
    elif len(x["orders"]) != 1:
        result["reason"] = "not exactly one order number"
    elif order_ref(x["orders"][0]) != order_ref(claim_order):
        result["reason"] = "order mismatch"
    else:
        result["usable"], result["reason"] = True, ""
    return result
