# FairFine

**The accountability layer for automated traffic enforcement.**

> Adversarial audit + cryptographic evidence + public dispute — before a single rupee is charged.

Automated enforcement issues fines from a single confidence score. FairFine puts an
adversarial reviewer in front of that decision — one instructed to *prevent wrongful
fines*, not confirm them — then writes every verdict to a hash-chained ledger and hands
the reasoning to the citizen in their own language, with a dispute that genuinely re-runs
the audit.

It plugs into existing CCTV/ANPR infrastructure. It does not replace police: ambiguous
cases go to a human by design.

---

## Quick start

Two terminals. No API keys required — the pipeline runs end-to-end in **simulation mode**
with a deterministic rule engine standing in for the models.

**Backend**

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
```

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend && npm install && npm run dev
```

Then seed a decision history and generate the demo clips:

```bash
cd backend && .venv/Scripts/python scripts/make_demo_clips.py && .venv/Scripts/python scripts/seed_demo.py
```

Open <http://localhost:3000>.

> On macOS/Linux the venv binaries live in `.venv/bin/` rather than `.venv/Scripts/`.

---

## Going live

Every dependency is optional and degrades to a working local implementation. Copy
`backend/.env.example` to `backend/.env` and fill in what you have:

| Variable | Without it | With it |
|---|---|---|
| `GEMINI_API_KEY` | Deterministic rule engine; UI shows **simulation mode** | Full ADK pipeline on Gemini 2.5 |
| `USE_VERTEX` + `GOOGLE_CLOUD_PROJECT` | Gemini Developer API, authenticated by key | Same models via Vertex, authenticated by the runtime's service account — no key in the deployment |
| `QDRANT_URL` / `QDRANT_API_KEY` | In-process cosine index over the same embeddings | Qdrant Cloud collections |
| `ENKRYPT_API_KEY` | Local regex PII redactor + bias deny-list | Enkrypt AI guardrails on top |

The mode is displayed in the nav on every screen, and reports *which* backend answered —
`gemini` or `gemini-via-vertex`. Claiming live inference while simulating would undercut
the whole premise, so the app never does.

---

## Architecture

```
FairFineOrchestrator (SequentialAgent)
│
├─ IngestAgent           FunctionTool · ffmpeg/OpenCV frame sampling + metadata
│
├─ PerceptionStage       ParallelAgent
│   ├─ DetectorAgent     LlmAgent · gemini-2.5-flash · output_schema=Detection
│   └─ PlateAgent        LlmAgent · gemini-2.5-flash · output_schema=PlateRead
│
├─ MemoryAgent           BaseAgent · Qdrant duplicate sweep + MV Act RAG
│
├─ AuditorAgent ★        LlmAgent · gemini-2.5-flash · output_schema=Verdict
│
└─ VerdictRouter         BaseAgent
    ├─ ISSUE    → EvidenceAgent   (LlmAgent + mock VAHAN tool)
    ├─ ESCALATE → HumanQueueAgent (writes pending_review with uncertainty notes)
    └─ REJECT   → RejectAgent     (dropped — still ledgered)

after_agent_callback → ledger append (every verdict, cannot be skipped)

CitizenAgent   separate entrypoint · explains the decision in en/hi/kn/ta
ReAuditAgent   invoked on dispute · re-decides against the stored evidence
ReviewAgent    the human · resolves ESCALATE at /review, ledgered as HUMAN_REVIEW
```

**On model choice.** The auditor runs on Flash, not Pro. Pro is served from a busier
shared pool: measured against these clips it answered in 57–103s and returned 429s under
ordinary rehearsal load, while Flash answered in 41–57s and reached the same verdicts.
What decides a case is the prompt, the five vetoes and the thresholds — identical either
way. Set `AUDITOR_MODEL=gemini-2.5-pro` to take the deeper reasoning and accept the
latency; `AUDITOR_FALLBACK_MODEL` then re-runs the audit a tier down rather than failing
it when that pool is saturated. Transient 429s and 503s are retried with backoff,
honouring the server's own `retryDelay`, before any of that is reached.

**ADK features carrying real weight**

