// The demo store and relayer as one state machine (README.md, "The Demo Shop runs on minutes"). Every network call goes through
// three adapters, so the same code runs in the Cloudflare Worker and in the local rehearsal:
//   arc   Arc testnet (or anvil): reads, events and signed transactions of the demo relayer and store
//   gl    GenLayer Bradbury (or the simulated judges): judge steps, verdicts, Lacre attestations
//   store persistent key-value storage (a Durable Object, or memory in the rehearsal)
// One tick() runs every minute. It never sends a transaction twice: every Arc transaction is signed
// and stored before it is broadcast, and every Bradbury send is recorded before and after.
import { cj, shaText, chain0, fold, orderRef, isoDay, b64, latin1, lower, signMail, mailDate } from "./util.js";

const OUTCOME = { REFUND: 1, DENY: 2, INVALID_CLAIM: 3 };
const MAX_ATTEMPTS = 3;
// An attempt in one of these has no consensus; Bradbury closes it (FINALIZED) after about 30 minutes, and only then is it resent.
const NO_CONSENSUS_STATUS = new Set(["UNDETERMINED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"]);
const NO_CONSENSUS_RESULT = new Set(["NO_MAJORITY", "MAJORITY_DISAGREE"]);
export const REFUND_TEXT = {
  daily_limit: "Refunded by the demo store: daily limit reached",
  judge_slow: "Refunded by the demo store: the judge did not finish in time",
  not_scenario: "Refunded by the demo store: the claim is not one of the demo scenarios",
};

export class DemoCore {
  constructor({ data, store, arc, gl, dkimKey, log = () => {} }) {
    this.d = data;
    this.s = store;
    this.arc = arc;
    this.gl = gl;
    this.dkimKey = dkimKey;
    this.log = log;
    this.scen = Object.fromEntries(data.scenarios.map((x) => [x.id, x]));
  }

  // ---- storage ---------------------------------------------------------------------------------

  async meta() {
    return (await this.s.get("meta")) || { block: null, paused: false, stop: null, failures: 0, created: {} };
  }
  async order(n) { return this.s.get("o:" + n); }
  async saveOrder(o) { await this.s.put("o:" + o.n, o); }
  async orders() { return (await this.s.list("o:")).sort((a, b) => a.createdAt - b.createdAt); }
  async byRef(ref) {
    const n = await this.s.get("r:" + lower(ref));
    return n ? this.order(n) : null;
  }

  // ---- API: orders created by the demo page -----------------------------------------------------

  /** A new order for a scenario. Only the page creates orders; payment is done by the visitor. */
  async createOrder(scenario, now) {
    if (!this.scen[scenario]) throw new Error("unknown scenario");
    const meta = await this.meta();
    const day = isoDay(now);
    meta.created[day] = (meta.created[day] || 0) + 1;
    if (meta.created[day] > 10 * this.d.limits.per_day) throw new Error("too many orders created today");
    let n;
    do { n = "DS-9" + String(Math.floor(Math.random() * 1e5)).padStart(5, "0"); } while (await this.order(n));
    const o = { n, ref: orderRef(n), scenario, createdAt: Number(now), events: [], subs: [], steps: [], mails: {} };
    await this.saveOrder(o);
    await this.s.put("r:" + lower(o.ref), n);
    await this.s.put("meta", meta);
    const a = this.d.addresses;
    return { order: n, ref: o.ref, pay: { escrow: a.escrow, merchant: a.store, token: a.usdc,
      amount: this.d.amount_cents * 1e4, hold: this.d.terms.hold_seconds, terms_hash: this.d.terms.terms_hash } };
  }

  /** Paid orders of an address today, and of everyone today (DM-P5). */
  async quota(address, now) {
    const day = isoDay(now);
    const paid = (await this.orders()).filter((o) => o.paidAt && isoDay(o.paidAt) === day && o.refund?.reason !== "not_scenario");
    return { address: paid.filter((o) => lower(o.buyer) === lower(address)).length, total: paid.length,
             per_address: this.d.limits.per_address_per_day, per_day: this.d.limits.per_day };
  }

