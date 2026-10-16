// Local test of worker/src/circle.js against a simulated Circle API (no network, no key).
//   node worker/test/circle.test.mjs
import { readFileSync } from "node:fs";
import { encodeFunctionData, toFunctionSelector } from "viem";
import { makeCircle } from "../src/circle.js";

const data = JSON.parse(readFileSync(new URL("../src/demo-data.json", import.meta.url), "utf8"));
const { escrow, usdc } = data.addresses;
const seen = [];
let initCode = null;
const fake = async (url, init) => {
  const path = url.replace("https://api.circle.com", "");
  const body = init.body ? JSON.parse(init.body) : null;
  seen.push({ path, method: init.method, headers: init.headers, body });
  const ok = (d) => ({ ok: true, status: 200, json: async () => ({ data: d }) });
  if (path === "/v1/w3s/users/social/token") return ok({ deviceToken: "dt", deviceEncryptionKey: "dk" });
  if (path === "/v1/w3s/user/initialize") {
    if (initCode) return { ok: false, status: 400, json: async () => ({ code: initCode, message: "user already initialized" }) };
    return ok({ challengeId: "c-init" });
  }
  if (path.startsWith("/v1/w3s/wallets")) return ok({ wallets: [{ id: "w1", address: "0xabc", blockchain: "ARC-TESTNET", accountType: "EOA", state: "LIVE" }] });
  if (path === "/v1/w3s/user/transactions/contractExecution") return ok({ challengeId: "c-tx" });
  if (path.startsWith("/v1/w3s/user/challenges/")) return ok({ challenge: { id: "c-tx", status: "COMPLETE", type: "CONTRACT_EXECUTION", correlationIds: ["t1"] } });
  if (path.startsWith("/v1/w3s/transactions/")) return ok({ transaction: { id: "t1", state: "COMPLETE", txHash: "0x" + "ab".repeat(32) } });
  return { ok: false, status: 404, json: async () => ({ code: 0, message: "no route" }) };
};
const c = makeCircle({ apiKey: "TEST_API_KEY:x:y", escrow, usdc, abi: data.escrow_abi, fetchImpl: fake, uuid: () => "00000000-0000-4000-8000-000000000000" });
let failed = 0;
const check = (ok, what) => { console.log((ok ? "ok   " : "BAD  ") + what); if (!ok) failed++; };
const fn = (name, args) => encodeFunctionData({ abi: data.escrow_abi, functionName: name, args });
const ERC20 = [{ type: "function", name: "approve", inputs: [{ type: "address" }, { type: "uint256" }], outputs: [{ type: "bool" }], stateMutability: "nonpayable" }];
const approve = (spender) => encodeFunctionData({ abi: ERC20, functionName: "approve", args: [spender, 1_000_000n] });
const ref = "0x" + "11".repeat(32);

check(JSON.stringify(await c.deviceToken("dev-1")) === JSON.stringify({ deviceToken: "dt", deviceEncryptionKey: "dk" }), "device token from Circle");
check(seen[0].headers.authorization === "Bearer TEST_API_KEY:x:y" && !seen[0].headers["x-user-token"], "the API key goes in the Authorization header; no user token before sign-in");
check((await c.initialize("ut")).challengeId === "c-init", "first sign-in: a challenge to create the wallet");
const init = seen.find((x) => x.path === "/v1/w3s/user/initialize");
check(init.body.accountType === "EOA" && JSON.stringify(init.body.blockchains) === '["ARC-TESTNET"]' && init.headers["x-user-token"] === "ut",
  "the wallet is an EOA on ARC-TESTNET, for the signed-in user (it pays its own gas, no Gas Station)");
initCode = 155106;
check((await c.initialize("ut")).challengeId === null, "a user already initialized gets no challenge");
initCode = 155999;
check(await c.initialize("ut").then(() => false, (e) => e.code === 155999), "any other Circle error is reported");
check((await c.wallet("ut")).address === "0xabc", "the user's Arc testnet wallet");
const calls = [
  [escrow, fn("pay", [ref, escrow, usdc, 1_000_000n, 2_592_000n, ref]), true, "pay"],
  [escrow, fn("openClaim", [ref, "0x7b7d"]), true, "openClaim"],
  [escrow, fn("submit", [ref, "0x7b7d"]), true, "submit"],
  [escrow, fn("withdraw", [usdc]), true, "withdraw"],
  [usdc, approve(escrow), true, "approve USDC to the demo escrow"],
  [usdc, approve("0x" + "22".repeat(20)), false, "approve USDC to anyone else"],
  [escrow, toFunctionSelector(data.escrow_abi.find((x) => x.name === "proposeVerdict")) + "00".repeat(32), false, "a relayer function of the escrow"],
  ["0x" + "33".repeat(20), fn("withdraw", [usdc]), false, "another contract"],
];
for (const [to, d, want, what] of calls) {
  const got = await c.execute("ut", "w1", to, d).then((r) => r.challengeId === "c-tx", () => false);
  check(got === want, (want ? "allowed: " : "refused: ") + what);
}
const ex = seen.filter((x) => x.path === "/v1/w3s/user/transactions/contractExecution");
check(ex.length === 5 && ex.every((x) => x.body.feeLevel === "MEDIUM" && x.body.callData && !x.body.abiFunctionSignature && x.body.walletId === "w1"),
  "only the allowed calls reach Circle, as raw callData with the wallet id and a fee level");
const ch = await c.challenge("ut", "c-tx"), tx = await c.transaction("ut", "t1");
check(ch.status === "COMPLETE" && ch.transactionId === "t1" && tx.state === "COMPLETE" && /^0x[0-9a-f]{64}$/.test(tx.txHash),
  "challenge to transaction to transaction hash");
console.log(failed ? `CIRCLE TEST FAIL (${failed})` : "CIRCLE TEST PASS");
process.exit(failed ? 1 : 0);
