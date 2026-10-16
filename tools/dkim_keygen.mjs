// Creates the DKIM key of a test store domain (RSA 2048) and prints the TXT record to publish in DNS.
// The private key goes to DKIM_KEY_FILE, a path outside the repository, and is never printed. If the
// file already exists it is not overwritten: the TXT record is derived from it again.
//
//   DKIM_KEY_FILE=<path outside the repository> node tools/dkim_keygen.mjs [domain] [selector]
//
// Default domain and selector: the live test store, Demo Shop (shop.rpmdev.app, selector shop1).
// The Demo Shop section of the page uses demo.rpmdev.app, selector demo1.
import { generateKeyPairSync, createPrivateKey, createPublicKey } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const DOMAIN = process.argv[2] ?? "shop.rpmdev.app";
const SELECTOR = process.argv[3] ?? "shop1";
const ZONE = "rpmdev.app";
const KEY_FILE = process.env.DKIM_KEY_FILE;
if (!KEY_FILE) throw new Error("set DKIM_KEY_FILE to the private key's path, outside the repository");
const PUBLIC_OUT = `results/dkim-public-${SELECTOR}.txt`; // public data, to compare with DNS later

let created = false;
if (!existsSync(KEY_FILE)) {
  const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048, publicExponent: 0x10001 });
  mkdirSync(dirname(KEY_FILE), { recursive: true });
  writeFileSync(KEY_FILE, privateKey.export({ type: "pkcs8", format: "pem" }), { flag: "wx" });
  created = true;
}
const pub = createPublicKey(createPrivateKey(readFileSync(KEY_FILE, "utf8")));
const p = pub.export({ type: "spki", format: "der" }).toString("base64");
const value = `v=DKIM1; k=rsa; p=${p}`;
const fullName = `${SELECTOR}._domainkey.${DOMAIN}`;
const cfName = fullName.slice(0, -(ZONE.length + 1));

writeFileSync(PUBLIC_OUT, `${fullName}\n${value}\n`);
console.log(created ? "new key saved in" : "the key already existed in", KEY_FILE, "(not printed)");
console.log("bits:", pub.asymmetricKeyDetails.modulusLength);
console.log("");
console.log("DNS record (zone " + ZONE + "):");
console.log("  Type:    TXT");
console.log("  Name:    " + cfName + "      (full name: " + fullName + ")");
console.log("  TTL:     Auto");
console.log("  Content (one line, no quotes):");
console.log(value);
console.log("");
console.log("Public copy of the record in", PUBLIC_OUT);
