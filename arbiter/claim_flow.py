"""How a subjective claim moves, in code: two separate paths, each at most once per claim.

Path A, missing or malformed proof (label insufficient): proof is requested once and the buyer has
7 days from the request. No proof sent in time -> DENY "proof not provided". Proof sent and the
result is still insufficient -> DENY "claim not proven". There is no second request.
Path B, contradicting facts (the store disputes with a fact and the buyer's proof is not in the
description): a single closing round, with the rule in subjective_v3.label: disputes again with a
fact -> DENY "claim not proven"; admits -> REFUND; general denial or no answer -> base rule
(well-formed proof REFUND, otherwise insufficient, which enters path A if it had not before). A
contradiction after the closing round does not open another one: it is judged with what that round
left (kept in the state).
If the closing round ended without proof and path A started, proof the buyer sends afterwards is
judged with the base rule: well formed -> REFUND.

The state is kept by whoever runs the claim (the judge contract on GenLayer); the escrow on Arc
keeps its own (`requestProof` once per order). Standard library only.
"""
import subjective_v3 as s3

NEW_STATE = {"proof_requested": False, "proof_submitted": False, "closing_done": False, "closing": None}


def step(state, q1, q2, claim, description, policy, facts, closing=None, hours_since_proof_request=0):
    """One evaluation of the claim with the committee's majorities.

    closing: None if there was no closing round in this evaluation; if there was,
    {"response": the store's text ("" if it did not answer), "q2": Q2 majority on that answer,
    "proof": proof added by the buyer or None}.
    Returns (action, decision, new_state). action: "decide", "open_closing_round", "request_proof"
    or "wait"; decision: (decision, amount, reason).
    """
    state = dict(state)
    if s3.needs_closing_round(q1, q2, claim, description):
        if closing is None:
            if not state["closing_done"]:
                return "open_closing_round", ("NOT_YET", 0, "closing round"), state
            closing = state["closing"]  # the round already happened: judged with what it left
        elif state["closing_done"]:
            raise ValueError("closing round already held for this claim")
        else:
            state["closing_done"] = True
            state["closing"] = {"response": closing.get("response", ""), "q2": closing.get("q2"),
                                "proof": closing.get("proof")}
        label = s3.label(q1, q2, claim, description, closing.get("response", ""), closing.get("q2"),
                         closing.get("proof"))
    else:
        if closing is not None:
            raise ValueError("no closing round without a contradiction of facts")
        label = s3.label(q1, q2, claim, description)
    if label is None:
        return "decide", ("NO_CONSENSUS", 0, ""), state
    if label == "insufficient":
        if not state["proof_requested"]:
            state["proof_requested"] = True
            return "request_proof", ("NOT_YET", 0, "proof required"), state
        outcome = s3.decide_proof_request(label, True, state["proof_submitted"], hours_since_proof_request)
        return ("wait" if outcome[0] == "NOT_YET" else "decide"), outcome, state
    return "decide", s3.decide(label, policy, facts), state


def submit_proof(state, hours_since_proof_request):
    """The buyer sends the requested proof: only if it was requested, once, and within the 7 days."""
    if not state["proof_requested"]:
        raise ValueError("no proof was requested")
    if state["proof_submitted"]:
        raise ValueError("proof already submitted")
    if hours_since_proof_request >= s3.PROOF_WINDOW_HOURS:
        raise ValueError("proof window closed")
    return dict(state, proof_submitted=True)
