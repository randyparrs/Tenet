// Shared helpers of the demo Worker. They reproduce, byte for byte, what the Python tools and the
// contracts compute: canonical JSON, the escrow's hash chain, order references, DKIM signatures.
import { sha256, toBytes, hexToBytes, bytesToHex, concat } from "viem";

/** Canonical JSON as json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True). */
export function cj(o) {
  if (o === null || o === undefined) return "null";
  if (typeof o === "boolean") return o ? "true" : "false";
  if (typeof o === "number") {
    if (!Number.isInteger(o)) throw new Error("cj: only integers");
    return String(o);
  }
  if (typeof o === "bigint") return o.toString();
  if (typeof o === "string") return quote(o);
  if (Array.isArray(o)) return "[" + o.map(cj).join(",") + "]";
  const keys = Object.keys(o).sort();
  return "{" + keys.map((k) => quote(k) + ":" + cj(o[k])).join(",") + "}";
}

function quote(s) {
  let out = '"';
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (ch === '"') out += '\\"';
    else if (ch === "\\") out += "\\\\";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\b") out += "\\b";
    else if (ch === "\f") out += "\\f";
    else if (c < 0x20 || (c > 0x7f && c <= 0xffff)) out += "\\u" + c.toString(16).padStart(4, "0");
    else if (c > 0xffff) {
      const v = c - 0x10000;
      out += "\\u" + (0xd800 + (v >> 10)).toString(16) + "\\u" + (0xdc00 + (v & 0x3ff)).toString(16);
    } else out += ch;
  }
  return out + '"';
}

/** "0x" + SHA-256 hex of a UTF-8 string. */
export const shaText = (text) => sha256(toBytes(text));

/** What the escrow stores when a claim opens: sha256(claimHash). */
export const chain0 = (claimHash) => sha256(hexToBytes(claimHash));

/** The escrow on every registered submission: sha256(chain || sha256(submission)). */
export const fold = (cur, raw) => sha256(concat([hexToBytes(cur), hexToBytes(shaText(raw))]));

/** The order reference the escrow keys orders by: sha256 of the order number. */
export const orderRef = (orderNumber) => shaText(orderNumber);

export const isoDay = (unix) => new Date(Number(unix) * 1000).toISOString().slice(0, 10);
export const addDays = (day, n) => new Date(Date.parse(day + "T00:00:00Z") + n * 86400e3).toISOString().slice(0, 10);

export function b64(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export const latin1 = (text) => Uint8Array.from(text, (c) => c.charCodeAt(0) & 0xff);
export const lower = (a) => String(a).toLowerCase();
export { bytesToHex };

// ---- DKIM (rsa-sha256, relaxed/relaxed), as tools/sign_mail.mjs -----------------------------------

const SIGNED = ["From", "To", "Subject", "Date", "Message-ID"];
const canonHeader = (name, value) =>
  name.trim().toLowerCase() + ":" + value.replace(/\r\n/g, "").replace(/[ \t]+/g, " ").trim() + "\r\n";

function canonBody(body) {
  const lines = body.split("\r\n").map((l) => l.replace(/[ \t]+/g, " ").replace(/ +$/, ""));
  while (lines.length && !lines[lines.length - 1]) lines.pop();
  return lines.length ? lines.join("\r\n") + "\r\n" : "";
}

/** PKCS8 PEM -> CryptoKey for RSASSA-PKCS1-v1_5 / SHA-256 (WebCrypto: Workers and Node). */
export async function importDkimKey(pem) {
  const der = atob(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""));
  return crypto.subtle.importKey("pkcs8", Uint8Array.from(der, (c) => c.charCodeAt(0)),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
}

/**
 * Signs one email and returns {raw, blob}: raw is the full message (latin-1 string, CRLF), blob the
 * headers Lacre's attest_inline takes (the DKIM-Signature and the fields it signs, in message order,
 * CRLF), as tools/headers_blob.py cuts it.
 */
export async function signMail(key, { domain, selector, headers, body, t }) {
  const bh = b64(new Uint8Array(await crypto.subtle.digest("SHA-256", latin1(canonBody(body)))));
  const tags = `v=1; a=rsa-sha256; c=relaxed/relaxed; d=${domain}; s=${selector}; t=${t}; ` +
    `h=${SIGNED.map((n) => n.toLowerCase()).join(":")}; bh=${bh}; b=`;
  const data = SIGNED.map((n) => canonHeader(n, " " + headers[n])).join("") +
    canonHeader("DKIM-Signature", " " + tags).replace(/\r\n$/, "");
  const sig = b64(new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, latin1(data))));
  const dkim = `DKIM-Signature: ${tags}${sig}\r\n`;
  const signedHeaders = SIGNED.map((n) => `${n}: ${headers[n]}\r\n`).join("");
  const raw = dkim + signedHeaders + "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=us-ascii\r\n\r\n" + body;
  return { raw, blob: dkim + signedHeaders, bh, body };
}

/** RFC 5322 date as Python's email.utils.formatdate(t, usegmt=True) with +0000. */
export function mailDate(unix) {
  const d = new Date(Number(unix) * 1000);
  const day = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getUTCDay()];
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getUTCMonth()];
  const p = (n) => String(n).padStart(2, "0");
  return `${day}, ${p(d.getUTCDate())} ${mon} ${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} +0000`;
}
