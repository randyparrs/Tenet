// Arc adapter of the demo Worker (viem). Two keys: the demo relayer and the demo store. Every
// transaction goes to the demo escrow and nowhere else; it is simulated first (a revert sends
// nothing), signed, and handed back to the core, which stores it before broadcasting it.
import { createPublicClient, http, encodeFunctionData, parseEventLogs, defineChain, decodeErrorResult, hexToString, stringToHex, keccak256 } from "viem";
import { privateKeyToAccount } from "viem/accounts";

const MIN_FEE = 20_000_000_000n; // Arc: maxFeePerGas >= 20 gwei
const EVENTS = ["OrderPaid", "ClaimOpened", "Submitted", "ProofRequested", "VerdictProposed", "OrderSettled", "ClaimCleared"];
const ACTIONS = { relayer: ["markNoResponse", "markClosingTimeout", "openClosingRound", "requestProof", "proposeVerdict",
                            "executeVerdict", "releaseUnproven"],
                  store: ["submit", "merchantRefund"] };

export function makeArc({ rpc, chainId, escrow, abi, keys }) {
  const chain = defineChain({ id: chainId, name: "Arc", nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
                              rpcUrls: { default: { http: [rpc] } } });
  const client = createPublicClient({ chain, transport: http(rpc, { retryCount: 2 }) });
  const accounts = { relayer: privateKeyToAccount(keys.relayer), store: privateKeyToAccount(keys.store) };
  const times = new Map();

  async function blockTime(n) {
    if (!times.has(n)) times.set(n, Number((await client.getBlock({ blockNumber: BigInt(n) })).timestamp));
    if (times.size > 500) times.delete(times.keys().next().value);
    return times.get(n);
  }

  function errorName(e) {
    let cur = e;
    while (cur) {
      const data = cur.data?.data || cur.data;
      if (typeof data === "string" && data.startsWith("0x") && data.length >= 10) {
        try { return decodeErrorResult({ abi, data }).errorName; } catch { /* not ours */ }
      }
      if (cur.data?.errorName) return cur.data.errorName;
      cur = cur.cause;
    }
    return (e.shortMessage || e.message || String(e)).slice(0, 160);
  }

  return {
    addresses: { relayer: accounts.relayer.address, store: accounts.store.address },
    async now() { return Number((await client.getBlock({ blockTag: "latest" })).timestamp); },
    async latestBlock() { return Number(await client.getBlockNumber({ cacheTime: 0 })); },

    async logs(from, to) {
      const raw = await client.getLogs({ address: escrow, fromBlock: BigInt(from), toBlock: BigInt(to) });
      const out = [];
      for (const l of parseEventLogs({ abi, logs: raw, strict: false })) {
        if (!EVENTS.includes(l.eventName)) continue;
        const args = { ...l.args };
        for (const k of ["claim", "submission"]) {
          if (typeof args[k] === "string") args[k] = hexToString(args[k]);
        }
        out.push({ name: l.eventName, args, tx: l.transactionHash, index: Number(l.logIndex), block: Number(l.blockNumber),
                   time: await blockTime(Number(l.blockNumber)) });
      }
      return out;
    },

    async getOrder(ref) {
      const o = await client.readContract({ address: escrow, abi, functionName: "getOrder", args: [ref] });
      return { chain: o.chain, claimHash: o.claimHash, state: Number(o.state), claimedAt: Number(o.claimedAt) };
    },

    async prepare(who, fn, args) {
      if (!ACTIONS[who]?.includes(fn)) throw new Error(`${who} does not send ${fn}`);
      const account = accounts[who];
      const data = encodeFunctionData({ abi, functionName: fn, args: encodeArgs(fn, args) });
      let gas;
      try {
        gas = await client.estimateGas({ account, to: escrow, data });
      } catch (e) {
        throw new Error("the simulation reverts: " + errorName(e));
      }
      const price = await client.getGasPrice();
      const maxFeePerGas = 2n * price > MIN_FEE ? 2n * price : MIN_FEE;
      const nonce = await client.getTransactionCount({ address: account.address, blockTag: "pending" });
      const tx = { to: escrow, data, gas: (gas * 13n) / 10n, maxFeePerGas, maxPriorityFeePerGas: maxFeePerGas < 10n ** 9n ? maxFeePerGas : 10n ** 9n,
                   nonce, chainId, type: "eip1559", value: 0n };
      const raw = await account.signTransaction(tx);
      return { raw, hash: keccak256(raw), nonce };
    },

    async broadcast(raw) {
      try {
        await client.sendRawTransaction({ serializedTransaction: raw });
      } catch (e) {
        const m = (e.shortMessage || e.message || "").toLowerCase();
        if (!/already known|nonce too low|already imported|known transaction/.test(m)) throw e;
      }
    },

    async waitReceipt(hash, ms) {
      try {
        const r = await client.waitForTransactionReceipt({ hash, timeout: ms, pollingInterval: 500 });
        return { status: r.status, block: Number(r.blockNumber) };
      } catch {
        return null; // not mined yet: resolved on a later tick
      }
    },

    async receipt(hash) {
      try {
        const r = await client.getTransactionReceipt({ hash });
        return { status: r.status, block: Number(r.blockNumber) };
      } catch {
        return null;
      }
    },
  };
}

// Text arguments travel as bytes; hashes as bytes32.
function encodeArgs(fn, args) {
  if (fn === "submit") return [args[0], stringToHex(args[1])];
  if (fn === "proposeVerdict") return [args[0], args[1], BigInt(args[2]), args[3], args[4], args[5]];
  return args;
}