  // ---- texts ---------------------------------------------------------------------------------------

  /** The claim text of the order's scenario, as relayer/e2e.py builds it, for a given claimed_at. */
  claimText(o, claimedAt) {
    const sc = this.scen[o.scenario];
    const cl = { v: "claim-v1", order_ref: o.ref, order_number: o.n, buyer: lower(o.buyer), merchant: lower(this.d.addresses.store),
      amount_cents: o.amount / 1e4, paid_at: o.paidAt, claimed_at: Number(claimedAt), terms_hash: lower(o.termsHash), event: sc.event };
    const paid = isoDay(o.paidAt);
    if (sc.event === "not_as_described") {
      const c = sc.claim;
      Object.assign(cl, { description: c.description, account: c.account, promised: c.promised, received: c.received,
        proof_kind: c.proof_kind, proof: c.proof, delivered_date: paid });
    } else if (sc.event === "not_delivered") {
      Object.assign(cl, { account: sc.account, promised_date: paid });
    }
    return cj(cl);
  }

  /** Submissions the visitor may register for this order, in canonical JSON. */
  buyerSubs(o) {
    const sc = this.scen[o.scenario];
    if (sc.event === "late") {
      return ["confirmed", "delivered"].filter((k) => o.mails[k]?.record).map((k) =>
        cj({ party: "buyer", kind: "evidence", content: { record_id: String(o.mails[k].record), body_b64: b64(latin1(o.mails[k].body)) } }));
    }
    if (sc.closing) return [cj({ party: "buyer", kind: "closing_proof", content: sc.closing.buyer })];
    return [];
  }

  storeSub(kind, text) { return cj({ party: "merchant", kind, content: text }); }

  // ---- the tick --------------------------------------------------------------------------------------

  async tick() {
    const meta = await this.meta();
    if (meta.paused) return { paused: meta.stop };
    const now = await this.arc.now();
    await this.resolveArc(meta);
    await this.scan(meta, now);
    await this.s.put("meta", meta); // the scan is not repeated even if this tick stops later
    const budget = { relayer: 4, store: 4, gl: 1 };
    for (const o of await this.orders()) {
      if (meta.paused) break;
      if (!o.paidAt || o.settled) continue;
      try {
        await this.stepOrder(o, now, budget, meta);
      } finally {
        await this.saveOrder(o);
      }
    }
    await this.s.put("meta", meta);
    return { now, paused: meta.paused ? meta.stop : null };
  }

  pause(meta, reason) {
    meta.paused = true;
    meta.stop = reason;
    this.log("STOP: " + reason);
  }

  event(o, at, what, extra = {}) { o.events.push({ at: Number(at), what, ...extra }); }

  // ---- Arc transactions: signed and stored first, then broadcast --------------------------------------

  async send(meta, who, o, fn, args, label) {
    const pending = await this.s.get("tx:" + who);
    if (pending) { if (this.debug) this.log(`busy ${who} (${pending.label} ${pending.order}) for ${label} ${o?.n || ""}`); return false; }
    let prep;
    try {
      prep = await this.arc.prepare(who, fn, args);
    } catch (e) {
      meta.failures = (meta.failures || 0) + 1;
      this.log(`NOT SENT ${label} ${o?.n || ""} (claim at ${o?.claim?.at ?? "-"}, now ${await this.arc.now()}): ${e.message}`);
      if (meta.failures >= 2) this.pause(meta, `two transactions in a row would revert (${label}: ${e.message})`);
      return false;
    }
    if (this.debug) this.log(`send ${who} ${label} ${o?.n || ""}`);
    await this.s.put("tx:" + who, { ...prep, who, order: o?.n || null, label, fn });
    await this.arc.broadcast(prep.raw);
    if (o) this.event(o, await this.arc.now(), label, { tx: prep.hash, net: "arc" });
    // Arc confirms in under a second: wait for the receipt here, so the key is free for the next one.
    const r = await this.arc.waitReceipt(prep.hash, 10_000);
    if (r) await this.settleArc(meta, who, { ...prep, label, order: o?.n || null }, r);
    return true;
  }

