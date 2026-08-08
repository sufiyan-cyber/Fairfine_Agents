# FairFine — pitch notes

Answers to the two questions judges reliably ask, plus the demo order.

---

## 1. Why is this better than what banks already have?

Banks already have fraud detection. **They do not have an accountability layer,
and that is the thing that is actually broken.**

### The problem is not detection accuracy — it is the asymmetry

Every fraud engine sits on one dial. Turn it up and you catch more fraud and
wrongly block more innocent customers. Turn it down and you catch fraud late,
after the money is gone. Banks pick the second option, because a wrongful block
generates a furious phone call and a regulator-visible complaint, while a late
detection is quietly written off and insured.

So the industry's answer to "why is fraud caught late?" is: *because catching it
early is too dangerous to the customer.*

**FairFine breaks the dial into two independent questions:**

1. Is this fraud pattern real? (detection — banks already do this well)
2. Can it be attributed to someone other than the customer? (**nobody does this
   separately**)

You only act when both hold. That means the bank can turn detection *up* —
flagging aggressively — because aggression no longer translates into wrongful
blocks. The auditor absorbs the false positives.

### What is genuinely new

| What banks have | What FairFine adds |
|---|---|
| A risk score, and a threshold on it | A second model whose job is to **argue against** the first |
| Rules engines that add signals together | Five **independent vetoes** — any one stops the action |
| Case management for analysts after the fact | Escalation **before** the money stops moving |
| An audit trail in a database an admin can edit | A **hash chain** where tampering is detectable |
| "Your transaction was declined for security reasons" | The auditor's **actual reasoning**, verbatim, in four languages |
| Fairness testing in an annual model-risk review | A **live bias dashboard** by customer segment |

### The four defensible claims

**(a) Two independent questions, not one score.** A real card-testing pattern
attributed to the wrong actor is still a wrongful block. Splitting attribution
out as its own veto with its own floor is the core insight, and it is the thing
a threshold cannot express.

**(b) The weakest link governs.** Attribution reports per-indicator confidence
and the *minimum* decides. Every production system we know of averages or sums
signals, which lets a strong signal drown a fatal weakness.

**(c) Escalation is a first-class outcome.** Most engines are binary: block or
allow. Genuine uncertainty has nowhere to go, so it collapses into whichever
default the bank fears less. FairFine routes it to a human with the auditor's
specific unresolved doubts attached.

**(d) The explanation is the same text the machine decided on.** Not a
post-hoc summary generated for the customer — the auditor's reasoning field
*is* the customer-facing text, and the prompt is written knowing that. You
cannot have a decision rationale that differs from what the customer is told,
because there is only one string.

### The regulatory hook

RBI's customer-liability circular puts the **burden of proof on the bank**, not
the customer. A bank that blocks and cannot evidence why is exposed. FairFine
produces that evidence as a by-product of deciding — the hash-chained record,
the five checks, the cited rule and the reasoning are all generated before the
action is taken, not reconstructed afterwards when someone complains.

---

## 2. How does this scale?

### What is real today

- **Stateless audit path.** Every audit is a pure function of the uploaded case
  file. Nothing is held between requests, so horizontal scaling is just more
  instances.
- **Parallel perception.** Signal and attribution are independent questions and
  run concurrently in an ADK `ParallelAgent` — the stage costs one model call's
  latency, not two.
- **Retry and fallback ladder.** 429s are absorbed by retry, then a second
  Vertex *region*, then a smaller model, then that model in the second region.
  A busy capacity pool degrades latency, never availability.
- **Deterministic simulator.** The same verdict logic runs with no model calls
  at all — the regression suite for the decision boundaries, and a zero-quota
  fallback.
- **Bounded concurrency.** One audit at a time per instance caps resident
  memory; queued requests wait rather than stacking peaks and OOMing.

### What changes at a bank's volume

A mid-size Indian issuer generates roughly **50k–200k alerts/day**. Auditing
every one with a frontier model is neither affordable nor necessary. The path:

**Tier by stakes, not by volume.** Most alerts are unambiguous in both
directions. Route only the contested middle band to the full agent tree — in the
seeded distribution that is around a third of alerts. The rest resolve on the
deterministic rules the simulator already implements.

**Cache the account context.** Account tenure, prior wrongful blocks and travel
notices change daily, not per transaction. One lookup per account per day
instead of per alert.

**Batch the embeddings.** Already done — the duplicate sweep embeds in one
batched call rather than per-event, which was a real bug we fixed.

**Prompt caching.** The auditor prompt with its five vetoes is ~1,200 tokens and
identical on every call. Cached, it is close to free after the first request.

**Async, not request-response.** At production volume the audit belongs on a
queue, with the alert's action held pending the verdict. The pipeline already
streams its trace over SSE, so the shape is unchanged.

**Model tiering.** Flash handles perception; the auditor is the only stage that
would justify a larger model. That is already a config flag, not a rewrite.

### Honest cost sketch

At ~4k input / ~600 output tokens per audit on Flash, a fully-audited alert is
tens of paise. Against a single wrongful block — a complaint, an analyst's time,
a possible compensation claim under the RBI circular — the audit pays for itself
at a false-positive rate well under 1%. Real fraud engines run 10–100× that.

### What we would not claim

This has not been run at production volume, against a real card network, or on
real customer data. Every number above is reasoned from the architecture and
measured on synthetic cases. The honest claim is that **nothing in the design
blocks it**, not that it has been proven there.

---

## 3. Demo order (4 minutes)

1. **`01_impossible_travel_FALSE_POSITIVE.json`** — the money shot. The bank's
   model scored it 91%. The auditor notices the earlier merchant settles in
   nightly batch, so the timestamp is settlement, not purchase. Verdict ALLOW.
   The comparison panel shows a threshold engine would have blocked ₹3,100.
2. **`02_card_testing_REAL_FRAUD.json`** — it is not just a refusal machine.
   Three declines at one merchant in 90 seconds from an unseen device, then an
   approval. Verdict BLOCK at 93% trust.
3. **`03_first_purchase_AMBIGUOUS.json`** — attribution below the floor.
   Verdict REVIEW, and it appears in the Human Review queue with the auditor's
   unresolved doubts attached. Close it there.
4. **Customer view** — same decision, plain language, switch to हिन्दी.
5. **Bias dashboard** — the stop rate by customer segment. Name the disparity
   out loud; that is the point of measuring it.
6. **Ledger** — re-verify the chain live.

### If something breaks

- `FORCE_SIMULATION=1` on the Cloud Run service → deterministic, honest,
  labelled as simulation everywhere. ~60 seconds.
- Full rollback to the traffic-enforcement build: `git checkout traffic-demo`,
  and roll Cloud Run/Vercel back to the previous revision.
