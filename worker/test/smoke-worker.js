// workerd smoke test (read only): the demo Worker's Bradbury and Arc adapters inside Cloudflare's
// runtime, against the live networks. Throwaway keys; nothing is signed or sent.
import { makeGl } from "../src/genlayer.js";
import { makeArc } from "../src/arc.js";
import { importDkimKey, signMail } from "../src/util.js";
import data from "../src/demo-data.json";

export default {
  async fetch(req, env) {
    const out = {};
    const gl = makeGl({ key: env.THROWAWAY, router: data.addresses.router,
      judges: { mail: "0x7e3251e7A9479280a6b8c93FD2E852291abd105c", subjective: "0x2a0126530321FF7886A568b9439d3535A27EfA91" } });
    const v = await gl.verdict("subjective", "0xe6404534a108d6fb0d56ba8059f8ab13b40b58037be82be491215faa81bcedaa", true);
    out.bradbury_verdict = v && `${v.outcome} ${v.refund_cents} ${v.reason}`;
    out.bradbury_status = await gl.status("0x87f4559fb02114abb656c7f0c283bd9dd093d5e40635d22a6cbc69909c45969c");
    out.lacre_record_lookup = await gl.findRecord("none", true);
    const arc = makeArc({ rpc: "https://rpc.testnet.arc.io", chainId: 5042002, escrow: "0x5Bf18C9B66dF20BF2D30e08b561f65de73fA1E2D",
      abi: data.escrow_abi, keys: { relayer: env.THROWAWAY, store: env.THROWAWAY } });
    out.arc_block = await arc.latestBlock();
    const e = await arc.getOrder("0x5a19cf062c1a4711b814a4b1978154efde8afca395d3387d7af57917f6604e2c");
    out.arc_live_order_E_state = e.state;
    const key = await importDkimKey(env.PEM);
    const m = await signMail(key, { domain: "demo.rpmdev.app", selector: "demo1", t: 1791990000, body: "x\r\n",
      headers: { From: "a@demo.rpmdev.app", To: "b@example.com", Subject: "s", Date: "d", "Message-ID": "<m@demo.rpmdev.app>" } });
    out.dkim_signed = m.raw.startsWith("DKIM-Signature: v=1; a=rsa-sha256;") && m.blob.length > 300;
    return new Response(JSON.stringify(out));
  },
};
