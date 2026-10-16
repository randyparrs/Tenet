// Reads a Bradbury transaction (no key): status, result, rounds and the last round's vote of each
// validator. Output: one JSON line.
//   GLJS_DIST=<genlayer-js 2.x dist/ folder> node tools/tx_votes.mjs <hash>
// Votes are named from the raw number with the current protocol table (VoteType in the genlayer-py
// reference on docs.genlayer.com and in genlayer-js 2.0.0-rc.1). genlayer-js 1.x
// `validatorVotesName` is not used: its table is from another version (it calls 1 AGREE, 2 DISAGREE
// and 4 DETERMINISTIC_VIOLATION).
// The vote number is the class of each validator's execution result, not "agrees with the leader";
// agreement is given by the transaction result.
import { pathToFileURL } from "node:url";

const GLJS = process.env.GLJS_DIST;
if (!GLJS) throw new Error("set GLJS_DIST to the dist/ folder of genlayer-js 2.x (see local.env.example)");
const { createClient } = await import(pathToFileURL(GLJS + "index.js").href);
const { testnetBradbury } = await import(pathToFileURL(GLJS + "chains/index.js").href);
const VOTES = ["NOT_VOTED", "FINISHED_WITH_RETURN", "FINISHED_WITH_ERROR", "TIMEOUT", "NONDET_DISAGREE",
               "DETERMINISTIC_VIOLATION"];

const tx = await createClient({ chain: testnetBradbury }).getTransaction({ hash: process.argv[2] });
const r = tx.lastRound ?? {};
const validators = (r.roundValidators ?? []).map((a, i) => {
  const raw = (r.validatorVotes ?? [])[i];
  const code = raw === undefined ? "" : String(raw);
  return {
    address: a,
    vote: `${code}:${VOTES[Number(code)] ?? "UNKNOWN"}`,
    leader: i === Number(r.leaderIndex ?? -1),
  };
});
const counts = {};
for (const v of validators) counts[v.vote] = (counts[v.vote] ?? 0) + 1;
// resultName and txExecutionResultName come from the SDK; the raw result number too.
console.log(JSON.stringify({
  status: tx.statusName, result: `${String(tx.result ?? "")}:${tx.resultName}`, execution: tx.txExecutionResultName,
  rounds: String(tx.numOfRounds ?? ""), round: String(r.round ?? ""), counts, validators,
}));
