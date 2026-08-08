# FairFine — technical brief

What the system is, what it is built on, how a decision actually flows through
it, and — the question that gets asked hardest — what a language model is and
is not allowed to see.

---

## 1. What it is, in one paragraph

A bank's fraud model flags a transaction. Instead of acting on that flag,
FairFine runs an adversarial multi-agent audit that must independently confirm
two separate things — that the fraud pattern is real, **and** that it is
attributable to someone other than the account holder — before the bank is
allowed to hold anyone's money. Anything uncertain goes to a human. Every
decision is written to a tamper-evident hash chain and explained to the
customer in plain language, in their own language, with a dispute that
genuinely re-runs the audit.

---

## 2. Tech stack

### Google technologies (the core of the build)

| Product | How it is used | Why it, specifically |
|---|---|---|
| **Google Agent Development Kit (ADK)** | The entire orchestration layer. `SequentialAgent` root, `ParallelAgent` perception stage, `LlmAgent` for every model-backed step, custom `BaseAgent` subclasses for deterministic steps, `FunctionTool` for lookups, session state as the hand-off medium | Gives structural guarantees a hand-rolled chain cannot: `output_schema` makes free-text answers impossible, and `before_model_callback` / `after_agent_callback` are enforcement points that fire regardless of what any prompt says |
| **Gemini 2.5 Flash** | Signal classification, attribution scoring, the adversarial auditor, the customer explainer, case-file drafting | Multimodal-capable but used here purely on structured text. Flash was measured at 37–53s per full audit against Pro's 57–103s, reaching the same verdicts — the prompt and the five vetoes decide a case, not model size |
| **Gemini 2.5 Flash-Lite** | Automatic fallback tier when the primary model is rate-limited | A shallower verdict beats an error. `capability_report()` reports which model actually answered |
| **Vertex AI** | The inference backend for every Gemini call | Runs inside the project's own GCP tenancy under Application Default Credentials — **no API key exists anywhere in the deployment**. Data-governance terms differ materially from the consumer Gemini API. Region-pinned to `asia-south1` for data residency |
| **Vertex AI Embeddings** (`google-genai`) | Vector embeddings for the near-duplicate alert sweep and rulebook retrieval | Batched at startup — an earlier per-item implementation exhausted the embedding quota in 22 requests |
| **Cloud Run** | Hosts the FastAPI backend, `asia-south1` | Scales to zero, and the service account *is* the Vertex credential — no secret to leak |
| **Cloud Build** | Container build on `gcloud run deploy --source` | — |
| **Cloud Logging** | Retry/fallback telemetry, 429 diagnosis | This is how the `global`-endpoint capacity problem was actually found |
| **Application Default Credentials** | Auth for Vertex, both locally and on Cloud Run | Removes the API key as an artifact entirely |

### Everything else

| Layer | Choice |
|---|---|
| API | FastAPI + Uvicorn, Server-Sent Events for the live agent trace |
| Contracts | Pydantic v2 — every agent hand-off is a typed schema |
| Config | pydantic-settings, env-driven, every dependency optional |
| Persistence | SQLite — challans, hash-chained ledger, review queue, disputes |
| Semantic memory | Qdrant Cloud when configured; an in-process cosine index over the same embeddings when not |
| Guardrails | Enkrypt AI when configured; a local regex redactor + bias deny-list when not |
| Frontend | Next.js 16 (Turbopack), React, Tailwind, deployed on Vercel |

**Design rule:** every external dependency is optional and degrades to a
working local implementation. With no keys at all the whole pipeline still runs
end to end on a deterministic rule engine, and the UI labels that mode honestly
on every screen. Nothing ever claims live inference while simulating.

---

## 3. How a decision flows

```
POST /api/audit  (multipart: alert.json)
  │
  ├─ _persist_upload — extension allowlist (.json/.txt), 10 MB ceiling,
  │                    empty-file rejection
  │
  ├─ _audit_gate — one audit at a time per instance, so concurrent
  │                requests queue instead of stacking memory peaks
  │
  ▼
pipeline.run_audit()  ──yields SSE trace events throughout──▶ browser
  │
  1. IngestAgent          parse JSON → flagged txn + account history
  │                       card number reduced to last 4 AT THIS POINT
  │                       mock account + merchant lookups
  │
  2. PerceptionStage      ParallelAgent — both run concurrently
  │   ├─ SignalAgent      → RiskSignal   (fraud_type, evidence, confidence)
  │   └─ AttributionAgent → AttributionRead (indicators + per-indicator
  │                          confidence; the MINIMUM governs)
  │
  3. MemoryAgent          duplicate-alert sweep (semantic + structured)
  │                       + fraud-rulebook retrieval
  │
  4. AuditorAgent ★       adversarial review → Verdict
  │                       five independent vetoes, calibrated trust score
  │
  5. VerdictRouter        ISSUE → EvidenceAgent   (case file drafted)
  │                       ESCALATE → HumanQueueAgent (review queue)
  │                       REJECT → RejectAgent   (dismissed, still ledgered)
  │
  6. LedgerAgent          SHA-256 chain append — bound as an
  │                       after_agent_callback so no verdict can skip it
  ▼
persist challan → enqueue review if escalated → remember event → stream result
```