  async settleArc(meta, who, p, r) {
    await this.s.delete("tx:" + who);
    if (r.status !== "success") {
      meta.failures = (meta.failures || 0) + 1;
      this.log(`REVERTED ${p.label} ${p.order}: ${p.hash}`);
      if (meta.failures >= 2) this.pause(meta, `two transactions in a row reverted (${p.label})`);
    } else {
      meta.failures = 0;
    }
  }

  async resolveArc(meta) {
    for (const who of ["relayer", "store"]) {
      const p = await this.s.get("tx:" + who);
      if (!p) continue;
      let r = await this.arc.receipt(p.hash);
      if (!r) {
        await this.arc.broadcast(p.raw); // the same signed transaction again: never a second one
        r = await this.arc.receipt(p.hash);
        if (!r) continue;
      }
      await this.settleArc(meta, who, p, r);
    }
  }

  // ---- events of the demo escrow -----------------------------------------------------------------------

  async scan(meta, now) {
    const latest = await this.arc.latestBlock();
    let from = meta.block == null ? (this.d.addresses.deploy_block ?? 0) : meta.block + 1;
    while (from <= latest) {
      const to = Math.min(latest, from + 9_999);
      for (const ev of await this.arc.logs(from, to)) await this.apply(ev, meta, now);
      meta.block = to;
      from = to + 1;
    }
  }

  async apply(ev, meta, now) {
    const a = ev.args;
    let o = await this.byRef(a.orderRef);
    const id = `${ev.tx}:${ev.index}`;
    if (o && (o.logs || []).includes(id)) return; // each event is applied once
    if (ev.name === "OrderPaid") {
      if (lower(a.merchant) !== lower(this.d.addresses.store)) return;
      if (!o) { // paid without going through the demo page
        o = { n: "unknown-" + lower(a.orderRef).slice(2, 12), ref: lower(a.orderRef), scenario: null, createdAt: Number(ev.time),
              events: [], subs: [], steps: [], mails: {} };
        await this.s.put("r:" + lower(o.ref), o.n);
      }
      Object.assign(o, { buyer: a.buyer, paidAt: Number(ev.time), amount: Number(a.amount), termsHash: lower(a.termsHash) });
      this.event(o, ev.time, "Paid into the demo escrow", { tx: ev.tx, net: "arc" });
      if (!o.scenario || o.amount !== this.d.amount_cents * 1e4) o.refundDue = "not_scenario";
      else {
        const q = await this.quota(a.buyer, ev.time);
        if (q.address >= q.per_address || q.total >= q.per_day) o.refundDue = "daily_limit";
      }
    } else if (!o) {
      return;
    } else if (ev.name === "ClaimOpened") {
      const text = a.claim;
      o.claim = { text, hash: lower(a.claimHash), chain: lower(a.chain), at: Number(ev.time) };
      o.judged = lower(a.chain);
      o.lastStepAt = Number(ev.time);
      this.event(o, ev.time, "Claim opened by the buyer", { tx: ev.tx, net: "arc" });
      let ok = false;
      try { ok = text === this.claimText(o, JSON.parse(text).claimed_at); } catch { ok = false; }
      if (!ok && !o.refundDue) o.refundDue = "not_scenario";
    } else if (ev.name === "Submitted") {
      const raw = a.submission;
      o.subs.push({ raw, chain: lower(a.chain), by: lower(a.by), at: Number(ev.time) });
      o.lastStepAt = Number(ev.time);
      const kind = (() => { try { return JSON.parse(raw).kind; } catch { return "?"; } })();
      const who = lower(a.by) === lower(o.buyer) ? "buyer" : lower(a.by) === lower(this.d.addresses.store) ? "store" : "anyone";
      this.event(o, ev.time, `Registered: ${kind.replace(/_/g, " ")} (${who})`, { tx: ev.tx, net: "arc" });
      if (who === "buyer" && !this.buyerSubs(o).includes(raw) && !o.refundDue) o.refundDue = "not_scenario";
    } else if (ev.name === "ProofRequested") {
      o.proofRequestedAt = Number(ev.time);
      this.event(o, ev.time, "Proof requested from the buyer", { tx: ev.tx, net: "arc" });
    } else if (ev.name === "VerdictProposed") {
      o.proposed = { outcome: Number(a.outcome), cents: Number(a.refundCents), after: Number(a.executeAfter) };
      this.event(o, ev.time, "Verdict proposed on Arc", { tx: ev.tx, net: "arc" });
    } else if (ev.name === "OrderSettled") {
      o.settled = { refund: Number(a.refund), released: Number(a.released), verdictRef: lower(a.verdictRef), tx: ev.tx, at: Number(ev.time) };
      if (o.refund?.sent) o.refund.done = true;
      this.event(o, ev.time, o.refund?.sent ? REFUND_TEXT[o.refund.reason] : "Settled on Arc", { tx: ev.tx, net: "arc" });
    } else {
      return;
    }
    o.logs = [...(o.logs || []), id];
    await this.saveOrder(o);
  }

