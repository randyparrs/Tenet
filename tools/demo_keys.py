"""Creates the two wallets of the demo mode and prints only their addresses.

- demo-relayer.env (DEMO_RELAYER_KEY): relayer of the demo escrow on Arc and sender of the demo
  judge and Lacre transactions on Bradbury.
- demo-store.env (DEMO_STORE_KEY): the demo store's wallet on Arc.

Both go to the E2E_KEYS folder (local.env), outside the project. An existing key is never
overwritten and no key is ever printed. The DKIM key of demo.rpmdev.app is made by
tools/dkim_keygen.mjs.

    python tools/lacre_boot.py tools/demo_keys.py
"""
import os
import sys
from pathlib import Path

from eth_account import Account

KEYS = Path(os.environ.get("E2E_KEYS", ""))
FILES = (("relayer", "demo-relayer.env", "DEMO_RELAYER_KEY"), ("store", "demo-store.env", "DEMO_STORE_KEY"))


def main():
    if not str(KEYS) or str(KEYS) == "." or not KEYS.is_dir():
        sys.exit("set E2E_KEYS in local.env to the keys folder (outside the project)")
    for who, name, var in FILES:
        path = KEYS / name
        if path.exists():
            line = next((x for x in path.read_text(encoding="utf-8").splitlines() if x.startswith(var + "=")), "")
            print("demo %-7s already exists, not overwritten: %s" % (who, Account.from_key(line.split("=", 1)[1].strip()).address))
            continue
        acct = Account.create()
        key = acct.key.hex()
        with open(path, "x", encoding="utf-8") as fh:
            fh.write("%s=%s\n" % (var, key if key.startswith("0x") else "0x" + key))
        print("demo %-7s created in %s: %s" % (who, path, acct.address))


if __name__ == "__main__":
    main()
