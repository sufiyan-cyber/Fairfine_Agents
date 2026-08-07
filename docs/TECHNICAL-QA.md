# FairFine — technical Q&A

Answers to the questions judges actually ask. Each one leads with the short
answer; the detail underneath is there if they push.

---

## 1. Positioning — the question behind most questions

### "What does this do that the existing system doesn't?"

**FairFine is not in the detection path. It is in the issuance path.**

The ANPR camera detects. ITMS flags. Then — before a rupee is charged —
FairFine reviews that one flagged event and returns ISSUE / ESCALATE / REJECT.

> "We don't detect violations. Bengaluru already detects them well — 250 ANPR
> cameras, 87% of 2025's violations caught automatically. We review the
> decision to charge someone. Detection is a perception problem and it's
> solved. Issuance is a justice problem and nobody's touching it."

### "You'd be processing hours of video. That's not feasible."

You never process hours of video. The upstream system already did that and cut
a ~3 second clip when it flagged something. You process that clip.
`EVENT_WINDOW_SECONDS=3`, `FRAMES_PER_EVENT=3`.

Bengaluru issued **over 20 lakh challans in four months** — about **16,700
events a day**. Not 250 cameras × 24 hours. 16,700 three-second clips.

### "Enforcement is real-time. The fine is issued on the spot."

Not for camera enforcement. **88% of Bengaluru's cases are contactless** — the
camera detects, the system generates an e-challan, an SMS arrives later. There
is already a gap of hours between detection and issuance, currently filled by
a human clicking through a validation queue.

> "There's no real-time to disrupt. The gap between the camera seeing you and
> the SMS arriving is hours. We need thirty seconds of it."

Where enforcement *is* instant, an officer stopped you — so there's already a
human in the loop, and FairFine isn't for that.

### "Can it find every offender in an hour of footage?"

**No, and it shouldn't.** Multi-object detection across long footage is what
ITMS already does. Rebuilding it would duplicate working infrastructure.

> Say this *before* anyone tries it: **one event per upload**. A long clip
> returns one verdict, not a list.

### "It just adds cost to a system that works fine."

The system does not work fine. It works at **99.9% — self-reported, no
published methodology, no per-camera breakdown**. At 20 lakh challans per four
months, 0.1% is **~2,000 wrongful fines in four months — around 6,000 a year.**

Documented failures, not hypotheticals:

- AI cameras confusing a beige shirt with a beige seatbelt
- Rivets and screws on number plates read as zeros, fining the wrong owner
- A Royal Enfield owner challaned from images showing a Honda Activa
- The system ran from **December 2022 for roughly a year with no human
  validation at all**

**The cost line:**

> "It costs about two rupees to check a fine. It costs a citizen a day's wages
> to contest one — they have to go to the Traffic Management Centre on
> Infantry Road. We're arguing the cheaper of those two should happen first."

**The close:**

> "Every wrongful challan is an argument for not paying. Sixty-four percent
> already don't — ₹5,714 crore outstanding. Rejecting bad fines isn't a cost,
> it's what makes the good ones collectable."

### "They already have a human reviewing every AI flag."

They do. But that reviewer is **shown the AI's verdict first and asked to
confirm it** — anchoring, not auditing. No reasoning is recorded, so nobody
can check the 99.9% claim, including them.

FairFine's auditor is instructed to argue *against* issuing, and writes down
why. Then `/review` requires an officer to state a reason before a case can be
closed, and that reason goes into the same hash chain.

---

## 2. Architecture

### "Walk me through the system."

```
FairFineOrchestrator (SequentialAgent)
│
├─ IngestAgent        FunctionTool · ffmpeg/OpenCV frame sampling + metadata
│
├─ PerceptionStage    ParallelAgent
│   ├─ DetectorAgent  LlmAgent · gemini-2.5-flash · output_schema=Detection
│   └─ PlateAgent     LlmAgent · gemini-2.5-flash · output_schema=PlateRead
│
├─ MemoryAgent        BaseAgent · Qdrant duplicate sweep + MV Act RAG
│
├─ AuditorAgent ★     LlmAgent · gemini-2.5-flash · output_schema=Verdict
│
└─ VerdictRouter      BaseAgent
    ├─ ISSUE    → EvidenceAgent   (LlmAgent + mock VAHAN tool)
    ├─ ESCALATE → HumanQueueAgent → /review
    └─ REJECT   → RejectAgent     (dropped — still ledgered)

after_agent_callback → ledger append (every verdict, cannot be skipped)
```

Detection and plate reading **race in parallel**; everything after is
sequential because each stage needs the previous one's output.

### "Which ADK features are actually load-bearing?"

- `SequentialAgent` + `ParallelAgent` composition
- `output_schema` on **every** `LlmAgent` — no agent may answer in free text
- `before_model_callback` → PII scrub at prompt assembly, so nothing
  unredacted can reach a model even if an upstream prompt changes