### The five vetoes

Any one of these failing stops the block. They are checked in order and the
first that applies decides:

1. **Duplicate** → REJECT. One event gets one action.
2. **Pattern not confirmed** → REJECT. Batch-settlement artifacts, truncated
   history, behaviour matching the customer's own record.
3. **Attribution unreliable** (`min_confidence < 0.85`) → **ESCALATE, never
   REJECT.** A genuine compromise you cannot yet pin on a non-customer must not
   be dismissed *or* acted on — a human makes contact.
4. **All clear and `trust_score ≥ 0.90`** → ISSUE. The block is justified.
5. **Anything else** → ESCALATE.

### Reliability engineering

Rate limits are the likeliest way a live system breaks, so the failure path is
a ladder, not a cliff:

```
retry (4 attempts, honours the server's own retryDelay, 60s cumulative cap)
  → same model, fallback region (us-central1)
    → smaller model, primary region
      → smaller model, fallback region
```

Regions hold **separate capacity pools**, which is why a region hop is a real
second chance rather than another spin of the same wheel. The retry logic walks
`ExceptionGroup` trees as well as `__cause__`/`__context__`, because ADK's
`ParallelAgent` runs on an asyncio TaskGroup and a 429 raised in flight arrives
wrapped in a group whose children a naive cause-walk never reaches.

---

## 4. "You're just handing financial data to an LLM"

No. This is the design constraint the system was built around, and there are
six separate mechanisms — four of which are structural rather than
prompt-based, meaning they hold even if a prompt is changed carelessly later.

### 4.1 Minimisation at the boundary, before anything else runs

`mask_account()` runs during ingest, before any model call, before anything
enters session state:

```
4532111122224821  →  •••• 4821
```

The full PAN is reduced to its last four digits at the edge. It is not masked
for display while the real value travels underneath — the real value is
**discarded**. Nothing downstream, including the database and the ledger, ever
holds it.

### 4.2 Identity is dropped, not masked — via an allowlist

`scrub_owner_record()` reduces the account record to an explicit allowlist and
replaces the customer entirely:

**Survives** (legitimate evidence about an *account*): tenure in years, prior
confirmed fraud, prior disputes, prior **wrongful blocks**, travel notice on
file, customer segment, issuing branch.

**Dropped**: the name. Replaced with the literal `[WITHHELD_FROM_MODEL]`.

This is an allowlist, not a denylist — a new field added to the mock core
banking record does not silently start reaching the model. It has to be
added deliberately.

### 4.3 A structural scrub at prompt assembly

`pii_scrub_callback` is registered as ADK's `before_model_callback` on **every**
`LlmAgent`. It fires on the assembled request, mutating parts in place, after
the prompt is built but before it leaves the process. This is the enforcement
point: it does not matter what a prompt template says, what an upstream agent
put in session state, or whether a future developer forgets — nothing reaches a
model without passing through it.

The local redactor catches, and replaces with `[REDACTED_*]`:

| Label | Pattern |
|---|---|
| `AADHAAR` | 12-digit, spaced or unspaced |
| `PAN` | `ABCDE1234F` |
| `PHONE` | Indian mobile, with or without +91 |
| `EMAIL` | RFC-ish address |
| `DL_NUMBER` | Driving licence |
| `ADDRESS_PIN` | 6-digit PIN code |
| `ACCOUNT` | any bare 11–18 digit run |

Enkrypt AI layers on top when an API key is present. **The guarantee holds in
both modes** — the local path is a real redactor, not a stub, and a guardrail
outage can never take the pipeline down or silently disable the scrub.

Every redaction is recorded in session state as a `guardrail_events` entry, so
the scrub is auditable rather than invisible.

### 4.4 The model cannot answer in free text

Every `LlmAgent` carries an `output_schema`. The model emits a typed Pydantic
object — `RiskSignal`, `AttributionRead`, `Verdict` — and nothing else. There
is no channel through which it can return unstructured content, echo back its
input, or improvise a field.

### 4.5 Customer free-text is scrubbed too

When someone disputes a decision, their words go into a prompt. That text is
passed through `redact_pii()` **before** prompt assembly — which protects the
disputant from themselves if they paste a card number or an Aadhaar into the
box, as people do.

### 4.6 Bias screening on the way out

`bias_screen_callback` runs as an `after_agent_callback` on the auditor and
screens the reasoning for prejudicial justification before it can become
customer-facing evidence. The auditor prompt separately forbids reasoning from
caste, religion, class, neighbourhood, income bracket, or the fact that someone
holds a student or pensioner account. The screen exists because a prompt
instruction is a request, not a guarantee.

