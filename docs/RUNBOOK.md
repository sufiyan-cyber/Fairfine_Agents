# FairFine Runbook

How to run it, what happens inside it, and how to ship it.

---

## 1. Running locally

You need **three terminals** the first time, two after that. Paths below are Windows
(Git Bash). On macOS/Linux swap `.venv/Scripts/` → `.venv/bin/`.

### One-time setup

```bash
cd A:/GOOGLE_VOTES/backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
```

```bash
cd A:/GOOGLE_VOTES/frontend && npm install
```

### Terminal 1 — backend

```bash
cd A:/GOOGLE_VOTES/backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Check it: <http://127.0.0.1:8000/api/health> · API docs: <http://127.0.0.1:8000/docs>

### Terminal 2 — frontend

```bash
cd A:/GOOGLE_VOTES/frontend && npm run dev
```

Open <http://localhost:3000>

### Terminal 3 — one-time demo data

```bash
cd A:/GOOGLE_VOTES/backend && .venv/Scripts/python scripts/make_demo_clips.py && .venv/Scripts/python scripts/seed_demo.py
```

This writes 4 synthetic clips to `backend/data/demo_clips/` and runs 18 real audits so the
ledger and dashboard have content. Without it the app works but every screen is empty.

### Verify everything

```bash
cd A:/GOOGLE_VOTES/backend && PYTHONPATH=scripts .venv/Scripts/python scripts/smoke_test.py
```

41 checks. Expect `=== ALL PASSED ===`.

### Reset between demos

```bash
curl -X POST http://127.0.0.1:8000/api/demo/reset
```

Wipes the ledger, challans, review queue and disputes. Re-run `seed_demo.py` to repopulate.

> **Why you must reset before re-running the same clip:** duplicate detection keys on the
> event timestamp parsed from the filename. Feed the same file twice without resetting and
> the second run correctly returns `REJECT — duplicate`. That is a feature, and it is also
> the #1 cause of "why is everything rejected?" during a demo.

---

## 2. Simulation vs live

The app runs fully with **no API keys**. Mode is shown in the nav on every screen.

| | No keys (`simulation`) | With `GEMINI_API_KEY` (`live`) |
|---|---|---|
| Perception | Deterministic rule engine | Gemini 2.5 Flash vision |
| Audit | Same verdict logic, coded | Gemini 2.5 Pro reasoning |
| Everything else | Identical | Identical |

To go live, create `backend/.env`:

```
GEMINI_API_KEY=your_key_from_aistudio.google.com/apikey
```

Restart the backend. `/api/health` will report `"mode": "live"`.

`QDRANT_URL`/`QDRANT_API_KEY` and `ENKRYPT_API_KEY` are likewise optional — without them a
local vector index and a local PII redactor serve the same interfaces.

---

## 3. Process flow

### What the user provides

**On `/console`** — a video clip or still image from any CCTV/ANPR feed.

- Formats: `mp4 · mov · avi · mkv · webm · jpg · png · webp`, max **200 MB**
- Clips longer than `EVENT_WINDOW_SECONDS` are sampled across their full duration, so a
  long upload contributes frames from all of it rather than only its opening seconds
- Optional: a *perception scenario* override (forces a known detector/plate result so you
  can demonstrate a specific decision boundary — the audit itself still runs for real)
- Optional: operator note, location override

Filenames carry metadata if you follow the convention — this is how the demo clips work:

```
parallax_redlight_CAM-KA03-021_indiranagar_2026-07-24T16-11-05.mp4
└─ scenario ────┘ └─ camera ─┘ └ junction ┘ └─── ISO timestamp ───┘
```

Anything unparseable falls back to file mtime and a default junction. Nothing breaks.

### What happens inside

```
POST /api/audit  (multipart, SSE response)
   │
   ├─ 1. IngestAgent          FunctionTool
   │     samples ≤5 frames across a 3s window (ffmpeg → OpenCV fallback)
   │     → list[Frame]{path, ts, camera_id, location}
   │
   ├─ 2. PerceptionStage      ParallelAgent — both run concurrently
   │     ├─ DetectorAgent     Gemini Flash
   │     │    → Detection{violation_type, region_description, raw_confidence, frame_ref}
   │     └─ PlateAgent        Gemini Flash
   │          → PlateRead{plate, per_char_confidence[], min_confidence, occluded}
   │
   ├─ 3. MemoryAgent          Qdrant + RAG
   │     duplicate sweep: same plate + same location, inside 60s
   │     statute retrieval over the Motor Vehicles Act corpus
   │     → DuplicateCheck, RuleCitation
   │
   ├─ 4. AuditorAgent ★       Gemini Pro — the adversarial reviewer
   │     runs 5 vetoing checks, returns a calibrated trust score
   │     → Verdict{verdict, trust_score, reasoning, checks{5 booleans}}
   │
   ├─ 5. VerdictRouter        branches on the verdict
   │     ├─ ISSUE     → EvidenceAgent  → EvidencePacket + challan draft
   │     ├─ ESCALATE  → HumanQueueAgent → pending_review row w/ uncertainty notes
   │     └─ REJECT    → dropped
   │
   └─ 6. LedgerAgent          runs on EVERY verdict, including REJECT
         appends {id, prev_hash, payload, hash, ts}
         hash = SHA-256(prev_hash + canonical_json(payload) + ts)
