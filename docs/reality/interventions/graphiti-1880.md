# Draft intervention — Graphiti #1880

Do not post this until we verify the current hook location on Graphiti main.

Suggested comment:

I think the useful boundary here is to keep two decisions separate: source-faithfulness and store-conflict.

A minimal hook contract could receive the raw episode span, the resolved candidate fact, and any conflicting/related persisted facts, then return a structured receipt rather than just a bool:

- outcome: accept | refuse | contested | review
- reason_code
- evidence/source ids
- supersedes/refutes ids when applicable
- verifier name/version
- optional confidence

That keeps Graphiti in control of graph lifecycle while allowing local NLI/attribution or an external verifier to plug in without owning storage.

One reason I would keep the receipt explicit: in a separate retrieval experiment I ran, the decisive source was ranked 17 in two controlled cases. A top-5 view looked plausible but made the contradiction unavailable; the failure was not “bad generation”, it happened before the judge ever saw the evidence. A verification hook has the same observability problem unless rejected/contested facts leave a trace.

If this contract direction is useful, I can turn it into a small typed Protocol + no-op default + regression fixture against current main before proposing a PR.
