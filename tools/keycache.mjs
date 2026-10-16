// Lacre's KeyCache on Bradbury for the DKIM key of a test store domain.
// The KeyCache address is read from Lacre's Router (resolve("keycache")) in final state.
//
//   node tools/keycache.mjs status   [domain selector]   read only, no key: the key's state in the KeyCache
//   node tools/keycache.mjs register [domain selector]   register_key: the key stays "pending" for 24 hours
//   node tools/keycache.mjs confirm  [domain selector]   confirm_key: after the 24 hours, activates it
// Without domain and selector: shop.rpmdev.app / shop1 (the live test store, Demo Shop). The Demo Shop
// section of the page: demo.rpmdev.app demo1.
//
// GLJS_DIST: the dist/ folder of an installed genlayer-js (1.2.0 was used). SIGNER_ENV (register and
// confirm only): a file with PRIVATE_KEY=0x... of the wallet that pays GEN; the key is never printed.
// One transaction at a time: it waits until the transaction is decided and then reads the key's
// state; the KeyCache record is the proof, not the transaction.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const GLJS = process.env.GLJS_DIST;
const SIGNER_ENV = process.env.SIGNER_ENV;
if (!GLJS) throw new Error("set GLJS_DIST to the dist/ folder of genlayer-js");
const { createAccount, createClient } = await import(pathToFileURL(GLJS + "index.js").href);
const { testnetBradbury } = await import(pathToFileURL(GLJS + "chains/index.js").href);

const ROUTER = "0xEf37cb72C3A9dD6bCE2f3575B75c94C555F9c8d9";
const DOMAIN = process.argv[3] ?? "shop.rpmdev.app";
const SELECTOR = process.argv[4] ?? "shop1";
if (!/^[a-z0-9.-]+$/.test(DOMAIN) || !/^[a-z0-9-]+$/.test(SELECTOR)) throw new Error("invalid domain or selector");
const DONE = new Set(["ACCEPTED", "UNDETERMINED", "FINALIZED"]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const reader = createClient({ chain: testnetBradbury });
const read = (address, functionName, args = []) =>
  reader.readContract({ address, functionName, args, transactionHashVariant: "latest-final" });
const show = (v) => JSON.stringify(v, (k, x) => (typeof x === "bigint" ? x.toString() : x instanceof Map ? Object.fromEntries(x) : x), 1);

const keycache = await read(ROUTER, "resolve", ["keycache"]);
const status = async () => {
  console.log("KeyCache", keycache, `${SELECTOR}._domainkey.${DOMAIN}`);
  console.log("key_status:", show(await read(keycache, "key_status", [DOMAIN, SELECTOR])));
  console.log("last_failure:", show(await read(keycache, "last_failure", [DOMAIN, SELECTOR])));
};

const cmd = process.argv[2];
if (cmd === "status") {
  await status();
} else if (cmd === "register" || cmd === "confirm") {
  if (!SIGNER_ENV) throw new Error("set SIGNER_ENV to the file with PRIVATE_KEY=");
  const line = readFileSync(SIGNER_ENV, "utf8").split(/\r?\n/).find((l) => l.startsWith("PRIVATE_KEY="));
  if (!line) throw new Error(`no PRIVATE_KEY in ${SIGNER_ENV}`);
  const base = createAccount(`0x${line.slice(12).trim().replace(/^["']|["']$/g, "").replace(/^0x/, "")}`);
  const GAS_FLOOR = BigInt(process.env.GAS_FLOOR ?? "5000000");
  const account = { ...base, signTransaction: (tx, o) => base.signTransaction({ ...tx, gas: tx.gas && tx.gas > GAS_FLOOR ? tx.gas : GAS_FLOOR }, o) };
  const client = createClient({ chain: testnetBradbury, account });
  const fn = cmd === "register" ? "register_key" : "confirm_key";
  const hash = await client.writeContract({ address: keycache, functionName: fn, args: [DOMAIN, SELECTOR], value: 0n });
  console.log(`${fn} sent ${hash}`);
  const t0 = Date.now();
  let tx = {};
  while (Date.now() - t0 < 20 * 60 * 1000) {
    await sleep(8000);
    try { tx = await client.getTransaction({ hash }); } catch { continue; }
    if (DONE.has(tx.statusName)) break;
  }
  console.log("transaction status:", tx.statusName, tx.resultName ?? "", tx.txExecutionResultName ?? "");
  console.log("What counts is the key's state read in final state (FINALIZED can take about 30 min):");
  await status();
} else {
  console.log("usage: node tools/keycache.mjs status|register|confirm [domain selector]");
}
