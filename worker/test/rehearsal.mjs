// Local rehearsal of the demo Worker. No network and
// no real keys: the demo escrow (evm/out-demo) on anvil, the judges and Lacre simulated by
// tests/demo_gl_stub.py (the judge contracts as built, in Lacre's simulated SDK), and the Worker's
// own core and Arc adapter. Both child processes live only while this command runs.
//
// Keys are anvil's public test accounts; the DKIM key is generated here and thrown away.
//
//   VENV_PY=<python with genlayer-py> node worker/test/rehearsal.mjs
//   (from the repository root; needs Foundry's anvil, and local.env for LACRE_DIR; see README.md)
import { spawn } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { generateKeyPairSync } from "node:crypto";
import { createServer } from "node:net";
import { createPublicClient, createWalletClient, http, defineChain, stringToHex, parseEventLogs } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { DemoCore, REFUND_TEXT } from "../src/core.js";
import { makeArc } from "../src/arc.js";
import { importDkimKey, cj, orderRef } from "../src/util.js";
import { makeCircle, circleApi } from "../src/circle.js";

const ROOT = new URL("../../", import.meta.url);
const P = (rel) => new URL(rel, ROOT);
const HOME = process.env.USERPROFILE || process.env.HOME;
// Foundry's anvil: $ANVIL, else the default foundryup location, else the one on PATH (as in CI).
const ANVIL_HOME = `${HOME}/.foundry/bin/anvil${process.platform === "win32" ? ".exe" : ""}`;
const ANVIL = process.env.ANVIL || (existsSync(ANVIL_HOME) ? ANVIL_HOME : "anvil");
const PY = process.env.VENV_PY || "python";
const USDC = "0x3600000000000000000000000000000000000000";
// anvil's public test accounts
const K = ["0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80", "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
  "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a", "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
  "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a", "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
  "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e"];
const [OWNER, GUARDIAN, RELAYER, STORE, B1, B2, B3] = K.map((k) => privateKeyToAccount(k));
// The wallet Circle "creates" for a visitor who signs in with Google (anvil's public test account 7)
const CIRCLE_USER = privateKeyToAccount("0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356");

const lines = [];
const say = (t) => { console.log(t); lines.push(t); };
let failed = 0;
const check = (cond, what) => { say(`${cond ? "ok  " : "BAD "} ${what}`); if (!cond) failed++; };

const freePort = () => new Promise((res) => { const s = createServer(); s.listen(0, () => { const p = s.address().port; s.close(() => res(p)); }); });

async function main() {
  const port = await freePort(), stubPort = await freePort();
  const url = `http://127.0.0.1:${port}`;
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048, publicExponent: 65537 });
  const jwk = publicKey.export({ format: "jwk" });
  const nHex = Buffer.from(jwk.n, "base64url").toString("hex");
  const data = JSON.parse(readFileSync(P("worker/src/demo-data.json"), "utf8"));
  // The rehearsal's store and relayer are anvil accounts: the data file and the simulated judges use them.
  data.addresses.store = STORE.address;
  data.addresses.relayer = RELAYER.address;
  const dataFile = P("results/demo-rehearsal-data.json");
  writeFileSync(dataFile, JSON.stringify(data));
  const anvil = spawn(ANVIL, ["--port", String(port), "--chain-id", "5042002", "--silent"], { stdio: "ignore" });
  const stub = spawn(PY, ["tools/lacre_boot.py", "tests/demo_gl_stub.py", String(stubPort), nHex, "65537"],
    { cwd: ROOT, env: { ...process.env, DEMO_DATA: dataFile.pathname.replace(/^\/([A-Z]:)/, "$1") }, stdio: ["ignore", "pipe", "inherit"] });
  try {
    await new Promise((res, rej) => { stub.stdout.on("data", (b) => String(b).includes("READY") && res()); stub.on("exit", (c) => rej(new Error("stub exited " + c))); });
    await run(url, stubPort, data, privateKey.export({ type: "pkcs8", format: "pem" }));
  } finally {
    anvil.kill();
    stub.kill();
  }
  say(failed ? `REHEARSAL FAIL (${failed})` : "REHEARSAL PASS");
  writeFileSync(P("results/demo-rehearsal.txt"), lines.join("\n") + "\n");
  process.exit(failed ? 1 : 0);
}

