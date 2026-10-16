// Builds site/circle-sdk.js from Circle's Web SDK (@circle-fin/w3s-pw-web-sdk, Apache-2.0). The rest of
// the page has no build step; this file is the only bundle, and the page loads it on demand.
//
//   cd tools/circle-sdk && npm ci && node build.mjs
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "..", "site", "circle-sdk.js");
await build({
  entryPoints: [join(HERE, "entry.js")], bundle: true, format: "iife", platform: "browser", target: "es2020",
  outfile: OUT, minify: true, legalComments: "eof", logLevel: "warning",
  alias: { jsonwebtoken: join(HERE, "jwt-shim.js") }, define: { "process.env.NODE_ENV": '"production"' },
  banner: { js: "/* Circle user-controlled wallets Web SDK 1.1.11 (Apache-2.0), bundled for Tenet by tools/circle-sdk/build.mjs */" },
});
console.log("built " + OUT);