### What the model actually receives

Concretely, the auditor's context is a transaction ledger:

```
   TIME (UTC)             AMOUNT  CHANNEL       CATEGORY   MERCHANT              CITY        STATUS    DEVICE
   2026-08-08 08:30:00  INR 1,400  card_present  fuel       HP Petro Stop         Bengaluru   approved  dev_home_01
   2026-08-08 14:17:30  INR    39  ecom          gift_card  GiftCardHub Online    Unknown     declined  dev_unknown_9f2
>> 2026-08-08 14:20:00  INR    42  ecom          gift_card  GiftCardHub Online    Unknown     approved  dev_unknown_9f2

Account:   •••• 4821
Customer:  [WITHHELD_FROM_MODEL]
Segment:   Salaried professional
Tenure:    14 years
Prior wrongful blocks: 2
```

Timestamps, amounts, merchant categories, channels, opaque device identifiers,
cities. **No name, no full card number, no address, no phone, no email, no
government identifier.** The model reasons about *behaviour*, which is what the
decision legitimately turns on, and it is structurally prevented from reasoning
about *identity*, which it never is.

### Residency and tenancy

Inference runs on **Vertex AI inside the project's own GCP tenancy**, pinned to
`asia-south1`, authenticated by the Cloud Run service account. Not the consumer
Gemini API. There is no API key in the deployment to leak, and prompts do not
traverse a consumer endpoint.

### Honest limits

All demo data is synthetic — generated deterministically, no real cardholder or
merchant data, no core-banking integration, no payment network. A production
deployment would additionally need a tokenisation vault, encryption at rest
beyond SQLite defaults, a formal DPIA, and the bank's own retention policy
applied to the ledger. Nothing in the architecture obstructs any of that, but
none of it is claimed to be done.

---

## 5. Why this beats what banks run today

Banks already have fraud detection. What they lack is an accountability layer —
and that is the part that is actually broken.

**The asymmetry nobody prices in.** Every fraud engine sits on one dial. Turn
it up: catch more fraud, wrongly block more innocent people. Turn it down:
catch fraud late, after the money is gone. Banks choose late, because a
wrongful block produces a furious customer and a regulator-visible complaint
while a missed fraud is quietly written off and insured. The industry's own
answer to *"why is fraud caught late?"* is: **because catching it early is too
dangerous to the customer.**

FairFine breaks the single dial into two independent questions and only acts
when both hold. That lets a bank turn **detection up** — because aggression no
longer converts into wrongful blocks. The auditor absorbs the false positives.

| What banks have | What FairFine adds |
|---|---|
| A risk score and a threshold | A second model whose job is to **argue against** the first |
| Rules engines that sum signals | Five **independent vetoes** — any one stops the action |
| Case management *after* the fact | Escalation **before** the money stops moving |
| An audit trail in an editable table | A **hash chain** where tampering is detectable |
| "Declined for security reasons" | The auditor's **actual reasoning**, verbatim, in four languages |
| Fairness review once a year | A **live bias dashboard** by customer segment |

### The four claims worth defending

**Attribution is its own veto, with its own floor.** A real card-testing
pattern pinned on the wrong person is still a wrongful block. A single
threshold cannot express that; two independent gates can.

**The weakest link governs, not the average.** Attribution reports
per-indicator confidence and the **minimum** decides. Production systems sum or
average, which lets one strong signal drown a fatal weakness. (This rule has a
sharp edge we hit and fixed: listing weak corroborating detail alongside
decisive findings vetoed clear-cut cases, so the contract now says the list
carries only findings you would act on standing alone.)

**Escalation is a first-class outcome.** Most engines are binary, so genuine
uncertainty collapses into whichever default the bank fears less. Here it
routes to a human with the auditor's specific unresolved checks attached.

**The explanation *is* the decision text.** Not a summary generated afterwards
for the customer — the auditor's `reasoning` field is what the customer reads,
and the prompt is written knowing that. The rationale and the explanation
cannot diverge, because there is only one string.

### The regulatory hook

RBI's customer-liability circular puts the **burden of proof on the bank**. A
bank that blocks and cannot evidence why is exposed. FairFine produces that
evidence as a by-product of deciding — the hash-chained record, the five
checks, the cited rule and the reasoning all exist *before* the action is
taken, rather than being reconstructed after a complaint.

---

## 6. The demonstrable claim

On the impossible-travel case, live against Vertex:

- The bank's model scored it **91%** — confidently wrong.
- The auditor noticed the earlier merchant settles in nightly batch, so the
  timestamp reflects settlement rather than purchase; found a travel notice on
  file; and weighed a 14-year account with two prior *wrongful* blocks.
- Verdict: **ALLOW**, trust 5%.
- A threshold-only engine would have held **₹3,100**.

And on real card testing, the same system reaches **BLOCK at 95%**. It is not a
machine that only ever refuses — it is one that refuses *for reasons it can
state*.