  // ---- one order ----------------------------------------------------------------------------------------

  async stepOrder(o, now, budget, meta) {
    const sc = this.scen[o.scenario];
    const w = this.d.windows_seconds;
    // 1. Refunds by the store (DM-P5, DM-P6): before anything else, and never as a verdict.
    if (!o.refundDue && o.claim && now - (o.lastStepAt || o.claim.at) >= this.d.limits.stall_seconds) o.refundDue = "judge_slow";
    if (o.refundDue) {
      if (!o.refund?.sent && budget.store > 0 && await this.send(meta, "store", o, "merchantRefund", [o.ref], REFUND_TEXT[o.refundDue])) {
        budget.store--;
        o.refund = { reason: o.refundDue, sent: true };
      }
      return;
    }
    // 2. Late path: the store's emails, signed and attested on Lacre.
    if (sc.event === "late") await this.mails(o, now, budget);
    if (!o.claim) return;
    const subs = o.subs.map((s) => s.raw);
    const has = (kind, party) => subs.some((r) => r.endsWith(`"kind":"${kind}","party":"${party}"}`));
    // 3. The store answers the first round, or the window passes without an answer (D2).
    if (sc.event !== "late") {
      if (sc.response && !has("response", "merchant") && !o.responded && budget.store > 0) {
        if (await this.send(meta, "store", o, "submit", [o.ref, this.storeSub("response", sc.response)], "Store answered")) {
          budget.store--; o.responded = true;
        }
      }
      if (!sc.response && !has("response", "merchant") && !has("no_response", "escrow") && now >= o.claim.at + w.response
          && !o.marked && budget.relayer > 0) {
        if (await this.send(meta, "relayer", o, "markNoResponse", [o.ref], "No-response marker after the window")) {
          budget.relayer--; o.marked = true;
        }
      }
    }
    // 4. Closing round: the store answers it; after the window, the timeout marker.
    if (has("closing_open", "escrow") && sc.closing) {
      const opened = o.subs.find((s) => s.raw.endsWith('"kind":"closing_open","party":"escrow"}')).at;
      if (!has("closing_response", "merchant") && !o.closingAnswered && now <= opened + w.closing && budget.store > 0) {
        if (await this.send(meta, "store", o, "submit", [o.ref, this.storeSub("closing_response", sc.closing.store)], "Store answered the closing round")) {
          budget.store--; o.closingAnswered = true;
        }
      }
      const both = has("closing_response", "merchant") && (has("closing_proof", "buyer") || has("closing_statement", "buyer"));
      if (!both && !has("closing_timeout", "escrow") && now >= opened + w.closing && !o.closingMarked && budget.relayer > 0) {
        if (await this.send(meta, "relayer", o, "markClosingTimeout", [o.ref], "Closing round timed out")) {
          budget.relayer--; o.closingMarked = true;
        }
      }
    }
    // 5. A step in flight on Bradbury: verdict ACCEPTED, then FINALIZED.
    const cur = o.steps[o.steps.length - 1];
    if (cur && !cur.final) {
      await this.follow(o, cur, sc, meta, now, budget);
      return;
    }
    // 6. A final verdict not taken to Arc yet.
    if (cur && cur.final && !cur.acted) {
      await this.act(o, cur, meta, budget);
      return;
    }
    // 7. A proposed verdict, executable after the delay.
    if (o.proposed && !o.executed && now >= o.proposed.after && budget.relayer > 0) {
      if (await this.send(meta, "relayer", o, "executeVerdict", [o.ref], "Verdict executed")) { budget.relayer--; o.executed = true; }
      return;
    }
    // 8. Proof requested and not sent: after the window, the payment goes to the store.
    if (o.proofRequestedAt && !has("proof", "buyer") && now >= o.proofRequestedAt + w.proof && !o.unproven && budget.relayer > 0) {
      if (await this.send(meta, "relayer", o, "releaseUnproven", [o.ref], "Released to the store: proof not provided")) {
        budget.relayer--; o.unproven = true;
      }
      return;
    }
    // 9. A new judgment step when the round is complete.
    if (!o.proposed && this.ready(o, sc, now, has) && budget.gl > 0) await this.judge(o, sc, meta, budget, now);
  }