async function run(url, stubPort, data, pem) {
  const chain = defineChain({ id: 5042002, name: "anvil", nativeCurrency: { name: "ETH", symbol: "ETH", decimals: 18 }, rpcUrls: { default: { http: [url] } } });
  const pub = createPublicClient({ chain, transport: http(url) });
  for (let i = 0; i < 100; i++) { try { await pub.getChainId(); break; } catch { await new Promise((r) => setTimeout(r, 200)); } }
  const rpc = (method, params) => pub.request({ method, params });
  const wallet = (acct) => createWalletClient({ account: acct, chain, transport: http(url) });
  const wait = async (h) => { const r = await pub.waitForTransactionReceipt({ hash: h }); if (r.status !== "success") throw new Error("reverted " + h); return r; };
  const warp = async (s) => { await rpc("evm_increaseTime", [Number(s)]); await rpc("evm_mine", []); };
  const now = async () => Number((await pub.getBlock()).timestamp);

  // test USDC at the Arc address, and the demo escrow
  const stable = JSON.parse(readFileSync(P("evm/out/RefundEscrow.t.sol/Stable.json"), "utf8"));
  const art = JSON.parse(readFileSync(P("evm/out-demo/RefundEscrow.sol/RefundEscrow.json"), "utf8"));
  const ow = wallet(OWNER);
  let r = await wait(await ow.deployContract({ abi: stable.abi, bytecode: stable.bytecode.object, args: ["USDC"] }));
  await rpc("anvil_setCode", [USDC, await pub.getCode({ address: r.contractAddress })]);
  for (const b of [B1, B2, B3, CIRCLE_USER]) await wait(await ow.writeContract({ address: USDC, abi: stable.abi, functionName: "mint", args: [b.address, 20_000_000n] }));
  r = await wait(await ow.deployContract({ abi: art.abi, bytecode: art.bytecode.object,
    args: [OWNER.address, RELAYER.address, GUARDIAN.address, [USDC], [1_000_000n], 120n] }));
  const escrow = r.contractAddress;
  await wait(await wallet(RELAYER).writeContract({ address: escrow, abi: art.abi, functionName: "setMerchantTerms",
    args: [STORE.address, BigInt(data.terms.hold_seconds), data.terms.terms_hash] }));
  data.addresses.escrow = escrow;
  data.addresses.deploy_block = Number(r.blockNumber);
  const windows = await Promise.all(["RESPONSE_WINDOW", "CLOSING_WINDOW", "PROOF_WINDOW"].map((f) => pub.readContract({ address: escrow, abi: art.abi, functionName: f })));
  check(windows.every((x) => x === 300n), "DEMO0 demo escrow on anvil: response, closing and proof windows of 5 minutes");

  // the Worker: memory storage, real Arc adapter, simulated Bradbury
  const mem = new Map();
  const store = { get: async (k) => structuredClone(mem.get(k)), put: async (k, v) => { mem.set(k, structuredClone(v)); },
    delete: async (k) => { mem.delete(k); }, list: async (p) => [...mem.entries()].filter(([k]) => k.startsWith(p)).map(([, v]) => structuredClone(v)) };
  const stubCall = async (path, body) => {
    const res = await fetch(`http://127.0.0.1:${stubPort}${path}`, { method: "POST", body: JSON.stringify(body), headers: { "content-type": "application/json" } });
    const out = await res.json();
    if (out.error) throw new Error(out.error);
    return out;
  };
  let arcRef;
  const gl = {
    sendJudge: async (kind, claim, step) => (await stubCall("/judge", { kind, claim, step, when: await arcRef.now(), sender: RELAYER.address })).tx,
    status: (tx) => stubCall("/status", { tx }),
    verdict: async (kind, ch, final) => (await stubCall("/verdict", { kind, chain: ch, final })).verdict,
    attest: async (blob, domain, selector, raw) => (await stubCall("/attest", { blob, domain, selector, raw, requester: RELAYER.address })).tx,
    findRecord: async (bh, final) => (await stubCall("/record", { bh, final })).record,
  };
  const dkimKey = await importDkimKey(pem);
  let failBroadcast = false;
  const makeCore = () => {
    const arc = makeArc({ rpc: url, chainId: 5042002, escrow, abi: art.abi, keys: { relayer: K[2], store: K[3] } });
    const real = arc.broadcast;
    arc.broadcast = async (raw) => { if (failBroadcast) { failBroadcast = false; throw new Error("simulated crash before broadcast"); } return real(raw); };
    arcRef = arc;
    const c = new DemoCore({ data, store, arc, gl, dkimKey, log: (t) => say("   worker: " + t) });
    c.debug = !!process.env.DEMO_DEBUG;
    return c;
  };
  let core = makeCore();
  const tick = async () => { try { await core.tick(); } catch (e) { if (!/simulated crash/.test(e.message)) throw e; say("   (crash simulated: the Worker restarts)"); core = makeCore(); } };

  // the visitor: like the page, it remembers what it already sent until the Worker sees it
  const sent = new Map();
  const visitor = async (acct, o) => {
    const v = await core.view(o.order, await now());
    const w = wallet(acct);
    const done = sent.get(o.order) || new Set();
    sent.set(o.order, done);
    if (!v.paid) return;
    const submit = async (s) => {
      if (done.has(s)) return;
      await wait(await w.writeContract({ address: escrow, abi: art.abi, functionName: "submit", args: [o.ref, stringToHex(s)] }));
      done.add(s);
    };
    if (v.next?.action === "claim" && !done.has("claim")) {
      await wait(await w.writeContract({ address: escrow, abi: art.abi, functionName: "openClaim", args: [o.ref, stringToHex(v.next.claim)] }));
      done.add("claim");
      for (const s of v.next.then || []) await submit(s);
    } else if (v.next?.action === "submit") {
      for (const s of v.next.submissions) await submit(s);
    }
  };
  const pay = async (acct, o) => {
    const w = wallet(acct);
    await wait(await w.writeContract({ address: USDC, abi: stable.abi, functionName: "approve", args: [escrow, BigInt(o.pay.amount)] }));
    await wait(await w.writeContract({ address: escrow, abi: art.abi, functionName: "pay",
      args: [o.ref, o.pay.merchant, USDC, BigInt(o.pay.amount), BigInt(o.pay.hold), o.pay.terms_hash] }));
  };
  const settledOf = async (o) => (await core.order(o.order)).settled;
  const verdictsOf = async (o) => (await core.order(o.order)).steps.map((s) => s.final && `${s.final.outcome} ${s.final.refund_cents} ${s.final.reason} ${s.final.action}`);
  const expectedOf = (id) => data.scenarios.find((s) => s.id === id).steps.map((s) => `${s.outcome} ${s.refund_cents} ${s.reason} ${s.action}`);
  const arcTxs = new Map(); // order -> labels of Arc transactions by the Worker (no duplicates allowed)
  const logLabels = async () => { for (const o of await core.orders()) arcTxs.set(o.n, o.events.filter((e) => e.net === "arc" && /^(Store|No-response|Closing|Proof|Verdict|Released|Refunded)/.test(e.what)).map((e) => e.what)); };

  // ---- DEMO2: the five same-day scenarios, two visitors ----------------------------------------------
  say("-- five scenarios on day 0 (N1 N2 N3 D1 D2); N1's first judge step splits (resend)");
  const plan = [["N1", B1], ["N2", B1], ["N3", B1], ["D1", B2], ["D2", B2]];
  const orders = [];
  for (const [sc, acct] of plan) { const o = await core.createOrder(sc, await now()); orders.push({ ...o, sc, acct }); await pay(acct, o); }
  await stubCall("/control", { split_next: true });
  let restarted = false, crashed = false;
  for (let i = 0; i < 120; i++) {
    await tick();
    for (const o of orders) await visitor(o.acct, o);
    // DEMO2 restart: a new Worker instance from the same storage, mid-scenario; and one crash between signing and broadcast
    if (!restarted && (await core.order(orders[1].order)).steps.length === 1) { core = makeCore(); restarted = true; say("   (Worker restarted from storage during N2)"); }
    if (!crashed && (await core.order(orders[3].order)).claim) { failBroadcast = true; crashed = true; }
    if ((await Promise.all(orders.map(settledOf))).every(Boolean)) break;
    await warp(60);
  }
  check(restarted && crashed, "DEMO2 the Worker was restarted mid-scenario and crashed once before a broadcast");
  for (const o of orders) {
    const s = await settledOf(o);
    const exp = data.scenarios.find((x) => x.id === o.sc);
    check(!!s, `DEMO2 ${o.sc} settled`);
    check(JSON.stringify(await verdictsOf(o)) === JSON.stringify(expectedOf(o.sc)),
      `DEMO2 ${o.sc} verdicts as expected: ${(await verdictsOf(o)).join(" / ")}`);
    check(s && s.refund === exp.settle.buyer * 1e4 && s.released === exp.settle.store * 1e4,
      `DEMO6 ${o.sc} settlement: buyer ${s && s.refund / 1e6} store ${s && s.released / 1e6} USDC`);
  }
  const n1 = await core.order(orders[0].order);
  check(n1.steps[0]?.attempts.length === 2 && /no consensus/.test(n1.steps[0].attempts[0].result), "DEMO9 N1 step 1: no consensus, resent once, then accepted");
  check(n1.steps[0].attempts[0].noConsensusAt > 0 && !n1.steps[0].attempts[1].noConsensusAt,
    "DEMO9 the attempt without consensus was marked before Bradbury closed it; the accepted one was not");
  if ((await core.meta()).paused) throw new Error("the Worker stopped: " + (await core.meta()).stop);
  check(n1.events.some((e) => /decided, finalizing/.test(e.what)), "DEMO2 the page saw \"decided, finalizing\" before the final verdict");
  await logLabels();
  const dups = [...arcTxs.entries()].filter(([, l]) => new Set(l).size !== l.length);
  check(dups.length === 0, "DEMO2 no Arc transaction sent twice by the Worker (restart and crash included)");

  // ---- DEMO2 L1: the late path across the UTC day ------------------------------------------------------
  say("-- L1: confirmation on day 0, delivery notice on day 1, claim on day 1");
  // L1 reads the UTC day: start it early in a day, so a run that begins near midnight does not cross it by accident
  { const into = (await now()) % 86400; if (into > 12 * 3600) await warp(86400 - into + 3600); }
  const l1 =await core.createOrder("L1", await now());
  await pay(B3, l1);
  for (let i = 0; i < 10; i++) { await tick(); await warp(60); }
  let v = await core.view(l1.order, await now());
  const l1Views = [structuredClone(v)];
  check(v.next?.action === "wait" && /tomorrow/.test(v.next.text), "DEMO2 L1 day 0: the page says the delivery notice comes tomorrow");
  const t = await now();
  await warp(86400 - (t % 86400) + 7 * 3600); // 07:00 UTC of day 1: more than 6 hours after the payment
  // DEMO11: L1 waits more than 6 hours since payment without a claim and is not refunded
  for (let i = 0; i < 160; i++) {
    await tick();
    l1Views.push(structuredClone(await core.view(l1.order, await now())));
    await visitor(B3, l1);
    if (await settledOf(l1)) break;
    await warp(60);
  }
  const l1o = await core.order(l1.order);
  check(!l1o.refund, "DEMO11 L1 waited past 6 hours from payment for the next-day email and was not refunded");
  check(JSON.stringify(await verdictsOf(l1)) === JSON.stringify(expectedOf("L1")), `DEMO2 L1 verdict: ${(await verdictsOf(l1)).join(" / ")}`);
  const ls = l1o.settled;
  check(ls && ls.refund === 500_000 && ls.released === 500_000, `DEMO6 L1 settlement: buyer ${ls && ls.refund / 1e6} store ${ls && ls.released / 1e6} USDC`);
  check(l1o.mails.confirmed.body.includes("Estimated delivery: " + new Date(l1o.paidAt * 1000).toISOString().slice(0, 10)), "DEMO2 L1 confirmation promises the payment day");

  // ---- DM-P5 / DEMO7: a fourth paid order of the same address the same day -----------------------------
  say("-- limits, a claim outside the scenarios, a payment outside the page");
  const day1 = [];
  for (const sc of ["N1", "N1", "N1", "N1"]) { const o = await core.createOrder(sc, await now()); await pay(B2, o); day1.push(o); }
  const sends0 = (await stubCall("/count", {})).judge_sends;
  // a claim that is not the scenario's text (B3), and an order paid without the page
  const odd = await core.createOrder("N1", await now());
  await pay(B3, odd);
  const stray = { order: "DS-123456", ref: orderRef("DS-123456"), pay: { ...day1[0].pay } };
  await pay(B3, stray);
  await tick();
  const oddClaim = JSON.parse((await core.view(odd.order, await now())).next.claim);
  oddClaim.account = "Something else entirely.";
  await wait(await wallet(B3).writeContract({ address: escrow, abi: art.abi, functionName: "openClaim", args: [odd.ref, stringToHex(cj(oddClaim))] }));
  for (let i = 0; i < 40; i++) { await tick(); await warp(60); }
  const fourth = await core.order(day1[3].order);
  check(fourth.settled && fourth.refund?.reason === "daily_limit" && fourth.settled.refund === 1_000_000,
    "DEMO7 the fourth order of the day is refunded in full by the store (daily limit)");
  const sends1 = (await stubCall("/count", {})).judge_sends;
  const oddo = await core.order(odd.order);
  check(oddo.settled && oddo.refund?.reason === "not_scenario" && oddo.steps.length === 0, "DM-D4 a claim outside the scenarios is not judged and is refunded in full");
  const strayo = await core.byRef(stray.ref);
  check(strayo && strayo.settled && strayo.refund?.reason === "not_scenario", "DM-D4 a payment made outside the page is refunded in full");
  check(sends1 - sends0 === 0, `DEMO7 refunds by the store use no GEN (judge sends while they ran: ${sends1 - sends0}; the 3 orders within the limit have no claim yet)`);
  for (const o of [fourth, oddo]) {
    const pv = await core.view(o.n, await now());
    check(pv.refund && pv.refund.text === REFUND_TEXT[o.refund.reason] && pv.steps.every((s) => !s.final && !s.decided),
      `DEMO12 the page shows "${pv.refund?.text}" and no verdict`);
  }

  // ---- DEMO11: the stall refund counts from the last step of the claim ---------------------------------
  say("-- stall: the judge never finishes");
  await warp(86400);
  const slow = await core.createOrder("N1", await now());
  await pay(B1, slow);
  await stubCall("/control", { hold: true });
  for (let i = 0; i < 8; i++) { await tick(); await visitor(B1, slow); await warp(60); }
  const last = (await core.order(slow.order)).lastStepAt;
  await warp(last + 6 * 3600 - 60 - (await now())); // 5 h 59 min after the last step
  await tick();
  check(!(await core.order(slow.order)).refund, "DEMO11 at 5 h 59 min after the last step of the claim: not refunded");
  await warp(90);
  for (let i = 0; i < 4; i++) { await tick(); await warp(30); }
  const so = await core.order(slow.order);
  check(so.refund?.reason === "judge_slow" && so.settled?.refund === 1_000_000, "DEMO11 at 6 hours without a new step: refunded in full by the store");
  const sv = await core.view(slow.order, await now());
  check(sv.refund.text === "Refunded by the demo store: the judge did not finish in time", "DEMO12 the page names it a refund by the store");
  await stubCall("/control", { hold: false });

  // ---- DEMO8: isolation --------------------------------------------------------------------------------
  say("-- isolation");
  const ev = l1o.mails.delivered;
  const iso = await stubCall("/isolation", { evidence: cj({ party: "buyer", kind: "evidence", content: { record_id: ev.record, body_b64: Buffer.from(ev.body, "latin1").toString("base64") } }) });
  const ign = iso.verdict?.ignored || [];
  check(iso.verdict && ign.length === 1 && ign[0][1] === "I5", `DEMO8 a demo-key email as evidence for the live store is ignored (${JSON.stringify(ign.map((x) => x[1]))}, ${iso.verdict?.outcome})`);
  let refused = 0;
  try { await arcRef.prepare("relayer", "withdraw", [USDC]); } catch { refused++; }
  try { await arcRef.prepare("store", "proposeVerdict", [l1.ref, 1, 1, "0x" + "0".repeat(64), "0x" + "0".repeat(64), "0x" + "0".repeat(64)]); } catch { refused++; }
  check(refused === 2, "DEMO8 the Worker refuses to sign anything outside its list (relayer withdraw, store proposeVerdict)");
  // ---- The page: N1 driven through site/app.js and site/demo-shop.js, the visitor's wallet on anvil --------
  say("-- the page's Demo Shop, end to end (N1)");
  await pageRun({ core, pub, wallet, now, warp, tick: () => tick(), data, escrow, art, stable, split: () => stubCall("/control", { split_next: true }),
    l1: { order: l1.order, views: l1Views } });

  const meta = await core.meta();
  check(!meta.paused, "no stop raised during the rehearsal" + (meta.stop ? ": " + meta.stop : ""));
  const counts = await stubCall("/count", {});
  check(counts.early_final_reads === 0, `DEMO4 every verdict and Lacre record the Worker used was read with its transaction FINALIZED (early final reads: ${counts.early_final_reads})`);
  say(`judge sends ${counts.judge_sends}, Lacre attestations ${counts.attests}`);
}

