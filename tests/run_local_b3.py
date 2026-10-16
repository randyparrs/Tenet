"""Local measurement of the store emails, committee part (B3, the version the email judge uses): the
committee reads only the body, which the contract checks against bh (Lacre does not keep the
subject). The code builds the date (resolve_date) from the body and the order date, and the majority
is taken over that date, which is what the contract compares.

Uses the body in cases/mail-set.json (the same text that is signed). Per run (pass x positive
email): the type question to the 5 models; if the majority is shipped, delayed or delivered and the
code found no labeled date, the date question, as in the contract. Each call is saved right away in
JSONL; --resume skips the saved ones. Same committee, temperature and retries (run_local.call).
Needs OPENROUTER_API_KEY in the environment (it is never printed or stored).

Usage: py -3.12 tests/run_local_b3.py --passes 10 --out results/local-b3.jsonl
Report: py -3.12 tests/report_local_b2.py results/local-b3.jsonl
"""
import argparse
import collections
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arbiter"))
sys.path.insert(0, str(ROOT / "tests"))
import mail_llm_v3 as mail_llm  # noqa: E402
import mail_v1  # noqa: E402
from run_local import MODELS, call  # noqa: E402


def majority(values):
    c = collections.Counter(v for v in values if v is not None)
    top, n = c.most_common(1)[0] if c else (None, 0)
    return top if n >= 3 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    data = json.load(open(ROOT / "cases" / "mail-set.json", encoding="utf-8"))
    out = ROOT / a.out
    saved = {}
    if a.resume and out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            saved[(r["pass"], r["mail"], r["question"], r["model"])] = r["answer"]
    elif out.exists():
        sys.exit("%s already exists: use --resume or another --out" % out)
    with open(out, "a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=5) as pool:

        def ask(n, m, question, body_text):
            text = body_text
            todo = [x for x in MODELS if (n, m["id"], question, x) not in saved]
            prompt = mail_llm.build_prompt(question, body_text)
            for model, res in pool.map(lambda x: (x, call(x, prompt, key)), todo):
                answer = mail_llm.canonical(question, res["text"]) if res.get("ok") else None
                if question == "date" and answer is not None:
                    resolved = mail_llm.resolve_date(answer, text, m["order_date"])
                else:
                    resolved = answer
                saved[(n, m["id"], question, model)] = resolved
                fh.write(json.dumps({
                    "pass": n, "mail": m["id"], "question": question, "model": model,
                    "prompt_sha256": mail_llm.PROMPT_SHA256, "parts": answer, "answer": resolved,
                    "ok": res.get("ok", False), "error": res.get("error", ""),
                    "provider": res.get("provider", ""), "secs": res.get("secs"),
                    "attempts": res.get("attempts"), "usage": res.get("usage", {}),
                    "raw": (res.get("text") or "")[:1000]}, ensure_ascii=False) + "\n")
                fh.flush()
            return majority([saved[(n, m["id"], question, x)] for x in MODELS])

        for n in range(1, a.passes + 1):
            for m in data["positives"]:
                body = m["body"].encode("latin-1")
                fixed = mail_v1.extract(body, data["profile"])["fixed_dates"]
                body_text = body.decode("utf-8")
                t = ask(n, m, "type", body_text)
                d = ask(n, m, "date", body_text) if mail_llm.needs_date(t, fixed) else "-"
                print("pass %d %s: type %s date %s" % (n, m["id"], t, d))
    print("done:", out)


if __name__ == "__main__":
    main()