- `SequentialAgent` + `ParallelAgent` composition — detection and plate reading race.
- `output_schema` on every `LlmAgent` — no agent may answer in free text.
- `before_model_callback` → Enkrypt PII scrub on the assembled request, so nothing
  unredacted can reach a model even if an upstream prompt changes.
- `after_agent_callback` → ledger append bound to the orchestrator, and a bias screen on
  the auditor's reasoning before it becomes citizen-facing evidence.
- Session state as the hand-off medium between every stage.
- `FunctionTool` → mock VAHAN lookup and MV Act section retrieval.

### The auditor

The product is the prompt. It is written around one asymmetry: a missed violation costs
the state a little revenue; a wrongful fine costs a person money, a day of work, and
their trust in the system. Those are not equivalent, so the auditor is told to argue
*against* issuance wherever doubt exists, and five checks each get a hard veto:

| Check | Fails when |
|---|---|
| Visual confirmation | Parallax, cropping, or misattribution to an adjacent vehicle |
| Plate reliability | `min_confidence < 0.85` → **never ISSUE**, always ESCALATE |
| Environment | Occlusion, low light, rain, motion blur, headlight glare |
| Duplicate | Near-identical event, same plate + location, inside 60s |
| Rule applicability | The cited MV Act section does not match what is shown |

Verdicts: `ISSUE` at trust ≥ 0.90 with all checks passing · `ESCALATE` at 0.60–0.90 or any
unreliable plate · `REJECT` otherwise. Ties break toward ESCALATE — a human should see it.

### The ledger

Each record hashes as `SHA-256(prev_hash + canonical_json(payload) + ts)`. Appends
serialise through a lock so two concurrent verdicts cannot fork the chain.
`GET /api/ledger/verify` recomputes from genesis and detects both payload tampering and
re-linking. Disputes **append** a re-audit rather than overwriting the original, so a
reversal stays permanently visible.