// The page's own code (site/app.js and site/demo-shop.js) in a small DOM stand-in. Its API calls go to the
// same routes as worker/src/index.js, served by the rehearsal's core; its wallet is B1 on anvil.
async function pageRun({ core, pub, wallet, now, warp, tick, data, escrow, art, stable, split, l1 }) {
  const vm = await import("node:vm");
  const els = {};
  const el = (id) => els[id] || (els[id] = { id, innerHTML: "", textContent: "", hidden: false, disabled: false, href: "", title: "", style: {},
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {}, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } });
  const screens = ["overview", "how-it-works", "order-flow", "live-cases", "case", "judges", "measurements", "contracts", "resources", "demo-shop", "my-orders"]
    .map((s) => Object.assign(el("screen-" + s), { getAttribute: (k) => (k === "data-screen" ? s : null) }));
  const listeners = {};
  const ls = new Map();
  // Circle, simulated: its REST API (behind the Worker's own routes, worker/src/circle.js) and its Web SDK.
  // A contract execution approved in "Circle's window" is sent from CIRCLE_USER on anvil.
  const sim = { pending: new Map(), done: new Map(), execs: [], init: null, walletMade: false, sdk: [] };
  const circleRest = async (url, init) => {
    const path = url.replace("https://api.circle.com", "");
    const body = init.body ? JSON.parse(init.body) : null;
    const ok = (d) => ({ ok: true, status: 200, json: async () => ({ data: d }) });
    if (path === "/v1/w3s/users/social/token") return ok({ deviceToken: "dt-test", deviceEncryptionKey: "dk-test" });
    if (path === "/v1/w3s/user/initialize") { sim.init = body; return ok({ challengeId: "c-init" }); }
    if (path.startsWith("/v1/w3s/wallets")) return ok({ wallets: sim.walletMade ? [{ id: "w-c", address: CIRCLE_USER.address, blockchain: "ARC-TESTNET", accountType: "EOA", state: "LIVE" }] : [] });
    if (path === "/v1/w3s/user/transactions/contractExecution") {
      const id = "c-" + (sim.pending.size + 1);
      sim.pending.set(id, body); sim.execs.push(body);
      return ok({ challengeId: id });
    }
    if (path.startsWith("/v1/w3s/user/challenges/")) {
      const id = decodeURIComponent(path.split("/").pop()), h = sim.done.get(id);
      return ok({ challenge: { id, type: "CONTRACT_EXECUTION", status: h ? "COMPLETE" : "PENDING", correlationIds: h ? ["t-" + id] : [] } });
    }
    if (path.startsWith("/v1/w3s/transactions/")) return ok({ transaction: { state: "COMPLETE", txHash: sim.done.get(path.split("/").pop().slice(2)) } });
    return { ok: false, status: 404, json: async () => ({ code: 0, message: "no route " + path }) };
  };
  const circleWorker = makeCircle({ apiKey: "TEST_API_KEY:x:y", escrow, usdc: data.addresses.usdc, abi: art.abi, fetchImpl: circleRest });
  class W3SSdk {
    constructor(configs, onLogin) {
      this.configs = configs;
      if (onLogin && /id_token=/.test(ctx.location.hash)) {
        setTimeout(() => { ctx.location.hash = ""; onLogin(undefined, { userToken: "ut-test", encryptionKey: "ek-test", refreshToken: "rt-test" }); }, 10);
      }
    }
    getDeviceId() { return Promise.resolve("device-test"); }
    updateConfigs(c) { this.configs = c; }
    performLogin(provider) { sim.sdk.push(["login", provider, this.configs]); ctx.location.hash = "#id_token=token-test&state=state-test"; return Promise.resolve(); }
    setAuthentication(a) { this.auth = a; }
    execute(id, cb) {
      sim.sdk.push(["execute", id, this.auth]);
      (async () => {
        if (id === "c-init") { sim.walletMade = true; return cb(undefined, { type: "INITIALIZE", status: "COMPLETE" }); }
        const b = sim.pending.get(id);
        const h = await wallet(CIRCLE_USER).sendTransaction({ to: b.contractAddress, data: b.callData });
        await pub.waitForTransactionReceipt({ hash: h });
        sim.done.set(id, h);
        cb(undefined, { type: "CONTRACT_EXECUTION", status: "COMPLETE" });
      })().catch((e) => cb({ message: e.message }, undefined));
    }
  }
  const api = async (path, init = {}) => {
    const u = new URL(path, "http://demo");
    if (u.pathname.startsWith("/api/circle/")) {
      const r = await circleApi(circleWorker, u.pathname.slice("/api/circle/".length), JSON.parse(init.body || "{}"));
      return { ok: r.status < 400, status: r.status, json: async () => structuredClone(r.body) };
    }
    const t = await now();
    let body;
    if (u.pathname === "/api/config") {
      body = { chain_id: 5042002, amount_cents: data.amount_cents, windows_seconds: data.windows_seconds, limits: data.limits,
        addresses: data.addresses, refund_texts: REFUND_TEXT, paused: null, scenarios: data.scenarios };
    } else if (u.pathname === "/api/quota") body = await core.quota(u.searchParams.get("address"), t);
    else if (u.pathname === "/api/account") body = net.workerDown ? { error: "unreachable" } : await core.arc.account(u.searchParams.get("address"), data.addresses.usdc);
    else if (u.pathname === "/api/orders" && init.method === "POST") body = await core.createOrder(JSON.parse(init.body).scenario, t);
    // Orders by buyer: served only for the check below, so the earlier checks see the page's own list
    else if (u.pathname === "/api/orders") body = net.ordersByBuyer ? { orders: await core.ordersOf(u.searchParams.get("buyer")) } : { error: "off" };
    else body = (await core.view(u.pathname.split("/").pop(), t)) || { error: "no such order" };
    return { ok: true, json: async () => structuredClone(body), text: async () => JSON.stringify(body) };
  };
  const READS = ["eth_getBalance", "eth_call", "eth_getTransactionReceipt"];
  const net = { walletReadsDown: false, publicRpcDown: false, workerDown: false, circleOn: false, ordersByBuyer: false }; // a broken wallet RPC, Arc's public RPC down, the Worker's read down; Circle set up
  const ethereum = {
    on() {},
    request: async ({ method, params }) => {
      if (net.walletReadsDown && READS.includes(method)) throw new Error("wallet RPC unreachable");
      if (method === "eth_requestAccounts" || method === "eth_accounts") return [B1.address];
      if (method === "eth_chainId") return "0x4cef52";
      if (method === "eth_sendTransaction") return wallet(B1).sendTransaction({ to: params[0].to, data: params[0].data });
      return pub.request({ method, params });
    },
  };
  const window = { addEventListener: (n, f) => { listeners[n] = f; }, scrollTo() {}, matchMedia: () => ({ matches: true }), devicePixelRatio: 1, ethereum };
  const document = {
    getElementById: el,
    querySelectorAll: (sel) => (sel === ".screen[data-screen]" ? screens : []),
    querySelector: (sel) => (sel.includes("tenet-demo-api") ? { content: "http://demo" }
      : sel.includes("tenet-circle") && net.circleOn ? { content: "app-test|client-test.apps.googleusercontent.com" } : null),
    addEventListener() {}, createElement: () => el("tmp"),
  };
  const ss = new Map();
  const ctx = { window, document, location: { hash: "", origin: "http://127.0.0.1:8000" }, navigator: {}, console, Date, JSON, Math, Number, String, Object, Array, RegExp, BigInt, Promise,
    isFinite, encodeURIComponent, decodeURIComponent, TextEncoder, URL, performance: { now: () => 0 }, requestAnimationFrame: () => 0,
    cancelAnimationFrame() {}, setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
    localStorage: { getItem: (k) => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, String(v)), removeItem: (k) => ls.delete(k) },
    sessionStorage: { getItem: (k) => (ss.has(k) ? ss.get(k) : null), setItem: (k, v) => ss.set(k, String(v)), removeItem: (k) => ss.delete(k) },
    fetch: async (u, init) => {
      if (String(u).startsWith("http://demo")) return api(String(u).slice("http://demo".length), init);
      if (String(u) === "https://rpc.testnet.arc.io") { // the page's reads of Arc, served by anvil
        if (net.publicRpcDown) throw new TypeError("Failed to fetch");
        const b = JSON.parse(init.body);
        const result = await pub.request({ method: b.method, params: b.params });
        return { ok: true, json: async () => ({ jsonrpc: "2.0", id: b.id, result }) };
      }
      return { ok: true, text: async () => readFileSync(P("site/data/tenet.json"), "utf8") };
    } };
  ctx.window.document = document;
  ctx.window.TenetCircleSdk = { W3SSdk, SocialLoginProvider: { GOOGLE: "Google" } };
  vm.createContext(ctx);
  for (const f of ["site/circle.js", "site/demo-shop.js", "site/app.js"]) vm.runInContext(readFileSync(P(f), "utf8"), ctx, { filename: f });
  const settle = () => new Promise((r) => setTimeout(r, 400));
  await settle();
  ctx.location.hash = "#demo-shop";
  listeners.hashchange();
  await settle();
  ctx.window.connectWallet();
  await settle();
  const T = ctx.window.TenetShop;
  const act = async (kind, arg) => { T._act(kind, arg); for (let i = 0; i < 60 && T._state.busy; i++) await settle(); await settle(); };
  // Reads: Arc's public RPC first, the wallet as fallback; when both fail the page says so instead of showing 0
  const W = ctx.window.TenetUI.wallet, shop = () => el("screen-demo-shop").innerHTML;
  const onChain = Number(BigInt(await pub.getBalance({ address: B1.address })) / 10n ** 16n) / 100;
  const owed = Number(await pub.readContract({ address: escrow, abi: art.abi, functionName: "claimable",
    args: [B1.address, "0x3600000000000000000000000000000000000000"] })) / 1e6;
  net.walletReadsDown = true; W.balance = null; T._state.claimable = null; await act("refresh");
  check(W.balance === onChain && T._state.claimable === owed && !W.balanceErr,
    `PAGE with the wallet's Arc RPC down, balance (${W.balance}) and credit (${T._state.claimable}) read through Arc's public RPC`);
  net.walletReadsDown = false; net.publicRpcDown = true; W.balance = null; T._state.claimable = null; await act("refresh");
  check(W.balance === onChain && T._state.claimable === owed, "PAGE with Arc's public RPC down, the reads fall back to the wallet");
  net.walletReadsDown = true; W.balance = null; T._state.claimable = null; await act("refresh");
  check(W.balance === onChain && !W.balanceErr && T._state.claimable === owed && el("wallet-bal").textContent === onChain.toFixed(2) + " USDC",
    "PAGE with the public RPC and the wallet both down, balance and credit come through the Worker's read");
  net.workerDown = true; W.balance = null; T._state.claimable = null; await act("refresh");
  check(W.balance === null && W.balanceErr && T._state.claimable === null && /Could not read the escrow on Arc; retrying\./.test(shop())
    && el("wallet-bal").textContent === "balance unavailable", "PAGE with every read down, the page says the reads failed instead of showing 0");
  net.walletReadsDown = false; net.publicRpcDown = false; net.workerDown = false; await act("refresh");
  check(W.balance === onChain && !W.balanceErr && T._state.claimable === owed, "PAGE the reads recover on the next refresh");
  const html = () => el("screen-demo-shop").innerHTML;
  check((html().match(/data-try="start"/g) || []).length === 6 && /Demo Shop/.test(html()) && (html().match(/<svg class="try-art-svg"/g) || []).length === 6
    && !/undefined|NaN/.test(html()), "PAGE the Demo Shop lists six products, each with its illustration and a Buy button");
  const usdcOf = async () => pub.readContract({ address: "0x3600000000000000000000000000000000000000", abi: stable.abi, functionName: "balanceOf", args: [B1.address] });
  const credited = async () => pub.readContract({ address: escrow, abi: art.abi, functionName: "claimable",
    args: [B1.address, "0x3600000000000000000000000000000000000000"] });
  const before = await usdcOf(), creditedBefore = await credited();
  // Buy: the order is created and paid in the same click, then the page opens it in My orders
  await act("start", "N1");
  const order = JSON.parse(ctx.localStorage.getItem("tenet-demo-orders")).pop().order;
  check(T._state.note?.tone === "ok" && /paid on Arc/.test(T._state.note.text) && T._state.note.text.includes(order),
    `PAGE Buy creates order ${order} and pays it from the wallet in one click (${T._state.note?.text})`);
  for (let i = 0; i < 4; i++) await settle();
  check(ctx.location.hash === "#my-orders/" + order, `PAGE after Buy the page opens the order in My orders (${ctx.location.hash})`);
  listeners.hashchange();
  await settle();
  const mo = () => el("screen-my-orders").innerHTML;
  const cnt = el("nav-orders-count");
  const cur = () => (mo().match(/<li class="cur" aria-current="step">.*?<span class="t">([^<]+)<\/span>/) || [])[1];
  let wasClaimed = false;
  let claimed = false, sawCounter = false, sawNoConsensus = false, sawFinalizing = false, sawClaimNote = false, staleNote = false;
  await split(); // the order's first judge attempt gets no consensus, as DS-984327's did on Bradbury
  const phases = new Set();
  for (let i = 0; i < 40; i++) {
    await tick();
    await act("refresh");
    const v = T._state.views[order] || {};
    if (cur()) phases.add(cur());
    if (/claim registered on Arc\. The demo store answers next\./.test(mo())) { if (cur() === "Judge" || cur() === "Settled") staleNote = true; else sawClaimNote = true; }
    if (/No consensus on the first attempt\. Bradbury closes it after about 30 min, then the step is sent again\./.test(mo())
      && /Until Bradbury closes the attempt/.test(mo()) && /data-bar-after="Closing, then sent again"/.test(mo())) sawNoConsensus = true;
    if (/Decided, finalizing: REFUND 1\.00 USDC\. The payment waits for the final verdict: GenLayer makes it final in about 30 min, then the escrow pays\./.test(mo())
      && /Until the verdict is final/.test(mo()) && /data-bar-after="Finalizing, almost there"/.test(mo())) sawFinalizing = true;
    if (v.paid && !v.settled && !cnt.hidden && cnt.textContent === "1" && cnt.title.includes(order)) sawCounter = true;
    if (!claimed && v.next?.action === "claim") {
      check(/data-try="claim"/.test(mo()) && /View exact text/.test(mo()), "PAGE the order offers one button, Open a claim, with the exact text folded");
      await act("claim", order); claimed = true;
      if (/claim registered on Arc\. The demo store answers next\./.test(mo())) sawClaimNote = true;
    }
    if (v.settled) break;
    await warp(60);
  }
  await act("refresh");
  const v = T._state.views[order];
  check(claimed && v?.settled?.refund === 1_000_000, "PAGE N1 through the page: claim signed by the visitor, REFUND 1.00 USDC settled");
  check(sawCounter, "PAGE while the order runs, the sidebar counter shows 1 with the order number on hover");
  check(sawNoConsensus && v.steps[0]?.attempts.length === 2, "PAGE a first attempt without consensus shows its line and time bar until Bradbury closes it; then the step is sent again");
  check(sawFinalizing, "PAGE a decided verdict shows that the payment waits for the final verdict (about 30 min), with its time bar");
  check(sawClaimNote && !staleNote, `PAGE the note left by the claim shows next to the button and goes once the order moves on to the judge (shown ${sawClaimNote}, stale ${staleNote})`);
  // L1 in My orders, rendered from the Worker's view at each moment of the run above
  const labels = (h) => [...h.matchAll(/<span class="t">([^<]+)<\/span><\/li>/g)].map((m) => m[1]);
  const curOf = (h) => (h.match(/<li class="cur" aria-current="step">.*?<span class="t">([^<]+)<\/span>/) || [])[1] || "";
  const card = (view) => { T._state.views[l1.order] = view; return T._card({ order: l1.order, scenario: "L1" }, Date.now() / 1000); };
  const l1Cards = l1.views.map(card);
  const n1Labels = labels(mo());
  check(l1Cards.every((h) => labels(h).join(",") === "Paid,Store emails,Claim,Judge,Settled") && n1Labels.join(",") === "Paid,Claim,Store answer,Judge,Settled",
    `PAGE L1's track is Paid, Store emails, Claim, Judge, Settled; the other paths keep their five steps (${n1Labels.join(", ")})`);
  const l1Cur = l1Cards.map(curOf);
  check(l1Cur[0] === "Store emails" && /Order confirmed/.test(l1Cards[0]) && /signed by the store/.test(l1Cards[0]) && /sent the day after the payment/.test(l1Cards[0])
    && /badge-lacre/.test(l1Cards[0]), `PAGE L1 day 0: Store emails is the current step, the confirmation is signed by the store and the delivery notice comes the next day (${l1Cur[0]})`);
  const both = l1Cards.find((h) => (h.match(/verified by Lacre \(record \d+\)/g) || []).length === 2);
  check(!!both && (both.match(/explorer-bradbury\.genlayer\.com\/tx\/0x[0-9a-f]+/g) || []).length >= 2,
    "PAGE L1: each store email shows signed by the store, verified by Lacre and a link to its attestation on Bradbury");
  const verifying = l1Cards.find((h) => /verifying on Lacre/.test(h));
  check(!!verifying && /Until the attestation is final/.test(verifying) && /about 30 min after it is sent/.test(verifying)
    && !l1Cards.some((h) => /Until the attestation is final/.test(h) && !/verifying on Lacre/.test(h)),
    "PAGE L1: an email still verifying on Lacre says what is happening, with a time bar until the attestation is final");
  check(l1Cards.some((h) => /Open a claim: the judge reads the store&#39;s 2 signed emails, sent with it as evidence, one transaction each\./.test(h)
    || /Open a claim: the judge reads the store's 2 signed emails, sent with it as evidence, one transaction each\./.test(h))
    && !l1Cards.some((h) => /with the store(&#39;|')s answer/.test(h)),
    "PAGE L1: Open a claim says the judge reads the store's signed emails, never a store answer");
  check(/class="badge badge-arc"[^>]*><svg class="ic arc-logo"[^>]*viewBox="0 0 164 171"[\s\S]*?<span>Arc Network<\/span><\/span>/.test(html()),
    "PAGE the Arc badge reads Arc Network, with Arc's official icon");
  check(l1Cur.includes("Claim") && l1Cur.includes("Judge") && !l1Cur.includes("Store answer")
    && (l1Cards[l1Cards.length - 1].match(/<li class="done">/g) || []).length === 5,
    `PAGE L1 moves through Claim and Judge to Settled, never through a store answer (${[...new Set(l1Cur)].join(", ")})`);
  check(["Claim", "Judge"].every((p) => phases.has(p)), `PAGE the order's track moved through its phases (${[...phases].join(", ")})`);
  check(mo().includes("Order <b>" + order + "</b>") && (mo().match(/<li class="done">/g) || []).length === 5
    && /REFUND 1\.00 USDC refunded to you/.test(mo()) && /Go to withdraw/.test(mo()) && !/undefined|NaN/.test(mo())
    && !(/Store answered/.test(mo()) && /Registered: response \(store\)/.test(mo())) && !(/Verdict executed/.test(mo()) && /Settled on Arc/.test(mo())),
    "PAGE the settled order shows its number, five phases done, the refund and Go to withdraw; one timeline line per Arc transaction");
  check(cnt.hidden, "PAGE the sidebar counter is off once the order is settled");
  const creditedNow = await credited();
  T._act("goto-withdraw");
  check(ctx.location.hash === "#demo-shop", "PAGE Go to withdraw leads to the Demo Shop");
  listeners.hashchange();
  await settle(); await settle();
  check(creditedNow - creditedBefore === 1_000_000n && Math.abs((T._state.claimable || 0) - Number(creditedNow) / 1e6) < 1e-9
    && /id="try-credited"/.test(html()) && /try-flash/.test(html()) && /btn-go" data-try="withdraw"/.test(html()),
    `PAGE the refund is credited in the escrow (+1.00 USDC; ${Number(creditedNow) / 1e6} USDC in total from this rehearsal), the card is highlighted and Withdraw is lit`);
  await act("withdraw");
  const after = await usdcOf();
  check(after - before === creditedNow - 1_000_000n && (await credited()) === 0n && /is-done" disabled>.*Withdrawn/.test(html()),
    `PAGE Withdraw from the page: the wallet receives everything credited, nothing left in the escrow, the button says Withdrawn`);
  // A wallet with the old Arc RPC: the page says which RPC to set; other errors keep their own text
  check(/https:\/\/rpc\.testnet\.arc\.io/.test(T._reason({ message: "RPC 0x4cef52 Custom eth_getBlockByNumber: RPC endpoint returned too many errors" }))
    && T._reason({ message: "The transaction reverted on Arc." }) === "The transaction reverted on Arc."
    && /rpc\.testnet\.arc\.io/.test(html()) && /older <span class="mono">rpc\.testnet\.arc\.network<\/span> no longer answers/.test(html()),
    "PAGE the Demo Shop names the RPC a wallet's Arc network needs, and a wallet that cannot reach Arc gets that instruction");
  // Another browser: nothing saved locally, the wallet's paid orders come from the Worker
  const byBuyer = await core.ordersOf(B1.address.toLowerCase());
  ctx.localStorage.removeItem("tenet-demo-orders");
  T._state.views = {}; T._state.remote = null;
  net.ordersByBuyer = true;
  ctx.location.hash = "#my-orders"; listeners.hashchange();
  await act("refresh");
  check(byBuyer.some((o) => o.order === order && o.scenario === "N1" && o.paid_at > 0) && mo().includes("Order <b>" + order + "</b>")
    && /REFUND 1\.00 USDC refunded to you/.test(mo()) && /Every order this wallet paid, from any browser/.test(mo()),
    `PAGE from another browser (empty local list) My orders still shows ${order}, from the Worker's orders of this wallet (${byBuyer.length} paid by it)`);
  net.ordersByBuyer = false; T._state.remote = null;

  // ---- Circle wallet: sign in with Google, then a D1 order of the Demo Shop end to end ------------------
  net.circleOn = true;
  const C = ctx.window.TenetCircle;
  W.disconnect();
  ctx.window.connectWallet();
  check(el("connect-modal").hidden === false, "PAGE CIRCLE Connect opens the window with Continue with Google and Browser wallet");
  ctx.location.hash = "#demo-shop";
  W.connectCircle();
  await settle();
  const login = sim.sdk.find((x) => x[0] === "login"), lc = login && login[2].loginConfigs;
  check(login && login[1] === "Google" && lc.google.clientId === "client-test.apps.googleusercontent.com" && lc.google.redirectUri === ctx.location.origin
    && lc.deviceToken === "dt-test" && el("connect-modal").hidden === true,
    "PAGE CIRCLE Google sign-in with the site's client id, a Circle device token, and the site's root as the way back");
  W.restore(); // the page loads again with Google's answer in the address
  for (let i = 0; i < 20 && W.status !== "connected"; i++) await settle();
  check(W.kind === "circle" && W.address === CIRCLE_USER.address && sim.init && sim.init.accountType === "EOA"
    && JSON.stringify(sim.init.blockchains) === '["ARC-TESTNET"]' && ctx.location.hash === "#demo-shop" && C.session()?.address === CIRCLE_USER.address,
    "PAGE CIRCLE back from Google: Circle creates an EOA wallet on Arc testnet, the page connects it and returns to the Demo Shop");
  listeners.hashchange(); await settle(); await act("refresh");
  const usdcOfC = async () => pub.readContract({ address: "0x3600000000000000000000000000000000000000", abi: stable.abi, functionName: "balanceOf", args: [CIRCLE_USER.address] });
  const c0 = await usdcOfC();
  await act("start", "D1");
  const orderC = JSON.parse(ctx.localStorage.getItem("tenet-demo-orders")).pop().order;
  check(T._state.note?.tone === "ok" && sim.execs.length === 2 && sim.execs.every((x) => x.walletId === "w-c" && x.feeLevel === "MEDIUM"),
    `PAGE CIRCLE Buy ${orderC}: approve and pay, each approved in the Circle window and sent by Circle (${sim.execs.length} transactions)`);
  for (let i = 0; i < 45; i++) {
    await tick();
    await act("refresh");
    const vc = T._state.views[orderC] || {};
    if (vc.next?.action === "claim" && !wasClaimed) { await act("claim", orderC); wasClaimed = true; }
    if (vc.settled) break;
    await warp(60);
  }
  const vC = T._state.views[orderC];
  check(wasClaimed && vC?.settled?.refund === 1_000_000 && sim.execs.length === 3,
    "PAGE CIRCLE D1: the claim is signed through Circle and the order settles with REFUND 1.00 USDC");
  await act("withdraw");
  check((await usdcOfC()) === c0 && sim.execs.length === 4 && (await pub.readContract({ address: escrow, abi: art.abi, functionName: "claimable",
    args: [CIRCLE_USER.address, "0x3600000000000000000000000000000000000000"] })) === 0n,
    "PAGE CIRCLE Withdraw through Circle: the 1.00 USDC is back in the Circle wallet, nothing left in the escrow");
  const refused = await C.send("0x" + "33".repeat(20), "0x12345678").then(() => false, (e) => /not a Demo Shop call/.test(e.message));
  check(refused && sim.execs.length === 4, "PAGE CIRCLE a call outside the Demo Shop is refused by the Worker before it reaches Circle");
  W.disconnect();
  check(!C.session() && W.kind === "browser" && W.status === "idle", "PAGE CIRCLE disconnect ends the Circle session in this tab");
  net.circleOn = false;
}

main().catch((e) => { console.error(e); say("REHEARSAL ERROR: " + (e.stack || e.message)); writeFileSync(P("results/demo-rehearsal.txt"), lines.join("\n") + "\n"); process.exit(2); });
