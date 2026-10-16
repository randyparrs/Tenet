# Error codes of the v2 judge contracts

Both contracts (`judge_mail.py` and `judge_subjective.py`) reject a call with
`gl.vm.UserError("[EXPECTED] <code>")`. A rejected call changes nothing in the contract.
`tests/judge_v2_stub_run.py` reads this table: a code the contract uses that is not listed here
fails the run.

Under the chain model, nothing that comes from the escrow is an error: a claim the judge cannot read
gets the verdict INVALID_CLAIM, and a submission that cannot be used (malformed, out of turn, from
the wrong party, an email without a valid attestation) is ignored. Errors are kept for the call
itself, the store registration and a Lacre read that failed (it is retried).

| code | meaning |
|---|---|
| C3 | event not judged by this contract |
| S1 | step is not {"chain", "submissions"} with a 32 byte chain and at most 8 submissions as text |
| S2 | unknown chain for this claim |
| M1 | owner only |
| M2 | bad merchant address |
| M3 | terms not supported in v2 |
| M4 | merchant not registered |
| M5 | terms hash does not match the merchant terms |
| F2 | claim already decided |
| F7 | refund out of range |
| L2 | lacre unreadable |

## Why a submission was ignored (email judge only)

The verdict of `judge_mail.py` carries `ignored`: a list of `[sha256 of the submission, code]` for
the submissions of that step that did not count. The subjective judge does not carry it (it does
not fit under the deploy gas cap); its state in `get_claim(chain)` is enough to deduce it.

| code | reason |
|---|---|
| I1 | not canonical JSON, or not {party, kind, content} |
| I2 | that kind of submission is not accepted from that party in this contract |
| I3 | out of turn or repeated (for example the same email twice) |
| I4 | content with the wrong shape |
| I5 | no valid and aligned Lacre attestation for the store's domain (missing, not valid, not aligned, key too small) |
| I6 | the store's signing key is not active |
| I7 | the body does not match the signature |
| I8 | it is about another order, or another order already used it |
| I9 | signed before the order's payment date |
