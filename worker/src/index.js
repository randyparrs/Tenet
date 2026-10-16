// Cloudflare entry of the demo Worker. One Durable Object ("demo") holds all the state and runs the
// core: the cron trigger calls its tick every minute, and the page's API goes through it too, so
// there is a single writer. Secrets (wrangler secret put): DEMO_RELAYER_KEY, DEMO_STORE_KEY,
// DKIM_DEMO_KEY (PKCS8 PEM). Nothing else is secret: addresses and texts are in demo-data.json.
import { DurableObject } from "cloudflare:workers";
import data from "./demo-data.json";
import { DemoCore, REFUND_TEXT } from "./core.js";
import { makeArc } from "./arc.js";
import { makeGl } from "./genlayer.js";
import { importDkimKey, lower } from "./util.js";

// A secret as stored, without the line break a shell may add when it is piped in.
const secret = (v) => {
  const t = String(v || "").trim();
  return t && !t.startsWith("0x") && /^[0-9a-fA-F]{64}$/.test(t) ? "0x" + t : t;
};
// Error text for the page, with anything shaped like a key or a PEM removed.
const redact = (e) => String((e && (e.shortMessage || e.message)) || e).replace(/-----BEGIN[\s\S]*?-----END[^-]*-----/g, "[pem]")
  .replace(/(0x)?[0-9a-fA-F]{64}/g, "[redacted]").slice(0, 300);
const json = (body, status = 200) => new Response(JSON.stringify(body), { status,
  headers: { "content-type": "application/json", "access-control-allow-origin": "*", "cache-control": "no-store" } });

export class DemoState extends DurableObject {
  async core() {
    if (!this._core) {
      const st = this.ctx.storage;
      const store = { get: (k) => st.get(k), put: (k, v) => st.put(k, v), delete: (k) => st.delete(k),
        list: async (p) => [...(await st.list({ prefix: p })).values()] };
      const a = data.addresses;
      const arc = makeArc({ rpc: this.env.ARC_RPC || "https://rpc.testnet.arc.io", chainId: data.chain_id, escrow: a.escrow,
        abi: data.escrow_abi, keys: { relayer: secret(this.env.DEMO_RELAYER_KEY), store: secret(this.env.DEMO_STORE_KEY) } });
      if (lower(arc.addresses.relayer) !== lower(a.relayer) || lower(arc.addresses.store) !== lower(a.store)) {
        throw new Error("the secrets do not match the demo relayer and store of demo-data.json");
      }
      const gl = makeGl({ key: secret(this.env.DEMO_RELAYER_KEY), judges: a.judges, router: a.router });
      this._core = new DemoCore({ data, store, arc, gl, dkimKey: await importDkimKey(this.env.DKIM_DEMO_KEY),
        log: (t) => console.log(t) });
    }
    return this._core;
  }

  async fetch(req) {
    const url = new URL(req.url);
    let core;
    try {
      core = await this.core();
    } catch (e) {
      this._core = null;
      return json({ error: "the demo could not start: " + redact(e) }, 503);
    }
    const now = () => core.arc.now();
    try {
      if (url.pathname === "/tick") {
        // The last tick, ok or not, is kept for the page's health line (error text redacted).
        try {
          const out = await core.tick();
          await this.ctx.storage.put("lastTick", { at: Date.now(), out });
          return json(out);
        } catch (e) {
          await this.ctx.storage.put("lastTick", { at: Date.now(), error: redact(e) });
          throw e;
        }
      }
      if (url.pathname === "/api/config") {
        const meta = await core.meta();
        return json({ chain_id: data.chain_id, amount_cents: data.amount_cents, windows_seconds: data.windows_seconds,
          verdict_delay_seconds: data.verdict_delay_seconds, limits: data.limits, terms: { domain: data.terms.domain,
          terms_hash: data.terms.terms_hash, hold_seconds: data.terms.hold_seconds, structure: data.terms.structure },
          addresses: data.addresses, refund_texts: REFUND_TEXT, paused: meta.paused ? meta.stop : null,
          last_tick: await this.ctx.storage.get("lastTick"),
          scenarios: data.scenarios.map(({ id, title, path, summary, store, product, next_day, steps, settle, claim, account, response, closing }) =>
            ({ id, title, path, summary, store, product, next_day: !!next_day, steps, settle, claim: claim || null, account: account || null,
               response: response || null, closing: closing || null })) });
      }
      if (url.pathname === "/api/quota") {
        const address = url.searchParams.get("address") || "";
        if (!/^0x[0-9a-fA-F]{40}$/.test(address)) return json({ error: "address" }, 400);
        return json(await core.quota(address, await now()));
      }
      if (url.pathname === "/api/orders" && req.method === "POST") {
        const body = await req.json().catch(() => ({}));
        const meta = await core.meta();
        if (meta.paused) return json({ error: "the demo is paused" }, 503);
        return json(await core.createOrder(String(body.scenario || ""), await now()));
      }
      const m = /^\/api\/orders\/(DS-\d{6})$/.exec(url.pathname);
      if (m) {
        const v = await core.view(m[1], await now());
        return v ? json(v) : json({ error: "no such order" }, 404);
      }
      return json({ error: "not found" }, 404);
    } catch (e) {
      return json({ error: redact(e) }, 400);
    }
  }
}

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") {
      return new Response(null, { headers: { "access-control-allow-origin": "*", "access-control-allow-methods": "GET,POST",
        "access-control-allow-headers": "content-type" } });
    }
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/")) return json({ error: "not found" }, 404);
    return env.DEMO.get(env.DEMO.idFromName("demo")).fetch(req);
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(env.DEMO.get(env.DEMO.idFromName("demo")).fetch("https://demo/tick", { method: "POST" }));
  },
};