  pending(o) {
    const chains = [o.claim.chain, ...o.subs.map((s) => s.chain)];
    const i = chains.indexOf(o.judged);
    return i < 0 ? null : o.subs.slice(i).map((s) => s.raw);
  }

  ready(o, sc, now, has) {
    const p = this.pending(o);
    if (!p || !p.length) return false;
    if (sc.judge === "mail") {
      const last = o.subs[o.subs.length - 1].at;
      return p.length >= 2 || now - last >= 600;
    }
    if (o.proofRequestedAt) return has("proof", "buyer");
    if (has("closing_open", "escrow")) {
      const both = has("closing_response", "merchant") && (has("closing_proof", "buyer") || has("closing_statement", "buyer"));
      return both || has("closing_timeout", "escrow");
    }
    return has("response", "merchant") || has("no_response", "escrow");
  }

  async judge(o, sc, meta, budget, now) {
    const pend = this.pending(o);
    let cur = o.judged;
    for (const raw of pend) cur = fold(cur, raw);
    const chainOnArc = await this.arc.getOrder(o.ref);
    if (lower(chainOnArc.chain) !== cur || lower(chainOnArc.claimHash) !== shaText(o.claim.text)) {
      this.pause(meta, `${o.n}: what was registered does not fold to the escrow chain`);
      return;
    }
    const n = o.steps.filter((s) => s.final).length + 1;
    let st = o.steps.find((s) => s.n === n && !s.final);
    if (!st) { st = { n, from: o.judged, to: cur, count: pend.length, attempts: [] }; o.steps.push(st); }
    if (st.attempts.length >= MAX_ATTEMPTS) return; // left to the stall refund (DM-P6)
    const step = cj({ chain: o.judged, submissions: pend });
    const at = { startedAt: Number(now), tx: null };
    st.attempts.push(at);
    await this.saveOrder(o); // the send is recorded before it is made
    budget.gl--;
    try {
      at.tx = await this.gl.sendJudge(sc.judge, o.claim.text, step);
      this.event(o, now, `Step ${n} sent to the judge, attempt ${st.attempts.length}`, { tx: at.tx, net: "bradbury" });
    } catch (e) {
      at.error = String(e.message || e).slice(0, 200);
      this.log(`judge send failed ${o.n}: ${at.error}`);
    }
  }

