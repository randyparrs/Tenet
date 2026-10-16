// GenLayer Bradbury adapter of the demo Worker (genlayer-js 1.2.0, the version of the project's tools).
// The demo relayer key sends to the two demo judges and to Lacre's Verifier, nothing else. Gas is
// three times the node's estimate, capped at the per-transaction limit, as Lacre's tools/chain.py does.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";

const CAP = 16_777_216n;
const DONE = new Set(["FINALIZED", "CANCELED"]);

export function makeGl({ key, judges, router }) {
  const base = createAccount(key);
  const account = { ...base, signTransaction: (tx, o) => {
    const g = BigInt(tx.gas ?? 0n) * 3n;
    return base.signTransaction({ ...tx, gas: g > CAP ? CAP : g }, o);
  } };
  const client = createClient({ chain: testnetBradbury, account });
  const read = (address, functionName, args, final) => client.readContract({ address, functionName, args,
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

  return {
    address: base.address,
    async sendJudge(kind, claim, step) {
      const to = judges[kind];
      if (!to || !allowed(to)) throw new Error("not a demo judge: " + kind);
      return client.writeContract({ address: to, functionName: "judge", args: [claim, step], value: 0n });
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
      return client.writeContract({ address: to, functionName: "attest_inline", args: [blob, domain, selector], value: fee });
    },
    async findRecord(bh, final = true) {
      const v = await lacre();
      for (const [rid, b] of seen) if (b === bh) return rid;
      const ids = (await read(v, "records_of", [base.address], final)) || [];
      for (const id of ids) {
        const rid = String(id);
        if (seen.has(rid)) continue;
        const rec = await read(v, "get", [rid], final);
        const b = rec instanceof Map ? rec.get("bh") : rec?.bh;
        if (b) seen.set(rid, String(b));
        if (b === bh) return rid;
      }
      return null;
    },
  };
}