The payload also carries `frames_sha256` — each evidence frame hashed, then the
concatenation hashed, so the chain commits to the frames *and* their order. Without it
the ledger would prove only that a verdict was never altered, while the images shown
beside it sat in a separate table, unhashed and swappable under an untouched decision.
This is the property Rule 167A leans on: the evidence a citizen is shown is provably the
evidence the verdict was drawn from.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/audit` | Multipart upload. SSE agent trace by default; `?stream=false` for one JSON response |
| `GET` | `/api/challan/{id}` | Officer view — full evidence packet |
| `GET` | `/api/challan/{id}/citizen?lang=kn` | Citizen view, plain language |
| `POST` | `/api/challan/{id}/dispute` | `{reason}` → triggers ReAuditAgent |
| `GET` | `/api/review-queue` | Open escalations awaiting an officer |
| `POST` | `/api/review/{id}/decide` | `{decision, officer, note}` → closes an escalation, appended as `HUMAN_REVIEW` |
| `GET` | `/api/ledger` | Paginated ledger records |
| `GET` | `/api/ledger/verify` | Recompute the chain → `{valid, broken_at?}` |
| `GET` | `/api/dashboard/bias` | Aggregates by area, vehicle type, violation, hour |
| `GET` | `/api/architecture` | Machine-readable agent tree + thresholds |
| `GET` | `/api/rules?q=` | Semantic search over the MV Act corpus |
| `POST` | `/api/demo/reset` | Wipe state so a pitch can re-run from zero |
| `POST` | `/api/demo/seed` | Replay the seed history through the pipeline — `?force=true` to reseed a non-empty ledger |

Interactive docs at `/docs`.

---

## Screens

| Route | What it does |
|---|---|
| `/` | Landing — thesis, live counters read from the running system |
| `/console` | Officer console — upload, live SSE agent trace, verdict, **naive vs FairFine** split |
| `/challan/[id]` | Citizen portal — plain-language reasoning, 4 languages, evidence, dispute |
| `/review` | Human review — the escalation queue, the evidence the auditor judged, and the officer's decision |
| `/ledger` | Ledger explorer — records, hash links, live chain verification |
| `/dashboard` | Bias dashboard — disaggregated false-positive rates |

**Design**: dark OLED operations console. IBM Plex Sans for institutional credibility,
JetBrains Mono for anything read character by character (plates, hashes, scores). Verdict
colour reads from the citizen's side of the transaction — green REJECT means *a wrongful
fine was prevented*, red ISSUE means *money is being taken from someone* — and every
verdict is labelled in text as well as colour.

---

## Demo script (45 seconds)

```bash
cd backend && .venv/Scripts/python scripts/make_demo_clips.py
```

Four synthetic clips are written to `backend/data/demo_clips/`. Every frame is drawn from
scratch with OpenCV — no real footage, no real registration plates anywhere.

1. **`clean_helmet_…`** → `ISSUE` at 93% trust. The system works.
2. **`occluded_plate_…`** → `ESCALATE`. Violation is obvious; one plate character reads at
   58%. Charging the wrong vehicle is still a wrongful fine.
3. **`parallax_redlight_…`** → `REJECT`. **The money frame.** The oblique camera makes a
   stopped car look past the stop line. The naive panel shows the ₹1,000 that would have
   been charged.
4. **Re-run clip 1** → `REJECT` as a duplicate. Nobody gets charged twice.

Then open the citizen portal from any issued challan, switch to ಕನ್ನಡ, file a dispute, and
watch the verdict flip — with both decisions visible in `/ledger`.

---

## Tests

```bash
cd backend && PYTHONPATH=scripts .venv/Scripts/python scripts/smoke_test.py
```

41 checks across the full surface: all four demo clips reach their expected verdicts, SSE
streams, all four citizen languages render, the dispute re-audit runs and its PII is
scrubbed, the dashboard aggregates — and the ledger **detects a deliberately tampered
payload**, locates the bad record, and re-verifies after restore.

---

## Deploy

### Backend → Cloud Run

```bash
gcloud run deploy fairfine-api --source backend --region asia-south1 --allow-unauthenticated --port 8080 --memory 2Gi --max-instances 1 --set-env-vars "GEMINI_API_KEY=...,CORS_ORIGINS=https://your-app.vercel.app"
```

> **`--max-instances 1` is load-bearing for the demo.** Cloud Run's filesystem is
> ephemeral and per-instance: the SQLite ledger lives only as long as the container, and
> two instances would maintain two independent chains that each verify but disagree. For
> anything beyond a demo, move the ledger to Cloud SQL or a GCS-backed volume — the
> `db.py` interface is small and the hashing logic is storage-agnostic. The PRD's
> production note (Walrus / on-chain) belongs here.

### Frontend → Vercel

```bash
cd frontend && vercel --prod
```

Set `NEXT_PUBLIC_API_URL` to the Cloud Run URL in the Vercel project's environment
variables, then set `CORS_ORIGINS` on the backend to the Vercel domain.

---

## Guardrails

These are enforced in code, not just documented:

- **No real Parivahan/VAHAN integration.** `tools/vahan.py` is deterministic and synthetic;
  the raw owner name never leaves that module.
- **No real citizen PII.** Registry records are generated from a hash of the plate.
- **All demo plates synthetic.** Clips are drawn frame by frame; no real vehicle appears.
- **Owner identity is withheld from models entirely** — not masked, dropped. Who owns a
  vehicle is never a valid input to whether a violation occurred.
- **Every LLM call is PII-scrubbed at prompt assembly**, via `before_model_callback`, and
  the local redactor runs whether or not Enkrypt is configured.
- **Human in the loop for ambiguity.** FairFine is decision support. It does not replace
  police officers. `ESCALATE` is a real outcome with a real screen: an officer cannot
  close a case without stating a reason, that reason is redacted and ledgered, and the
  auditor's own verdict is left standing beside it. A queue nothing can answer would
  reproduce the failure this project exists to name — a human check with no record of
  whether anyone looked.

## Not built (by design)

A new detection model, hardware, or a real state-portal integration. FairFine rides
existing infrastructure; the state-portal framing is "how the layer would plug in".

## Production upgrades

Reserved deliberately for v1: specialised ANPR (PaddleOCR/YOLO) in place of Gemini vision
for plate reads, a durable ledger backend, and calibration of the trust score against
adjudicated outcomes rather than the current Bayesian combination.