  async follow(o, st, sc, meta, now, budget) {
    const at = st.attempts[st.attempts.length - 1];
    if (!at) return;
    // Status first, then the verdict: a transaction that ends between the two reads is not lost.
    const status = at.tx ? await this.gl.status(at.tx) : null;
    const final = await this.gl.verdict(sc.judge, st.to, true);
    if (final && final.outcome && final.outcome !== "NO_CONSENSUS") {
      const want = sc.steps[st.n - 1] || {};
      const seen = { outcome: final.outcome, refund_cents: final.refund_cents, reason: final.reason, action: final.action };
      const ok = want.outcome === seen.outcome && want.refund_cents === seen.refund_cents && want.reason === seen.reason
        && want.action === seen.action && lower(final.chain) === st.to && lower(final.claim_hash) === o.claim.hash
        && (sc.judge !== "mail" || (final.ignored || []).length === 0);
      st.final = final;
      at.result = "accepted";
      o.judged = st.to;
      o.lastStepAt = Number(now);
      this.event(o, now, `Step ${st.n} final: ${final.outcome} ${(final.refund_cents / 100).toFixed(2)} USDC (${final.reason})`,
        { tx: at.tx, net: "bradbury" });
      if (!ok) this.pause(meta, `${o.n} step ${st.n}: verdict ${cj(seen)}, expected ${cj(want)}`);
      return;
    }
    if (status && !status.done) {
      // Shown on the page while Bradbury has not closed the attempt yet (the first time it is seen, from its last vote).
      const stuck = NO_CONSENSUS_STATUS.has(status.status) || NO_CONSENSUS_RESULT.has(status.result);
      at.noConsensusAt = stuck ? at.noConsensusAt || status.lastVote || Number(now) : null;
    }
    if (!st.decided) {
      const nf = await this.gl.verdict(sc.judge, st.to, false);
      if (nf && nf.outcome === "NO_CONSENSUS" && !at.noConsensusAt) at.noConsensusAt = (status && status.lastVote) || Number(now);
      if (nf && nf.outcome && nf.outcome !== "NO_CONSENSUS") {
        st.decided = { outcome: nf.outcome, refund_cents: nf.refund_cents, reason: nf.reason, action: nf.action };
        this.event(o, now, `Step ${st.n} decided, finalizing: ${nf.outcome} ${(nf.refund_cents / 100).toFixed(2)} USDC (${nf.reason})`,
          { tx: at.tx, net: "bradbury" });
      }
    }
    // No final verdict: the transaction ended without consensus, or the send did not go out.
    const over = at.tx ? !!(status && status.done) : now - at.startedAt >= 900;
    if (over) {
      at.result = at.tx ? `no consensus (${status.result || status.status}), resent` : "not sent";
      st.decided = null;
      if (st.attempts.length < MAX_ATTEMPTS && budget.gl > 0) {
        const pend = this.pending(o);
        if (pend) await this.judge(o, sc, meta, budget, now);
      }
    }
  }

  async act(o, st, meta, budget) {
    const v = st.final;
    const onArc = await this.arc.getOrder(o.ref);
    if (lower(onArc.chain) !== lower(v.chain) || lower(onArc.claimHash) !== lower(v.claim_hash)) {
      this.pause(meta, `${o.n}: the escrow changed since the verdict`);
      return;
    }
    if (budget.relayer <= 0) return;
    const tx = st.attempts[st.attempts.length - 1].tx;
    let ok = false;
    if (v.action === "open_closing_round") ok = await this.send(meta, "relayer", o, "openClosingRound", [o.ref], "Closing round opened");
    else if (v.action === "request_proof") ok = await this.send(meta, "relayer", o, "requestProof", [o.ref], "Proof requested");
    else if (v.action === "decide" && OUTCOME[v.outcome]) {
      ok = await this.send(meta, "relayer", o, "proposeVerdict",
        [o.ref, OUTCOME[v.outcome], v.refund_cents, v.claim_hash, v.chain, "0x" + tx.slice(2).padStart(64, "0").slice(-64)],
        "Verdict proposed");
    } else {
      st.acted = true; // "wait": nothing to take to Arc
      return;
    }
    if (ok) { budget.relayer--; st.acted = true; }
  }

  // ---- the late path's emails -------------------------------------------------------------------------

