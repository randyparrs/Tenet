"""Attests the Demo Shop emails on Lacre's Verifier (GenLayer Bradbury) in two phases and logs each
result. One command per email.

    <venv> tools/attest_mail.py send <ID> [--dry]
    <venv> tools/attest_mail.py confirm <ID>
    <venv> tools/attest_mail.py status
where <venv> has genlayer-py 0.16.3, the version Lacre's tools use.

send:
- up to 3 sends in flight at once (sent and not confirmed); the next one goes when the previous one
  reached ACCEPTED, which is when this command ends;
- sends nothing if the email already has a log entry, or if any send ended unreadable or cut off:
  that blocks new sends until it is checked by hand;
- before sending, read only: the email's key (d=, s=) in the KeyCache the Router points to, in final
  state, has to be `active`, and with that key the signature, the body and the expected alignment
  are verified locally (arbiter/mail_v1.py, Lacre's code). N3 (unregistered selector) is not sent
  and is logged as an expected refusal;
- the send is done by Lacre's tools/attest.py (github.com/eudomar500/lacre, MIT, Copyright (c) 2026
  Insidr Labs) unchanged, with --attempts 1 and --until accepted: a single attempt, never resent.
  Its verdict at ACCEPTED is not used: with several sends in flight from the same sender, domain and
  selector, it cannot tell which email each record belongs to.
confirm:
- waits for FINALIZED of that transaction (up to 4 hours) and reads, in final state, the sender's
  records_of and each new record; the email's record is the one with its bh and the hash of its
  Message-ID (unique per email);
- if the transaction finalized without executing, nothing was written: it is logged and not resent;
- if the record cannot be identified or read, it is logged as unreadable and blocks new sends;
- logs status, result, record, valid, aligned, reason, votes of the last round (tools/tx_votes.mjs)
  and the L2 receipt cost of the send (gas used x price, printed by Lacre's chain.py when sending).

The signer key is read from SIGNER_ENV and passed to attest.py in PROBE_PK, only in the child
process environment; it is never printed or stored. --dry runs the send checks with a throwaway key,
without sending or logging.
Also takes the emails of the end-to-end test from cases/e2e/mail-set.json.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lacre_boot  # noqa: E402,F401  (local.env, OS certificates and User-Agent; before genlayer_py)

LACRE = Path(os.environ.get("LACRE_DIR", ""))  # a clone of github.com/eudomar500/lacre (set in local.env)
SIGNER_ENV = Path(os.environ.get("SIGNER_ENV", ""))  # file with PRIVATE_KEY= (set in local.env)
sys.path[:0] = [str(LACRE), str(LACRE / "tools"), str(ROOT / "arbiter")]

import chain  # noqa: E402  (Lacre)
import headers_blob  # noqa: E402  (Lacre)
import txstate  # noqa: E402  (Lacre)
from genlayer_py.types import TransactionHashVariant  # noqa: E402

import mail_v1  # noqa: E402

FINAL = TransactionHashVariant.LATEST_FINAL
LOG = ROOT / "results" / "attest-mail.jsonl"
WORK = ROOT / "results" / "attest"
MAX_IN_FLIGHT = 3
FINAL_BUDGET_S, FINAL_POLL_S, PROGRESS_S = 4 * 3600, 30, 300
BLOCKING = ("sending", "illegible")  # states that block new sends


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def private_key():
    for line in SIGNER_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("PRIVATE_KEY="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            return value if value.startswith("0x") else "0x" + value
    sys.exit("no PRIVATE_KEY in %s" % SIGNER_ENV)


def states():
    out = {}
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            out.setdefault(row["id"], {}).update(row)
    return out


def append(row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(row, at=now()), ensure_ascii=False) + "\n")


E2E_SET = ROOT / "cases" / "e2e" / "mail-set.json"  # emails of the end-to-end test


def load_set():
    data = json.load(open(ROOT / "cases" / "mail-set.json", encoding="utf-8"))
    positives = {m["id"] for m in data["positives"]}
    mails = {m["id"]: m for m in data["positives"] + data["negatives"]}
    if E2E_SET.exists():
        e2e = json.load(open(E2E_SET, encoding="utf-8"))["positives"]
        assert not {m["id"] for m in e2e} & set(mails), "ids repeated between the sets"
        positives |= {m["id"] for m in e2e}
        mails.update({m["id"]: dict(m, eml=str(E2E_SET.parent / "mail" / ("%s.eml" % m["id"]))) for m in e2e})
    return positives, mails


def expectation(mid, positives):
    if mid in positives:
        return {"outcome": "recorded", "valid": True, "aligned": True}
    if mid == "N4":
        return {"outcome": "recorded", "valid": True, "aligned": False}
    return {"outcome": "refused", "reason": "key not registered"}  # N3


def signature_of(raw):
    head, _ = mail_v1.split_message(raw)
    fields = mail_v1.dkimcore.parse_headers(head)
    _, tags = mail_v1.dkimcore.find_signature(fields)
    mid = mail_v1.dkimcore.message_id(fields)
    return (tags.get("d", "").lower(), tags.get("s", "").lower(), mail_v1.dkimcore.unfold(tags.get("bh", "")),
            hashlib.sha256(mid.encode("utf-8")).hexdigest() if mid else "")


def connect(dry=False):
    # With --dry the reads use a throwaway key: the signer's key is not used.
    os.environ["PROBE_PK"] = "0x" + secrets.token_hex(32) if dry else private_key()
    account, client, net = chain.connect("bradbury")
    router = json.loads((LACRE / "deployments.json").read_text())["bradbury"]["router"]["address"]
    return account, client, net, router


def must(value, what):
    if value is chain.UNKNOWN or value is None:
        raise RuntimeError("could not read %s" % what)
    return value


def parse_send_log(text):
    def pick(pattern):
        return (re.findall(pattern, text, re.M) or [""])[-1]
    return {"tx": pick(r"^CONSENSUS TX : (0x[0-9a-fA-F]+)"), "l2_hash": pick(r"^L2 TX HASH\s+: (0x[0-9a-fA-F]+)"),
            "l2_status": pick(r"^L2 status\s+: (.*)$"), "l2_gas_used": pick(r"^L2 gasUsed\s+: (\d+)"),
            "l2_cost_wei": pick(r"^L2 cost\s+: (\d+) wei"), "status_at_send": pick(r"^status\s+: (\S+)"),
            "result_at_send": pick(r"^result\s+: (\S+)"), "attest_verdict": pick(r"^verdict\s+: (.*)$"),
            "not_sent": pick(r"^NOT SENT\s+: (.*)$"), "stopped": pick(r"^STOPPED\s+: (.*)$")}


def cmd_send(mid, dry):
    positives, mails = load_set()
    if mid not in positives and mid not in ("N3", "N4"):
        sys.exit("%s is not in the plan (the 18 valid emails, N3, N4 and the E2E emails)" % mid)
    st = states()
    if mid in st and not dry:
        sys.exit("%s is already logged (%s); not sent again." % (mid, st[mid].get("state")))
    blocking = [k for k, v in st.items() if v.get("state") in BLOCKING]
    if blocking and not dry:
        sys.exit("BLOCKED: %s ended %s; check it by hand before sending another one." % (
            ", ".join(blocking), "/".join(sorted({st[k]["state"] for k in blocking}))))
    in_flight = [k for k, v in st.items() if v.get("state") == "sent"]
    if len(in_flight) >= MAX_IN_FLIGHT and not dry:
        sys.exit("There are already %d sends in flight (%s); confirm one before sending another." % (
            len(in_flight), ", ".join(in_flight)))
    expect = expectation(mid, positives)
    raw = Path(mails[mid].get("eml") or ROOT / "cases" / "mail" / ("%s.eml" % mid)).read_bytes()
    domain, selector, bh, mid_hash = signature_of(raw)
    account, client, net, router = connect(dry)
    keycache = str(must(chain.read(net, client, router, "resolve", ["keycache"], FINAL), "resolve(keycache)"))
    key = chain.read(net, client, keycache, "key_status", [domain, selector], FINAL)
    if key is chain.UNKNOWN:
        sys.exit("could not read key_status; not sent")
    print("email %s: d=%s s=%s; KeyCache %s; key: %s" % (mid, domain, selector, keycache,
                                                     (key or {}).get("state", "not registered")))
    if not key or key.get("state") != "active":
        reason = "key not registered" if not key else "key " + str(key.get("state"))
        if key and key.get("n_hex") and dry:
            v = mail_v1.verify(raw, {(domain, selector): (int(key["n_hex"], 16), int(key["e"]))})
            print("DRY with the %s key: signature %s, body %s, aligned %s" % (
                key.get("state"), v["valid"], v["body_ok"], v["aligned"]))
        if expect["outcome"] == "refused" and reason == "key not registered":
            if not dry:
                append({"id": mid, "state": "refused_expected", "sent": False, "reason": reason,
                        "expected": expect, "as_expected": True})
            print("NOT SENT: the Verifier would refuse it (%s). That is what is expected for %s%s." % (
                reason, mid, "" if dry else "; logged"))
            return
        sys.exit("NOT SENT: the key %s/%s is not active (%s)." % (domain, selector, reason))
    local = mail_v1.verify(raw, {(domain, selector): (int(key["n_hex"], 16), int(key["e"]))})
    print("local: signature %s, body %s, aligned %s" % (local["valid"], local["body_ok"], local["aligned"]))
    if not (local["valid"] and local["body_ok"] and local["aligned"] == expect.get("aligned")):
        sys.exit("NOT SENT: the local check does not give the expected result.")
    blob = headers_blob.build(raw, domain, selector).encode("utf-8")
    if dry:
        print("DRY: ready to send; blob of %d bytes; in flight now: %d; expected: %s" % (
            len(blob), len(in_flight), expect))
        return
    WORK.mkdir(parents=True, exist_ok=True)
    blob_file, log_file = WORK / ("%s.blob.txt" % mid), WORK / ("%s.send.log" % mid)
    if log_file.exists():
        sys.exit("%s exists without a log entry: check it by hand." % log_file)
    blob_file.write_bytes(blob)
    base = {"id": mid, "domain": domain, "selector": selector, "bh": bh, "message_id_sha256": mid_hash,
            "sender": account.address, "expected": expect}
    append(dict(base, state="sending"))  # if the command is cut off, this state blocks new sends
    code = subprocess.call([sys.executable, str(ROOT / "tools" / "lacre_boot.py"), str(LACRE / "tools" / "attest.py"),
                            "--inline", str(blob_file), domain, selector, "--attempts", "1", "--until", "accepted",
                            "--log", str(log_file)], env=dict(os.environ))
    found = parse_send_log(log_file.read_text(encoding="utf-8"))
    if not found["tx"]:
        state = "not_sent" if found["not_sent"] else "illegible"
    elif found["status_at_send"] in txstate.DECIDED or found["status_at_send"] == "FINALIZED":
        state = "sent"
    else:
        state = "illegible"
    append(dict(base, state=state, attest_exit=code, **found))
    print("")
    print("SEND %s: %s; tx %s; status at the end %s %s; L2 cost %s wei (gas %s)" % (
        mid, state, found["tx"] or "-", found["status_at_send"] or "-", found["result_at_send"] or "",
        found["l2_cost_wei"] or "-", found["l2_gas_used"] or "-"))
    if state == "sent":
        print("In flight. Confirm at FINALIZED with: confirm %s" % mid)
    elif state == "not_sent":
        print("It did not reach the chain (%s). Not retried automatically; report it." % found["not_sent"])
    else:
        print("STOP: the result of the send could not be read. New sends are blocked; report it.")


def cmd_confirm(mid):
    st = states().get(mid)
    if not st or st.get("state") != "sent":
        sys.exit("%s is not in flight (state: %s)" % (mid, (st or {}).get("state", "not logged")))
    account, client, net, router = connect()
    tx = st["tx"]
    print("waiting for FINALIZED of %s (%s; up to %d hours) ..." % (mid, tx, FINAL_BUDGET_S // 3600))
    try:
        state = txstate.wait_stored(client, tx, statuses=txstate.FINAL, budget=FINAL_BUDGET_S,
                                    interval=FINAL_POLL_S, progress=PROGRESS_S)
    except Exception as error:
        append({"id": mid, "state": "illegible", "error": "%s: %s" % (type(error).__name__, str(error)[:200])})
        sys.exit("STOP: the transaction status could not be read (%s). New sends are blocked." % type(error).__name__)
    row = {"id": mid, "final_status": state["status"], "final_result": state["result"],
           "execution": state["execution"], "rounds": state["rounds"]}
    if state["status"] != "FINALIZED":
        if state["status"] == "CANCELED":
            append(dict(row, state="illegible", note="CANCELED"))
            sys.exit("STOP: the transaction ended CANCELED. New sends are blocked.")
        print("not FINALIZED yet (%s); run confirm %s again later" % (state["status"], mid))
        return
    votes = subprocess.run(["node", str(ROOT / "tools" / "tx_votes.mjs"), tx], capture_output=True, text=True,
                           cwd=str(ROOT))
    row["votes"] = json.loads(votes.stdout) if votes.returncode == 0 and votes.stdout.strip() else {}
    if st.get("l2_cost_wei"):
        row["cost_gen"] = "%.9f" % (int(st["l2_cost_wei"]) / 1e18)
    if not txstate.executed(state):
        append(dict(row, state="not_executed", as_expected=False))
        print("FINALIZED without executing (%s, %s): nothing was written; not resent automatically. Report it." % (
            state["result"], state["execution"]))
        return
    try:
        verifier = str(must(chain.read(net, client, router, "resolve", ["verifier"], FINAL), "resolve(verifier)"))
        ids = must(chain.read(net, client, verifier, "records_of", [st["sender"]], FINAL), "records_of")
        taken = {v.get("record_id") for k, v in states().items() if k != mid and v.get("record_id")}
        matches = []
        for rid in [str(i) for i in ids]:
            if rid in taken:
                continue
            rec = must(chain.read(net, client, verifier, "get", [rid], FINAL), "get(%s)" % rid)
            if rec.get("bh") == st["bh"] and rec.get("message_id_sha256") == st["message_id_sha256"]:
                matches.append((rid, rec))
    except RuntimeError as error:
        append(dict(row, state="illegible", error=str(error)))
        sys.exit("STOP: %s. New sends are blocked." % error)
    if len(matches) != 1:
        append(dict(row, state="illegible", note="%d records with the email's bh and Message-ID" % len(matches)))
        sys.exit("STOP: %d records match the email (1 expected). New sends are blocked."
                 % len(matches))
    rid, rec = matches[0]
    expect = st["expected"]
    ok = bool(rec.get("valid")) == expect["valid"] and bool(rec.get("aligned")) == expect["aligned"]
    append(dict(row, state="confirmed", record_id=rid, valid=bool(rec.get("valid")), aligned=bool(rec.get("aligned")),
                reason=rec.get("reason", ""), from_domain=rec.get("from_domain", ""),
                signed_at=str(rec.get("signed_at", "")), requester=rec.get("requester", ""), as_expected=ok))
    print("CONFIRMED %s: record %s, valid %s, aligned %s, reason %r; %s %s; votes %s; cost %s GEN -> %s" % (
        mid, rid, rec.get("valid"), rec.get("aligned"), rec.get("reason", ""), state["status"], state["result"],
        row["votes"].get("counts", "-"), row.get("cost_gen", "-"), "as expected" if ok else "NOT as expected"))


def cmd_status():
    st = states()
    if not st:
        print("no emails attested yet")
    for mid in sorted(st):
        r = st[mid]
        print("%-4s %-16s tx %-12s %s %s record %s valid %s aligned %s expected %s cost %s votes %s" % (
            mid, r.get("state"), (r.get("tx") or "-")[:12], r.get("final_status", r.get("status_at_send", "")),
            r.get("final_result", r.get("result_at_send", "")), r.get("record_id", "-"), r.get("valid", "-"),
            r.get("aligned", "-"), {True: "yes", False: "NO"}.get(r.get("as_expected"), "-"), r.get("cost_gen", "-"),
            (r.get("votes") or {}).get("counts", "-")))
    print("in flight: %d of %d allowed" % (sum(v.get("state") == "sent" for v in st.values()), MAX_IN_FLIGHT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("send", "confirm", "status"))
    ap.add_argument("mail", nargs="?")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.command == "status":
        cmd_status()
    elif not a.mail:
        sys.exit("missing the email ID")
    elif a.command == "send":
        cmd_send(a.mail, a.dry)
    else:
        cmd_confirm(a.mail)


if __name__ == "__main__":
    main()
