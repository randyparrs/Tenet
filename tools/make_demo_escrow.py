"""Builds evm/demo/RefundEscrow.sol, the escrow of the demo mode (README.md, "The Demo Shop runs on minutes").

Same source as evm/src/RefundEscrow.sol with exactly four constants changed, so every demo window
runs in minutes. The script fails unless the two files differ in those four lines and nowhere else.
evm/src/RefundEscrow.sol is never written.

    py -3.12 tools/make_demo_escrow.py
Then, in evm/: `forge test` (live escrow) and `FOUNDRY_PROFILE=demo forge test` (demo escrow; build
output in evm/out-demo, so evm/out stays the live build).
"""
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evm" / "src" / "RefundEscrow.sol"
OUT = ROOT / "evm" / "demo" / "RefundEscrow.sol"
CHANGES = (
    ("    uint256 public constant MIN_VERDICT_DELAY = 10 minutes;", "    uint256 public constant MIN_VERDICT_DELAY = 1 minutes;"),
    ("    uint256 public constant PROOF_WINDOW = 7 days;", "    uint256 public constant PROOF_WINDOW = 5 minutes;"),
    ("    uint256 public constant RESPONSE_WINDOW = 72 hours;", "    uint256 public constant RESPONSE_WINDOW = 5 minutes;"),
    ("    uint256 public constant CLOSING_WINDOW = 72 hours;", "    uint256 public constant CLOSING_WINDOW = 5 minutes;"),
)


def main():
    with open(SRC, encoding="utf-8", newline="") as fh:  # keep the line endings of the source
        src = fh.read()
    out = src
    for old, new in CHANGES:
        if src.count(old) != 1:
            sys.exit("not exactly one line %r in %s" % (old.strip(), SRC))
        out = out.replace(old, new)
    diff = [d for d in difflib.unified_diff(src.splitlines(), out.splitlines(), lineterm="", n=0)
            if d[:1] in "+-" and not d.startswith(("+++", "---"))]
    want = sorted(["-" + o for o, _ in CHANGES] + ["+" + n for _, n in CHANGES])
    if sorted(d.rstrip("\r") for d in diff) != sorted(w.rstrip("\r") for w in want):
        sys.exit("unexpected difference:\n" + "\n".join(diff))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8", newline="")
    print("%s: %d lines differ from %s (the 4 constants of DM-P1)" % (
        OUT.relative_to(ROOT), len(diff) // 2, SRC.relative_to(ROOT)))


if __name__ == "__main__":
    main()