  async mails(o, now, budget) {
    const day = isoDay(now);
    const paidDay = isoDay(o.paidAt);
    const want = ["confirmed"];
    if (day > paidDay) want.push("delivered");
    for (const k of want) {
      const m = o.mails[k];
      if (!m) {
        const t = Number(now);
        const tpl = this.d.mail[k];
        const vars = { order: o.n, total: (o.amount / 1e6).toFixed(2), day: k === "confirmed" ? paidDay : day };
        const fill = (s) => s.replace(/\{(\w+)\}/g, (_, x) => vars[x]);
        const signed = await signMail(this.dkimKey, {
          domain: this.d.terms.domain, selector: this.d.terms.selector, t, body: fill(tpl.body),
          headers: { From: this.d.mail.from, To: this.d.mail.to, Subject: fill(tpl.subject), Date: mailDate(t),
                     "Message-ID": `<${k}.${o.n.toLowerCase()}.${t}@${this.d.terms.domain}>` } });
        o.mails[k] = { ...signed, signedAt: t, attempts: [] };
        this.event(o, now, k === "confirmed" ? "Store email signed: order confirmed" : "Store email signed: delivered", { net: "store" });
        continue;
      }
      if (m.record) continue;
      const a = m.attempts[m.attempts.length - 1];
      if (a && !a.done) {
        const st = a.tx ? await this.gl.status(a.tx) : null;
        const rid = await this.gl.findRecord(m.bh, true);
        if (rid != null) {
          m.record = String(rid);
          a.done = true;
          this.event(o, now, `Store email attested on Lacre: record ${rid}`, { tx: a.tx, net: "lacre" });
          continue;
        }
        if (!(a.tx ? st && st.done : now - a.startedAt >= 900)) continue;
        a.done = true; // finalized without a record: attest again
      }
      if (m.attempts.length >= MAX_ATTEMPTS || budget.gl <= 0) continue;
      const at = { startedAt: Number(now), tx: null };
      m.attempts.push(at);
      await this.saveOrder(o);
      budget.gl--;
      try {
        at.tx = await this.gl.attest(m.blob, this.d.terms.domain, this.d.terms.selector, m.raw);
        this.event(o, now, "Store email sent to Lacre", { tx: at.tx, net: "lacre" });
      } catch (e) {
        at.error = String(e.message || e).slice(0, 200);
      }
    }
  }

  // ---- what the page shows -----------------------------------------------------------------------------

  async view(n, now) {
    const o = await this.order(n);
    if (!o) return null;
    const sc = this.scen[o.scenario] || null;
    const out = { order: o.n, ref: o.ref, scenario: o.scenario, buyer: o.buyer || null, paid: !!o.paidAt,
                  events: o.events, steps: o.steps.map((s) => ({ n: s.n, decided: s.decided || null,
                    final: s.final ? { outcome: s.final.outcome, refund_cents: s.final.refund_cents, reason: s.final.reason,
                      action: s.final.action } : null, attempts: s.attempts.map((a) => ({ tx: a.tx, result: a.result || "pending",
                      no_consensus_at: a.noConsensusAt || null })) })),
                  settled: o.settled || null, refund: o.refund ? { reason: o.refund.reason, text: REFUND_TEXT[o.refund.reason] } : null,
                  next: null, max_attempts: MAX_ATTEMPTS };
    if (!sc || !o.paidAt || o.settled || o.refundDue) return out;
    if (!o.claim) {
      if (sc.event === "late" && !(o.mails.delivered?.record && o.mails.confirmed?.record)) {
        out.next = { action: "wait", text: isoDay(now) === isoDay(o.paidAt)
          ? "The delivery notice is sent tomorrow (UTC). Come back then to open the claim."
          : "The store's emails are being attested on Lacre." };
      } else {
        // A minute of margin for the block time, never before the payment (the judge requires paid_at <= claimed_at).
        const claimedAt = Math.max(Number(now) - 60, o.paidAt);
        out.next = { action: "claim", claimed_at: claimedAt, claim: this.claimText(o, claimedAt),
                     then: this.buyerSubs(o).filter((r) => r.includes('"kind":"evidence"')) };
      }
      return out;
    }
    const subs = o.subs.map((s) => s.raw);
    const missing = this.buyerSubs(o).filter((r) => !subs.includes(r));
    const closingOpen = subs.some((r) => r.endsWith('"kind":"closing_open","party":"escrow"}'));
    if (sc.event === "late" && missing.length) out.next = { action: "submit", submissions: missing };
    else if (sc.closing && closingOpen && missing.length) out.next = { action: "submit", submissions: missing };
    else out.next = { action: "wait", text: "The demo store and the judge are working on it." };
    return out;
  }
}