- `after_agent_callback` → ledger append bound to the orchestrator, plus a
  bias screen on the auditor's reasoning before it becomes citizen-facing
- Session state as the hand-off medium between stages
- `FunctionTool` → VAHAN lookup and MV Act retrieval

### "Why an LLM for the audit rather than rules?"

The vetoes *are* rules — thresholds, a plate-confidence floor, a duplicate
window. What needs a model is judging whether the **evidence supports the
claim**: whether an oblique camera angle makes a stopped car look past the
stop line, whether glare makes a seatbelt unreadable. That's a visual
reasoning problem, and it's exactly where the existing systems fail.

---

## 3. The auditor

### "What makes it 'adversarial'?"

One asymmetry, written into the prompt: a missed violation costs the state a
little revenue; a wrongful fine costs a person money, a day of work, and their
trust in the system. Those aren't equivalent — so the auditor is told to argue
*against* issuance wherever doubt exists.

### "What are the actual decision rules?"

Five checks, each with a **hard veto**:

| Check | Fails when |
|---|---|
| Visual confirmation | Parallax, cropping, or misattribution to an adjacent vehicle |
| Plate reliability | `min_confidence < 0.85` → **never ISSUE**, always ESCALATE |
| Environment | Occlusion, low light, rain, motion blur, headlight glare |
| Duplicate | Near-identical event, same plate + location, inside 60s |
| Rule applicability | The cited MV Act section doesn't match what's shown |

Verdicts: **ISSUE** at trust ≥ 0.90 with all checks passing · **ESCALATE** at
0.60–0.90 or any unreliable plate · **REJECT** otherwise. Ties break toward
ESCALATE — a human should see it.

Thresholds are configurable and exposed at `/api/architecture`, so they're
auditable rather than buried.

### "Isn't the trust score just a number the model made up?"

Partly, and we say so. It's currently a Bayesian combination of detector
confidence, plate confidence and the check outcomes. **It is not yet
calibrated against adjudicated outcomes** — that's the honest v1 gap, and it's
listed in the README. Calibration needs real dispute results to train on,
which needs a deployment.

---

## 4. The ledger

### "What stops someone editing a verdict afterwards?"

Each record hashes as `SHA-256(prev_hash + canonical_json(payload) + ts)`.
Editing any historical payload invalidates every hash after it.
`GET /api/ledger/verify` recomputes from genesis and detects both payload
tampering and re-linking. Appends serialise through a lock so two concurrent
verdicts can't fork the chain.

The smoke test **deliberately tampers with a record**, proves the chain
detects it, locates the bad record, and re-verifies after restore.

### "The chain protects the verdict. What protects the evidence?"

`frames_sha256` in the payload. Each evidence frame is hashed, then the
concatenation is hashed — so the chain commits to the frames **and their
order**, and an individual frame can still be checked on its own.

Without it the ledger would prove only that a verdict was never altered, while
the images shown beside it sat in a separate table, swappable under an
untouched decision. Verified: swapping one frame while leaving the verdict,
trust score and reasoning untouched is detected.

**This is the Rule 167A answer.** [Rule 167A CMVR] requires every
auto-generated challan to carry clear photographic evidence, the device
measurement, date/time/place, the provision violated, **and a Section 65B
certificate**. A Srinagar court has quashed e-challans for non-compliance.

> "This isn't only about fairness. Every challan you issue today is one writ
> petition away from being unenforceable. We make them defensible."

### "What happens on a dispute?"

The dispute **appends** a re-audit rather than overwriting the original, so a
reversal stays permanently visible. Same for human review — a `HUMAN_REVIEW`
record sits beside the untouched `AUDIT` record.

---

## 5. Human in the loop

### "Show me what the officer sees."

`/review`. The queue of escalated cases; click one and you get the escalation
reason, the trust score against the thresholds, which of the five checks
passed and failed, the auditor's reasoning, and the evidence frames — the same
packet the auditor judged, not a summary of it.

An officer **cannot close a case without stating a reason**. The reason is
PII-redacted, stored, and appended to the ledger as `HUMAN_REVIEW`. The
auditor's own verdict is left standing beside it.

> "A queue nothing can answer would reproduce exactly the failure we're
> naming: a human check with no record of whether anyone actually looked."

---

## 6. Memory and duplicates

### "How does duplicate detection work?"

Every audited event is embedded and stored in Qdrant with its plate, location,
violation type and timestamp. A new event is swept against that store; a
near-identical match on the same plate and location inside 60 seconds is
flagged as a duplicate and rejected.

This is the fourth demo scenario: run the same clip twice, and the second run
is rejected. **Nobody gets charged twice for one event.**

Collections are namespaced by embedding dimension (`fairfine_events_d3072`) so
a deployment that changes embedding models can't write wide vectors into a
narrow collection. FairFine never drops a collection — only creates and
upserts — so the cluster is safe to share.

