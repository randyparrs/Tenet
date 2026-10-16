"""Local committee: the 5 models (MODELS) and the OpenRouter call (call) every local measurement
uses. Run directly, it is the first measurement (the committee reads the policies in cases/cases.json).
Each call is saved as one JSONL line right away, so a cut run can be resumed (--resume skips the
calls already saved).

Needs OPENROUTER_API_KEY in the environment (it is never printed or stored).
Usage: py -3.12 tests/run_local.py --passes 10 --out results/local-v1.jsonl [--resume]
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arbiter"))
import policy  # noqa: E402

MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "qwen/qwen3-235b-a22b-2507",
    "google/gemma-3-27b-it",
    "mistralai/mistral-small-3.2-24b-instruct",
    "deepseek/deepseek-chat-v3-0324",
]
URL = "https://openrouter.ai/api/v1/chat/completions"
TEMPERATURE = 0.7


def call(model, prompt, key):
    body = {"model": model, "temperature": TEMPERATURE, "max_tokens": 400,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}]}
    last = ""
    for attempt in range(4):
        t0 = time.time()
        try:
            r = requests.post(URL, json=body, timeout=90,
                              headers={"Authorization": "Bearer " + key,
                                       "Content-Type": "application/json"})
            secs = round(time.time() - t0, 2)
            if r.status_code == 200:
                d = r.json()
                text = d["choices"][0]["message"]["content"] or ""
                return {"ok": True, "text": text, "provider": d.get("provider", ""),
                        "secs": secs, "attempts": attempt + 1,
                        "usage": d.get("usage", {})}
            last = "http %d" % r.status_code
            if r.status_code not in (408, 429, 500, 502, 503, 504):
                break
        except Exception as e:  # network error: retried
            last = type(e).__name__
        time.sleep(3 * (attempt + 1))
    return {"ok": False, "error": last, "attempts": 4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=10)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    cases = json.load(open(ROOT / "cases" / "cases.json", encoding="utf-8"))
    out = ROOT / a.out
    done = set()
    if a.resume and out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["pass"], row["case"], row["model"]))
    elif out.exists():
        sys.exit("%s already exists: use --resume or another --out" % out)
    with open(out, "a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=5) as pool:
        for n in range(1, a.passes + 1):
            for case in cases:
                todo = [m for m in MODELS if (n, case["id"], m) not in done]
                if not todo:
                    continue
                prompt = policy.build_prompt(case["policy"])
                results = list(pool.map(lambda m: (m, call(m, prompt, key)), todo))
                for model, res in results:
                    form = policy.canonical(res["text"]) if res.get("ok") else None
                    row = {"pass": n, "case": case["id"], "model": model,
                           "prompt_sha256": policy.PROMPT_SHA256, "canonical": form,
                           "ok": res.get("ok", False), "error": res.get("error", ""),
                           "provider": res.get("provider", ""), "secs": res.get("secs"),
                           "attempts": res.get("attempts"), "usage": res.get("usage", {}),
                           "raw": (res.get("text") or "")[:600]}
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                print("pass %d case %s: %s" % (n, case["id"], [
                    (r[1].get("ok") and policy.canonical(r[1]["text"])) or "x" for r in results]))
    print("done:", out)


if __name__ == "__main__":
    main()