```

**The five checks** — any one failing stops the fine:

| Check | Fails when |
|---|---|
| Visual confirmation | Parallax, cropping, or the plate belongs to an adjacent vehicle |
| Plate reliability | `min_confidence < 0.85` → **never ISSUE**, always ESCALATE |
| Environment | Occlusion, low light, rain, motion blur, headlight glare |
| Duplicate | Near-identical event, same plate + location, inside 60s |
| Rule applicability | The cited MV Act section doesn't match what's shown |

**Verdict thresholds:** `ISSUE` at trust ≥ 0.90 *and* all checks pass · `ESCALATE` at
0.60–0.90 or any unreliable plate · `REJECT` otherwise. Ties break toward ESCALATE.

### What the user gets back

**Streamed live** (Server-Sent Events) while it runs:

| Event | Payload |
|---|---|
| `meta` | `{challan_id, mode}` |
| `trace` | Full 7-step array, re-sent on every status change |
| `result` | The complete `AuditResult` |
| `error` / `done` | Terminal |

**On screen** (`/console`):

- Agent trace — each step lights up, shows its duration, click for its raw JSON
- Verdict card — ISSUE/ESCALATE/REJECT, trust score against the 60%/90% markers
- **Auditor's reasoning**, verbatim — the same text the citizen will read
- **Naive vs FairFine split** — what a confidence-threshold-only system would have
  charged. This is the demo's pivot: *"a wrongful fine of ₹1,000 was prevented"*
- The 5 checks, pass/fail with explanations
- Per-character plate confidence
- Sampled frames + ledger record and hash

**Then, downstream:**

| Route | User gives | User gets |
|---|---|---|
| `/challan/[id]` | Language choice (en/hi/kn/ta) | Plain-language headline, explanation, what they owe, concrete options, evidence frames, every check, the rule text, the ledger hash |
| dispute form | Free-text reason | ReAuditAgent re-decides against stored evidence → new verdict (can and does reverse), appended to the chain beside the original. PII in their text is redacted before storage |
| `/ledger` | — | Every record, hash links, one-click chain re-verification |
| `/dashboard` | — | Prevention rate disaggregated by area, vehicle type, violation, hour |

---

## 4. Deploy

Backend → **Cloud Run**. Frontend → **Vercel**. You do not need Docker installed locally;
Cloud Build builds the image server-side from the Dockerfile.

### Step 1 — prerequisites

```bash
gcloud auth login
```

```bash
gcloud config set project YOUR_PROJECT_ID
```

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

### Step 2 — deploy the backend

From the repo root:

```bash
gcloud run deploy fairfine-api --source backend --region asia-south1 --allow-unauthenticated --port 8080 --memory 2Gi --max-instances 1 --set-env-vars "GEMINI_API_KEY=your_key_here"
```

Takes 3–5 minutes. It prints a service URL like
`https://fairfine-api-abc123-el.a.run.app`. **Copy it.**

> ### `--max-instances 1` is load-bearing
>
> Cloud Run's filesystem is ephemeral and per-instance. The SQLite ledger lives only as
> long as the container, and two instances would maintain two independent chains that each
> verify but disagree with each other. For a demo this is fine. For production, move the
> ledger to Cloud SQL or a GCS-backed volume — `db.py` is small and the hashing logic is
> storage-agnostic.
>
> Practical consequence: **the ledger resets whenever Cloud Run cold-starts.** Re-seed
> after deploy (step 5).

Verify:

```bash
curl https://YOUR-SERVICE-URL/api/health
```

### Step 3 — deploy the frontend

```bash
npm install -g vercel
```

```bash
cd A:/GOOGLE_VOTES/frontend && vercel --prod
```

When prompted, accept the defaults (framework auto-detects as Next.js). Then set the API
URL and redeploy so it takes effect:

```bash
cd A:/GOOGLE_VOTES/frontend && vercel env add NEXT_PUBLIC_API_URL production
```

Paste the Cloud Run URL when prompted. Then:

```bash
cd A:/GOOGLE_VOTES/frontend && vercel --prod
```

Vercel prints your live URL, e.g. `https://fairfine.vercel.app`.

### Step 4 — lock down CORS

The backend currently allows any origin. Point it at your Vercel domain:

```bash
gcloud run services update fairfine-api --region asia-south1 --update-env-vars "CORS_ORIGINS=https://fairfine.vercel.app"
```

### Step 5 — seed the deployed instance

The deployed ledger starts empty. Either run a few audits through the live console, or
seed it locally against the deployed API. Simplest is to open `/console` on the Vercel URL
and upload the demo clips from `backend/data/demo_clips/` one at a time.

### Step 6 — verify the deployment

```bash
curl https://YOUR-SERVICE-URL/api/ledger/verify
```

Expect `{"valid": true, ...}`. Then walk the five screens on the Vercel URL.

### Optional — Qdrant and Enkrypt

```bash
gcloud run services update fairfine-api --region asia-south1 --update-env-vars "QDRANT_URL=https://xyz.qdrant.io,QDRANT_API_KEY=...,ENKRYPT_API_KEY=..."
```

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every verdict is `REJECT — duplicate` | Same clip re-run without a reset | `curl -X POST .../api/demo/reset` |
| Landing counters say "unavailable" | Backend unreachable from the browser | Check `NEXT_PUBLIC_API_URL`, and CORS on the backend |
| Dashboard/ledger empty | Never seeded | Run `scripts/seed_demo.py` |
| Nav says `simulation mode` | No `GEMINI_API_KEY` | Expected. Add the key to `backend/.env` and restart |
| Nav says `api offline` | Backend not running | Start uvicorn |
| Ledger empties after a while on Cloud Run | Container cold-start, ephemeral disk | Expected at `--max-instances 1`. Re-seed, or move to durable storage |
| Cloud Build fails on `COPY` | — | `data/` is intentionally not copied; it is created empty in the image |
| Frontend build fails on `params` | Next 16 made `params` async | Must `await props.params` in dynamic routes |