### "What if Qdrant is down?"

An in-process cosine index serves the same interface over the same embeddings.
`/api/health` reports which backend is actually live, so the UI never claims
Qdrant when it's on the fallback.

---

## 7. Privacy and safety

### "You're handling citizen data. What stops it leaking?"

- **Owner identity is withheld from models entirely** — not masked, dropped.
  Who owns a vehicle is never a valid input to whether a violation occurred.
- **Every LLM call is PII-scrubbed at prompt assembly**, via
  `before_model_callback`, and the local redactor runs whether or not Enkrypt
  is configured.
- Free-text from citizens (disputes) and officers (review notes) is redacted
  before being stored or ledgered.
- **No real Parivahan/VAHAN integration.** `tools/vahan.py` is deterministic
  and synthetic; the raw owner name never leaves that module.
- **All demo plates synthetic.** Clips are drawn frame by frame in OpenCV; no
  real vehicle appears anywhere.
- Running on Vertex means the deployment carries **no API key at all** —
  it authenticates with the runtime's service account.

### "Could this be used to fine more people, more aggressively?"

It can only ever reduce issuance. The auditor's outputs are ISSUE, ESCALATE or
REJECT against a decision that has *already been made upstream* — it never
originates a violation. The worst case is it agrees with the existing system.

---

## 8. Operations

### "What does it cost to run?"

Per audit: roughly 14k input / 2k output tokens across ~4–5 model calls.

| | per audit | Bengaluru at 16,700/day |
|---|---|---|
| Flash | ~₹0.30 | ~₹18 lakh/year |
| Pro auditor | ~₹2 | ~₹1.2 crore/year |

And you don't have to audit everything — triage on the upstream confidence
score, audit the uncertain 20%, and it's a rounding error against ₹5,714 crore
in unpaid challans.

### "How fast is it?"

37–53 seconds per audit end to end on Flash. That's not the constraint:
issuance is already hours behind detection.

### "What happens when Gemini rate-limits you?"

Transient 429/500/503 are retried with exponential backoff and jitter,
honouring the server's own `retryDelay`. If the auditor's model is still
exhausted, the audit **re-runs on a smaller model rather than failing** — same
prompt, same five vetoes, same thresholds, so the verdict is shallower, not
different. Auth and request errors (403/400) fail immediately rather than
being retried pointlessly.

### "Why Vertex rather than the Gemini API?"

Vertex bills to the project's Cloud billing account, authenticates with the
runtime's service account rather than a key, and keeps no API key in the
deployment. `/api/health` reports `gemini-via-vertex` so it's visible which
backend answered.

### "Simulation mode — isn't that fake?"

It's a deterministic rule engine standing in for the models, and **the mode is
displayed in the nav on every screen**. The verdict rules, thresholds and
vetoes are identical in both modes; only perception differs. Claiming live
inference while simulating would undercut the entire premise, so the app never
does.

---

## 9. Known limitations — say these before they're found

Being first to name these reads as confidence, not weakness.

- **Not a detector.** One event per upload; it won't enumerate offenders in a
  long clip. By design — ITMS does that.
- **Demo clips are synthetic**, drawn frame by frame in OpenCV so no real
  plate or vehicle appears. Live vision on hand-drawn clips is noisy, which is
  why the scripted narrative runs on the deterministic engine.
- **The ledger is SQLite on an ephemeral container.** Fine for a demo; a
  production deployment moves it to Cloud SQL or a GCS-backed volume. The
  `db.py` interface is small and the hashing is storage-agnostic.
- **VAHAN is mocked.** Deliberately — see the privacy section.
- **The trust score isn't calibrated** against adjudicated outcomes yet.
- **Plate reading uses Gemini vision**, not a specialised ANPR model.
  Production would use PaddleOCR/YOLO for the plate and keep the model for the
  judgement.

---

## 10. Numbers worth memorising

| | |
|---|---|
| Bengaluru ANPR cameras | 250 (+80 red-light), ITMS at 30 junctions |
| AI-detected violations, 2025 | 87% |
| Contactless cases, Jan–Apr 2025 | 88% |
| Challans, Jan–Apr 2025 | Over 20 lakh (~16,700/day) |
| Claimed accuracy after manual review | 99.9%, self-reported |
| Implied wrongful fines | ~2,000 per 4 months (~6,000/year) |
| Period with no human validation | ~1 year from Dec 2022 |
| Unpaid challans, 2025 | 64% — 3.31 crore of 5.16 crore |
| Outstanding fine value | ₹5,714 crore |
| Cost to audit one fine | ~₹0.30 (Flash) |

Thresholds: ISSUE ≥ 0.90 · ESCALATE 0.60–0.90 · plate floor 0.85 · duplicate
window 60s.
