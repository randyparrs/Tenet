"""Local measurement of not_as_described (C3): Q1 and Q2 to the committee, and the closing round.

Per run (pass x case): Q1 and Q2 to the 5 models every time (to measure both). If with those
majorities the code opens the closing round and the store answers in it, Q2 again on that answer
(question "q2r2"), as in the contract. Each call is saved right away in JSONL; --resume skips the
saved ones. Same committee, temperature and retries (run_local.call).
Needs OPENROUTER_API_KEY in the environment (it is never printed or stored).

Usage: py -3.12 tests/run_local_c3.py --passes 10 --out results/local-c3.jsonl [--cases cases/k17b.json]
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
import subjective_v3 as s3  # noqa: E402
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
    ap.add_argument("--cases", default="cases/subjective-c3.json", help="another case file with the same format")
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    data = json.load(open(ROOT / a.cases, encoding="utf-8"))
    if data["prompt_sha256"] != s3.PROMPT_SHA256:
        sys.exit("the prompts changed since the cases were generated: regenerate cases/subjective-c3.json")
    out = ROOT / a.out
    saved = {}
    if a.resume and out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            saved[(r["pass"], r["case"], r["question"], r["model"])] = r["verdict"]
    elif out.exists():
        sys.exit("%s already exists: use --resume or another --out" % out)
    with open(out, "a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=5) as pool:

        def ask(n, item, name, question, response, extra_proof=None):
            todo = [m for m in MODELS if (n, item["id"], name, m) not in saved]
            prompt = s3.build_prompt(question, item["description"], item["claim"], response, extra_proof)
            for model, res in pool.map(lambda m: (m, call(m, prompt, key)), todo):
                verdict = s3.canonical(question, res["text"]) if res.get("ok") else None
                saved[(n, item["id"], name, model)] = verdict
                fh.write(json.dumps({
                    "pass": n, "case": item["id"], "question": name, "model": model,
                    "prompt_sha256": s3.PROMPT_SHA256, "verdict": verdict,
                    "ok": res.get("ok", False), "error": res.get("error", ""),
                    "provider": res.get("provider", ""), "secs": res.get("secs"),
                    "attempts": res.get("attempts"), "usage": res.get("usage", {}),
                    "raw": (res.get("text") or "")[:1000]}, ensure_ascii=False) + "\n")
                fh.flush()
            return majority([saved[(n, item["id"], name, m)] for m in MODELS])

        for n in range(1, a.passes + 1):
            for item in data["cases"]:
                q1 = ask(n, item, "q1", "q1", "")
                q2 = ask(n, item, "q2", "q2", item["response"])
                r2 = item.get("round2") or {}
                q2r2 = "-"
                if s3.needs_closing_round(q1, q2, item["claim"], item["description"]) and r2.get("response"):
                    q2r2 = ask(n, item, "q2r2", "q2", r2["response"], r2.get("proof"))
                print("pass %d %s: q1 %s q2 %s q2r2 %s" % (n, item["id"], q1, q2, q2r2))
    print("done:", out)


if __name__ == "__main__":
    main()
