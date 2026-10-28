// GenLayer Bradbury Phase 2 (Consensus v0.6) for relayer/e2e.py: sends to and reads from the judges with
// genlayer-js 2.0.0-rc.2 (pinned outside the repository, GLJS2_DIST). One JSON line on stdout per command.
//
//   node tools/gl2.mjs send <address> <method>     arguments as a JSON array on stdin; signs with the
//                                                  PRIVATE_KEY of SIGNER_ENV (never printed), fee deposit
//                                                  estimated and capped at 10 GEN, waits for ACCEPTED
//   node tools/gl2.mjs final <tx> [minutes]        waits for FINALIZED (default 30 minutes); status, result,
//                                                  execution and the last round's votes (as tx_votes.mjs)
//   node tools/gl2.mjs read <address> <method> [final]   arguments as a JSON array on stdin
//
// Contract reads go to the GenLayer node (GL2_NODE, default rpc-bradbury.genlayer.com); sends and
// transaction reads to the chain RPC of the SDK's testnetBradbury. The public RPC refuses eth_call from the
// zero address, so reads without "from" are sent from the signer's address (reads only).
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const GLJS = (process.env.GLJS2_DIST || "C:/Users/randy/Desktop/refund-arbiter-tools/gljs-rc2/node_modules/genlayer-js/dist/").replace(/\\/g, "/");
const NODE = process.env.GL2_NODE || "https://rpc-bradbury.genlayer.com";
const MAX_FEE = 10n * 10n ** 18n;
const VOTES = ["NOT_VOTED", "FINISHED_WITH_RETURN", "FINISHED_WITH_ERROR", "TIMEOUT", "NONDET_DISAGREE", "DETERMINISTIC_VIOLATION"];
const { createClient, createAccount } = await import(pathToFileURL(GLJS + "index.js").href);
const { testnetBradbury } = await import(pathToFileURL(GLJS + "chains/index.js").href);

const out = (o) => console.log(JSON.stringify(o, (k, v) => (typeof v === "bigint" ? v.toString() : v)));
const stdinArgs = () => JSON.parse(readFileSync(0, "utf8") || "[]");

function signerKey() {
  const file = process.env.SIGNER_ENV;
  if (!file) throw new Error("set SIGNER_ENV (local.env)");
  const line = readFileSync(file, "utf8").split(/\r?\n/).find((l) => l.startsWith("PRIVATE_KEY="));
  if (!line) throw new Error("no PRIVATE_KEY in SIGNER_ENV");
  const k = line.slice("PRIVATE_KEY=".length).trim().replace(/^["']|["']$/g, "");
  return k.startsWith("0x") ? k : "0x" + k;
}

function fromShim(address) {
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    if (init && typeof init.body === "string" && init.body.includes('"eth_call"')) {
      const b = JSON.parse(init.body);
      for (const r of Array.isArray(b) ? b : [b]) if (r.method === "eth_call" && r.params?.[0] && !r.params[0].from) r.params[0].from = address;
      init = { ...init, body: JSON.stringify(b) };
    }
    return realFetch(url, init);
  };
}

function votesOf(tx) {
  const r = tx.lastRound ?? {};
  const counts = {};
  for (const raw of r.validatorVotes ?? []) {
    const code = String(raw);
    const name = `${code}:${VOTES[Number(code)] ?? "UNKNOWN"}`;
    counts[name] = (counts[name] ?? 0) + 1;
  }
  return counts;
}

const [cmd, a1, a2, a3] = process.argv.slice(2);
if (cmd === "send") {
  const account = createAccount(signerKey());
  fromShim(account.address);
  const client = createClient({ chain: testnetBradbury, account });
  const args = stdinArgs();
  const fees = await client.estimateTransactionFees({ appealRounds: 0 });
  const feeValue = BigInt(fees.feeValue);
  if (feeValue > MAX_FEE) throw new Error(`fee deposit ${feeValue} wei is above 10 GEN: nothing sent`);
  const hash = await client.writeContract({ address: a1, functionName: a2, args, value: 0n, fees });
  let decided = {};
  try {
    const r = await client.waitForTransactionReceipt({ hash, retries: 120, interval: 5000, waitUntil: "decided", fullTransaction: true });
    decided = { status: r.statusName, result: r.resultName, execution: r.txExecutionResultName };
  } catch (e) {
    decided = { wait_error: String(e.shortMessage || e.message).split("\n")[0].slice(0, 200) };
  }
  out({ tx: hash, fee_value: feeValue, ...decided });
} else if (cmd === "final") {
  const client = createClient({ chain: testnetBradbury });
  const minutes = Number(a2 || 30);
  const end = Date.now() + minutes * 60000;
  let tx;
  for (;;) {
    tx = await client.getTransaction({ hash: a1 });
    if (tx.statusName === "FINALIZED" || Date.now() > end) break;
    await new Promise((r) => setTimeout(r, 30000));
  }
  out({ status: tx.statusName, result: tx.resultName, execution: tx.txExecutionResultName, rounds: String(tx.numOfRounds ?? ""),
    votes: votesOf(tx), final: tx.statusName === "FINALIZED" });
} else if (cmd === "read") {
  fromShim("0x0F0c950043c4D0B570fb6A7eDE0874Df96966808");
  const client = createClient({ chain: testnetBradbury, endpoint: NODE });
  const value = await client.readContract({ address: a1, functionName: a2, args: stdinArgs(),
    transactionHashVariant: a3 === "final" ? "latest-final" : "latest-nonfinal" });
  out({ value });
} else {
  console.error("usage: node tools/gl2.mjs send <address> <method> | final <tx> [minutes] | read <address> <method> [final]");
  process.exit(2);
}
