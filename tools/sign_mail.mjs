// Signs the Demo Shop email set (cases/mail-set.json) with DKIM and writes cases/mail/<id>.eml.
// rsa-sha256, c=relaxed/relaxed, h=from:to:subject:date:message-id, t = the email's date.
// MAIL_SET and MAIL_OUT pick another set and another folder (the end-to-end test uses them).
// Canonicalization per RFC 6376 3.4.2 and 3.4.4, the same Lacre checks (lacre/dkimcore.py and
// lacre/dkimbody.py). The private key is read from DKIM_KEY_FILE and never printed.
//
//   DKIM_KEY_FILE=<pem> [MAIL_SET=<set.json>] [MAIL_OUT=<dir>] node tools/sign_mail.mjs
import { createHash, createPrivateKey, sign } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

const KEY_FILE = process.env.DKIM_KEY_FILE;
if (!KEY_FILE) throw new Error("set DKIM_KEY_FILE to the store's DKIM private key (PEM)");
const OUT = process.env.MAIL_OUT ?? "cases/mail";
const SIGNED = ["From", "To", "Subject", "Date", "Message-ID"];

const canonHeader = (name, value) =>
  name.trim().toLowerCase() + ":" + value.replace(/\r\n/g, "").replace(/[ \t]+/g, " ").trim() + "\r\n";

function canonBody(body) {
  const lines = body.split("\r\n").map((l) => l.replace(/[ \t]+/g, " ").replace(/ +$/, ""));
  while (lines.length && !lines[lines.length - 1]) lines.pop();
  return lines.length ? lines.join("\r\n") + "\r\n" : "";
}

const key = createPrivateKey(readFileSync(KEY_FILE, "utf8"));
// MAIL_SET: another set with the same format (the end-to-end one, cases/e2e/mail-set.json).
const set = JSON.parse(readFileSync(process.env.MAIL_SET ?? "cases/mail-set.json", "utf8"));
set.negatives = set.negatives ?? [];
mkdirSync(OUT, { recursive: true });

for (const m of [...set.positives, ...set.negatives]) {
  const h = m.headers;
  const t = Math.floor(Date.parse(h.Date) / 1000);
  const bh = createHash("sha256").update(canonBody(m.body), "latin1").digest("base64");
  const tags = `v=1; a=rsa-sha256; c=relaxed/relaxed; d=${m.sign.domain}; s=${m.sign.selector}; t=${t}; ` +
    `h=${SIGNED.map((n) => n.toLowerCase()).join(":")}; bh=${bh}; b=`;
  const data = SIGNED.map((n) => canonHeader(n, " " + h[n])).join("") +
    canonHeader("DKIM-Signature", " " + tags).replace(/\r\n$/, "");
  const b = sign("sha256", Buffer.from(data, "latin1"), key).toString("base64");
  let body = m.body;
  if (m.sign.tamper) body = body.replace(m.sign.tamper[0], m.sign.tamper[1]);
  const raw = `DKIM-Signature: ${tags}${b}\r\n` + SIGNED.map((n) => `${n}: ${h[n]}\r\n`).join("") +
    "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=us-ascii\r\n\r\n" + body;
  writeFileSync(`${OUT}/${m.id}.eml`, raw, "latin1");
}
console.log(`signed ${set.positives.length + set.negatives.length} emails in ${OUT}`);
