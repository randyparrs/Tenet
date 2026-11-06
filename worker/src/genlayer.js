// GenLayer Bradbury Phase 2 adapter of the demo Worker (genlayer-js 2.0.0-rc.2), the same calls as Tenet Pay's gateway
// adapter and tools/gl2.mjs. The demo relayer key sends to the two demo judges and to Lacre's Verifier, nothing else.
// Each send estimates its fee deposit (returned at finalization) and stops above 10 GEN; genlayer-js sets the gas
// limit from the node's estimate. Sends and transaction reads go to the SDK's chain RPC; contract reads go to the
// GenLayer node.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";

const NODE = "https://rpc-bradbury.genlayer.com";
const MAX_FEE = 10n * 10n ** 18n;
const DONE = new Set(["FINALIZED", "CANCELED"]);
const plain = (x) => (x instanceof Map ? Object.fromEntries([...x].map(([k, v]) => [k, String(v)])) : x || {});

/** The public RPC refuses eth_call from the zero address, so a GenLayer eth_call without "from" goes from the relayer's. */
export function withFrom(realFetch, address) {
  return async (url, init) => {
    if (/genlayer\.com/.test(String(url)) && init && typeof init.body === "string" && init.body.includes('"eth_call"')) {
      const b = JSON.parse(init.body);
      for (const r of Array.isArray(b) ? b : [b]) if (r.method === "eth_call" && r.params?.[0] && !r.params[0].from) r.params[0].from = address;
      init = { ...init, body: JSON.stringify(b) };
    }
    return realFetch(url, init);
  };
}

export function makeGl({ key, judges, router }) {
  const account = createAccount(key);
  globalThis.fetch = withFrom(globalThis.fetch.bind(globalThis), account.address);
  const client = createClient({ chain: testnetBradbury, account });
  const node = createClient({ chain: testnetBradbury, account, endpoint: NODE });
  const read = (address, functionName, args, final) => node.readContract({ address, functionName, args,
    transactionHashVariant: final ? "latest-final" : "latest-nonfinal" });
  let verifier = null, fee = null;
  const seen = new Map(); // record id -> bh, final records only

  async function lacre() {
    if (!verifier) {
      verifier = String(await read(router, "resolve", ["verifier"], true));
      fee = BigInt(await read(verifier, "fee", [], true));
    }
    return verifier;
  }
  const allowed = (to) => [judges.mail, judges.subjective, verifier].filter(Boolean).map((x) => x.toLowerCase())
    .includes(String(to).toLowerCase());
  const write = async (address, functionName, args, value = 0n) => {
    if (!allowed(address)) throw new Error("not a demo judge or Lacre's Verifier: " + address);
    const fees = await client.estimateTransactionFees({ appealRounds: 0 });
    if (BigInt(fees.feeValue) > MAX_FEE) throw new Error(`fee deposit ${fees.feeValue} wei is above 10 GEN: nothing sent`);
    return client.writeContract({ address, functionName, args, value, fees });
  };

  return {
    address: account.address,
    async sendJudge(kind, claim, step) {
      const to = judges[kind];
      if (!to) throw new Error("not a demo judge: " + kind);
      return write(to, "judge", [claim, step]);
    },
    async status(tx) {
      try {
        const t = await client.getTransaction({ hash: tx });
        const status = String(t.statusName || t.status);
        return { status, result: String(t.resultName ?? ""), done: DONE.has(status), lastVote: Number(t.lastVoteTimestamp || 0) };
      } catch {
        return null; // statuses genlayer-js cannot name: read again next tick
      }
    },
    async verdict(kind, chain, final) {
      try {
        const raw = await read(judges[kind], "get_verdict", [chain], final);
        return raw ? JSON.parse(String(raw)) : null;
      } catch {
        return null;
      }
    },
    async attest(blob, domain, selector) {
      const to = await lacre();
      return write(to, "attest_inline", [blob, domain, selector], fee);
    },
    async findRecord(bh, final = true) {
      const v = await lacre();
      for (const [rid, b] of seen) if (b === bh) return rid;
      const ids = (await read(v, "records_of", [account.address], final)) || [];
      for (const id of ids) {
        const rid = String(id);
        if (seen.has(rid)) continue;
        const b = plain(await read(v, "get", [rid], final)).bh;
        if (b) seen.set(rid, String(b));
        if (b === bh) return rid;
      }
      return null;
    },
  };
}
