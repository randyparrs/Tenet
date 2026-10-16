"""Sends GEN on GenLayer Bradbury from the signer wallet to the demo relayer, which pays the demo's
judge steps and Lacre attestations. The only recipient is the demo relayer's
address, read from E2E_KEYS/demo-relayer.env; no key is printed.

    python tools/lacre_boot.py tools/fund_demo_relayer.py <GEN> [--dry]

--dry estimates and prints the balances without sending.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

from eth_account import Account
from web3 import Web3

RPC, CHAIN_ID = "https://rpc-bradbury.genlayer.com", 4221
MAX_GEN = Decimal("5")


def key_from(path, name):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            v = line.split("=", 1)[1].strip().strip("\"'")
            return Account.from_key(v if v.startswith("0x") else "0x" + v)
    sys.exit("no %s in %s" % (name, path))


def main():
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv
    if len(args) != 1:
        sys.exit(__doc__)
    amount = Decimal(args[0])
    if not Decimal("0") < amount <= MAX_GEN:
        sys.exit("amount between 0 and %s GEN" % MAX_GEN)
    signer = key_from(os.environ["SIGNER_ENV"], "PRIVATE_KEY")
    relayer = key_from(Path(os.environ["E2E_KEYS"]) / "demo-relayer.env", "DEMO_RELAYER_KEY").address
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 60}))
    if w3.eth.chain_id != CHAIN_ID:
        sys.exit("unexpected chain id %s" % w3.eth.chain_id)
    gen = lambda a: Decimal(w3.eth.get_balance(a)) / Decimal(10**18)  # noqa: E731
    print("signer       %s  %s GEN" % (signer.address, gen(signer.address)))
    print("demo relayer %s  %s GEN" % (relayer, gen(relayer)))
    value = int(amount * 10**18)
    tx = {"from": signer.address, "to": relayer, "value": value, "chainId": CHAIN_ID,
          "nonce": w3.eth.get_transaction_count(signer.address)}
    gas = w3.eth.estimate_gas(tx)
    base = w3.eth.get_block("latest")["baseFeePerGas"]
    tip = w3.to_wei(2, "gwei")
    tx.update(gas=gas * 2, maxFeePerGas=base * 2 + tip, maxPriorityFeePerGas=tip)
    print("transfer     %s GEN, gas estimate %d" % (amount, gas))
    if dry:
        print("--dry: nothing sent")
        return
    h = w3.eth.send_raw_transaction(signer.sign_transaction(tx).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=300)
    print("SENT tx %s, status %d" % (w3.to_hex(h), r["status"]))
    print("demo relayer now %s GEN" % gen(relayer))


if __name__ == "__main__":
    main()
