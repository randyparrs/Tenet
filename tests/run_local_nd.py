"""Local measurement of not_delivered (ND): Q2-ND to the committee and the closing round.
Per run (pass x case): Q2-ND on the store's answer to the 5 models; if the majority is
disputes_with_fact and the store answers in the closing round, Q2-ND again on that answer with the
text added by the buyer (question "q2r2"), as in the contract. Each call is saved right away in
JSONL; --resume skips the saved ones. Same committee, temperature and retries (run_local.call).
Needs OPENROUTER_API_KEY in the environment (it is never printed or stored).
Usage: py -3.12 tests/run_local_nd.py --passes 10 --out results/local-nd.jsonl [--cases cases/g1d.json]
Report: py -3.12 tests/report_local_nd.py results/local-nd.jsonl
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
import not_delivered as nd  # noqa: E402
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
    ap.add_argument("--cases", default="cases/nd.json", help="another case file with the same format")
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    data = json.load(open(ROOT / a.cases, encoding="utf-8"))
    if data["prompt_sha256"] != nd.PROMPT_SHA256:
        sys.exit("the prompt changed since the cases were generated: regenerate %s" % a.cases)
    out = ROOT / a.out
    saved = {}
    if a.resume and out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            saved[(r["pass"], r["case"], r["question"], r["model"])] = r["verdict"]
    elif out.exists():
        sys.exit("%s already exists: use --resume or another --out" % out)
    with open(out, "a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=5) as pool:
        def ask(n, item, name, response, statement=None):
            todo = [m for m in MODELS if (n, item["id"], name, m) not in saved]
            prompt = nd.build_prompt(item["account"], response, statement)
            for model, res in pool.map(lambda m: (m, call(m, prompt, key)), todo):
                verdict = nd.canonical(res["text"]) if res.get("ok") else None
                saved[(n, item["id"], name, model)] = verdict
                fh.write(json.dumps({
                    "pass": n, "case": item["id"], "question": name, "model": model,
                    "prompt_sha256": nd.PROMPT_SHA256, "verdict": verdict,
                    "ok": res.get("ok", False), "error": res.get("error", ""),
                    "provider": res.get("provider", ""), "secs": res.get("secs"),
                    "attempts": res.get("attempts"), "usage": res.get("usage", {}),
                    "raw": (res.get("text") or "")[:1000]}, ensure_ascii=False) + "\n")
                fh.flush()
            return majority([saved[(n, item["id"], name, m)] for m in MODELS])
        for n in range(1, a.passes + 1):
            for item in data["cases"]:
                q2 = ask(n, item, "q2", item["response"])
                q2r2 = "-"
                r2 = item.get("closing") or {}
                if nd.needs_closing_round(q2) and str(r2.get("response") or "").strip():
                    q2r2 = ask(n, item, "q2r2", r2["response"], r2.get("statement"))
                print("pass %d %s: q2 %s q2r2 %s" % (n, item["id"], q2, q2r2))
    print("done:", out)


if __name__ == "__main__":
    main()
