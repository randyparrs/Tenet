"""Refund terms the buyer sees and accepts when paying, rendered from the store's confirmed
structure (schema v2), no LLM. Same text for the same structure and hold; its SHA-256 is the hash the
order keeps in the escrow.

Includes the procedure rules (72 hours without an answer from the store, 7 days for requested proof,
and the closing round). Standard library only.
"""
import hashlib

import subjective
import subjective_v3

TERMS_VERSION = "terms-v1"

_EVENT = {
    "not_delivered": "If the order never arrives",
    "late": "If the order arrives more than {grace} {unit} after the promised delivery date",
    "not_as_described": "If the item arrives damaged, defective, wrong or different from its description",
    "cancelled": "If the order is cancelled",
    "out_of_stock": "If the item is out of stock",
}
_ANCHOR = {"purchase": "the purchase date", "promised": "the promised delivery date", "delivery": "the delivery date"}
_PAYMENT = {"cash": "cash", "off_platform": "payment outside the platform", "qr": "QR code"}
_CAUSE = {"buyer_absent": "the recipient not being available", "buyer_address": "a wrong or incomplete address given by the buyer",
          "customs": "customs", "force_majeure": "events beyond the store's control", "weather": "weather"}


def _days(n, day_type):
    word = "business day" if day_type == "business" else "day"
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def render(structure, hold_days, windows=None):
    """Text of the terms. structure: policy_v2.structure(...) confirmed by the store.

    windows: the escrow's answer and proof windows as text, for an escrow built with other windows
    (the demo escrow: {"response": "5 minutes", "proof": "5 minutes"}). None = 72 hours and 7 days.
    """
    w = windows or {"response": "%d hours" % subjective.RESPONSE_WINDOW_HOURS,
                    "proof": "%d days" % (subjective_v3.PROOF_WINDOW_HOURS // 24)}
    lines = ["Refund terms (%s)" % TERMS_VERSION, ""]
    if not structure.get("clear"):
        lines.append("This store does not promise a fixed refund. The escrow does not hold this payment for claims.")
        return "\n".join(lines) + "\n"
    dt = structure["day_type"]
    lines.append("What is covered:")
    for r in structure["rules"]:
        unit = "business days" if dt == "business" else "days"
        s = _EVENT[r["event"]].format(grace=r["late_grace_days"], unit=unit)
        s += ", you get a refund of %d%% of the order total." % r["refund_percent"]
        if r["wait_days"]:
            s += " You can claim from %s after %s." % (_days(r["wait_days"], dt), _ANCHOR[r["wait_from"]])
        if r["deadline_days"]:
            s += " You must claim within %s of %s." % (_days(r["deadline_days"], dt), _ANCHOR[r["deadline_from"]])
        else:
            s += " There is no deadline to claim."
        lines.append("- " + s)
    lines += ["", "Conditions:"]
    cond = []
    if "contact_seller" in structure["preconditions"]:
        wait = structure["seller_wait_hours"]
        cond.append("You must contact the store first" + (" and wait %d hours for an answer." % wait if wait else "."))
    if "seller_attempt_resolution" in structure["preconditions"]:
        cond.append("The store gets a chance to resolve the problem first.")
    if structure["seller_types"] == "third_party":
        cond.append("These terms apply only to items sold by third-party sellers.")
    elif structure["seller_types"] == "first_party":
        cond.append("These terms apply only to items sold by the store itself.")
    if structure["excluded_payments"]:
        cond.append("Payments made by %s are not covered." % _join(_PAYMENT[p] for p in structure["excluded_payments"]))
    if structure["category_exclusions"]:
        cond.append("Some product categories are excluded.")
    if structure["excluded_causes"]:
        cond.append("Delays caused by %s are not covered." % _join(_CAUSE[c] for c in structure["excluded_causes"]))
    cond.append("Days are counted as %s." % ("business days" if dt == "business" else "calendar days"))
    lines += ["- " + c for c in cond]
    lines += [
        "",
        "How a claim is decided:",
        "- The payment is held in escrow for %d days. A claim opened within that time freezes the payment until it is decided; a claim opened later is outside the escrow." % hold_days,
        "- A claim that the item is different from its description names what the description promised, what arrived, and, as proof, a label, a model number or a serial number that shows what arrived.",
        "- If the store does not answer a claim within %s, the claim is decided without its answer: a claim with that proof is refunded under these terms." % w["response"],
        "- If a claim needs proof, the buyer is asked once and has %s to provide it. Without that proof, the claim is denied: %s." % (w["proof"], subjective_v3.PROOF_NOT_PROVIDED_REASON),
        "- If the store disputes the claim with a specific fact, each side may add one more piece of proof, once. If the store then disputes it again with a fact, the claim is denied: %s. If the store admits it, the claim is refunded. If the store only denies it in general or does not answer, the claim is refunded when the buyer's proof is well formed." % subjective_v3.NOT_PROVEN_REASON,
        "- A claim with no agreement among the reviewers is not a denial and can be submitted again.",
    ]
    return "\n".join(lines) + "\n"


def coverage(structure, hold_days):
    """Only what the structure promises (coverage and conditions), without the procedure common to
    every store: what is compared with the policy text for the seal."""
    return render(structure, hold_days).split("\nHow a claim is decided:")[0].rstrip() + "\n"


def terms_hash(structure, hold_days, windows=None):
    """SHA-256 of the text, as 0x + 64 hex: the value the order keeps in the escrow."""
    return "0x" + hashlib.sha256(render(structure, hold_days, windows).encode("utf-8")).hexdigest()
