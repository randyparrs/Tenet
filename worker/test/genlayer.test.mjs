// worker/src/genlayer.js without a network: a GenLayer eth_call without "from" goes from the relayer's address and
// nothing else changes (a call that has one, other methods, Arc's RPC); the adapter sends only to the demo judges.
import { withFrom, makeGl } from "../src/genlayer.js";

let failed = 0;
const check = (cond, what) => { console.log(`${cond ? "ok  " : "BAD "} ${what}`); if (!cond) failed++; };
const ME = "0x09eA4087B9245E1EfB95aCbA437FD1Ff8B4A0D63";
const seen = [];
const f = withFrom(async (url, init) => { seen.push({ url, init }); return "reply"; }, ME);
const call = (extra = {}) => ({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to: "0x01", data: "0x", ...extra }, "latest"] });
const body = (i) => JSON.parse(seen[i].init.body);

const reply = await f("https://rpc-bradbury.genlayer.com", { method: "POST", body: JSON.stringify(call()) });
check(reply === "reply" && body(0).params[0].from === ME, "GenLayer eth_call without from: sent from the relayer's address");
await f("https://rpc.testnet-chain.genlayer.com", { method: "POST", body: JSON.stringify([call(), call({ from: "0x02" })]) });
check(body(1)[0].params[0].from === ME && body(1)[1].params[0].from === "0x02", "a batch: only the one without from; a given from stays");
const arc = JSON.stringify(call());
await f("https://rpc.testnet.arc.io", { method: "POST", body: arc });
check(seen[2].init.body === arc, "Arc's RPC is not touched");
const other = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getBalance", params: ["0x01", "latest"] });
await f("https://rpc-bradbury.genlayer.com", { method: "POST", body: other });
check(seen[3].init.body === other, "other methods are not touched");
await f("https://rpc-bradbury.genlayer.com");
check(seen[4].init === undefined, "a request without a body goes through");

// makeGl with a throwaway key and no network: an unknown judge kind is refused before anything is sent
const net = [];
globalThis.fetch = async (url, init) => { net.push(url); throw new Error("no network in this test"); };
const gl = makeGl({ key: "0x" + "11".repeat(32), judges: { mail: "0x" + "a".repeat(40), subjective: "0x" + "b".repeat(40) }, router: "0x" + "c".repeat(40) });
const refused = await gl.sendJudge("other", "{}", "{}").then(() => false, (e) => /not a demo judge/.test(e.message));
check(refused && net.length === 0, "a judge kind that is not mail or subjective: refused, nothing sent");
console.log(failed ? `GENLAYER ADAPTER FAIL (${failed})` : "genlayer.js: 6/6");
process.exit(failed ? 1 : 0);
