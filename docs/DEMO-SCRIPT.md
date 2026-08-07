# FairFine — demo script

What to say, what to click, in order. Target **6 minutes**; the core is 3.

**Bold** = say it roughly like this. Everything else is stage direction.

---

## Before you walk in

- [ ] `gcloud run services update fairfine-api --region asia-south1 --min-instances 1` (an hour before — kills cold starts)
- [ ] `curl.exe -X POST "https://YOUR-URL/api/demo/seed?force=true"` — clean ledger, populated dashboard
- [ ] Open `/api/health` — confirm the mode is what you intend
- [ ] Tabs open in this order: `/console` · `/review` · `/ledger` · `/dashboard`
- [ ] Demo clips on the desktop, not buried in a folder
- [ ] Phone hotspot ready in case venue wifi dies
- [ ] Laptop on mains power, notifications off

---

## 0 · The opening (20 seconds)

Do not start with the architecture. Start with the person.

> **"In Bengaluru, 87% of traffic violations are now caught by AI cameras — over
> 20 lakh challans in four months. The police say 99.9% are accurate after
> manual review. At that volume, 0.1% is about six thousand wrong fines a
> year.**
>
> **Six thousand people who did nothing, who lose a day's wages going to
> Infantry Road to contest it. FairFine is the layer that checks the fine
> before it's charged."**

---

## 1 · The console — the system works (45 seconds)

Open `/console`. Point at the mode pill in the nav *before* you upload.

> **"That pill says what's actually running. It never claims live inference
> when it's simulating — that would undercut the whole premise."**

Upload **`clean_helmet_...`**. While the trace streams:

> **"Ingest samples frames. Detection and plate reading run in parallel.
> Memory sweeps for duplicates and pulls the matching Motor Vehicles Act
> section. Then the auditor — that's the product."**

Verdict lands: **ISSUE**.

> **"Clean violation, plate read confidently, all five checks pass. It issues.
> The system isn't obstructive — it agrees when the evidence is good."**

---

## 2 · The money frame (60 seconds) — the most important part

Upload **`parallax_redlight_...`**. Verdict: **REJECT**.

Point at the naive-vs-FairFine split panel.

> **"An oblique camera makes a stopped car look past the stop line. The
> existing system reads one number — a confidence score — and charges a
> thousand rupees.**
>
> **Ours is told to argue against issuing wherever there's doubt. It caught the
> parallax. That's a wrongful fine that didn't happen, and a citizen who never
> had to find out it nearly did."**

Pause here. Let it land. This is the slide they'll remember.

---

## 3 · Escalation and the human (75 seconds) — the newest and strongest part

Upload **`occluded_plate_...`**. Verdict: **ESCALATE**.

> **"The violation is obvious. But one plate character reads at 58%, against
> the 85% floor we require. Charging the wrong vehicle is still a wrongful
> fine — so it refuses to guess."**

Switch to `/review`.

> **"This is what Bengaluru doesn't have. They do have a human reviewer — but
> that reviewer is shown the AI's answer first and asked to confirm it. That's
> anchoring, not auditing, and nothing is written down."**

Click the case. Scroll the evidence.

> **"The officer gets exactly what the auditor saw — why it escalated, which
> checks failed, the reasoning, the frames."**

Type an officer ID and a reason. Click **Reject — no fine**.

> **"They cannot close it without saying why. That reason is redacted, stored,
> and appended to the ledger — and the machine's verdict stays there beside
> it. Nobody can quietly overrule the system without leaving a record."**

---

## 4 · The citizen (45 seconds)

Open an issued challan → `/challan/[id]`.

> **"Today a citizen gets an SMS and a photo. No reasoning. Here's the same
> decision explained in plain language —"**

Switch to **ಕನ್ನಡ**.

> **"— in their language. English, Hindi, Kannada, Tamil."**

Click dispute, type a reason, submit.

> **"And a dispute doesn't go into an inbox. It re-runs the audit against the
> stored evidence. Watch the verdict change."**

---

## 5 · The ledger (40 seconds)

Open `/ledger`. Click **Verify chain**.

> **"Every decision is hash-chained. Editing any record breaks every hash after
> it — and that's not a claim, our test suite deliberately tampers with a
> record and proves the chain catches it."**

Point at the evidence digest.

> **"The chain also commits to the evidence frames and their order. So nobody
> can swap the photo under a verdict that still verifies. That's what Rule
> 167A and a Section 65B certificate actually require — and courts have
> already quashed e-challans for not having it."**

If you see the reversal from step 4 and the `HUMAN_REVIEW` from step 3:

> **"Both decisions are here. Nothing was overwritten — the reversal is
> permanent and public."**

---

## 6 · The dashboard (30 seconds)

Open `/dashboard`.

> **"Nobody today can tell you Bengaluru's false-positive rate by junction, by
> camera, by vehicle type, by hour. It isn't measured. This is the first
> artefact that makes it measurable — and you cannot fix what you cannot
> measure."**

---

## 7 · The close (25 seconds)

> **"FairFine doesn't replace the cameras or the police. It's the missing step
> between detecting a violation and charging someone money.**
>
> **And it isn't only about fairness. Sixty-four percent of India's challans go
> unpaid — ₹5,714 crore outstanding. Every wrongful fine is an argument for not
> paying. Rejecting bad challans isn't a cost. It's what makes the good ones
> collectable."**

---

## The four lines to have ready

**"How is this different from what BTP already does?"**
> "They detect. We review the decision to charge. Detection is solved. Issuance
> isn't."

**"Can it handle an hour of footage / many offenders?"**
> "No, and it shouldn't — ITMS already does that well. We run after it, on the
> one event it flagged."

**"Isn't this just extra cost?"**
> "It costs two rupees to check a fine. It costs a citizen a day's wages to
> contest one. The cheaper one should happen first."

**"Their human already reviews everything."**
> "Confirming an AI's answer isn't reviewing it. Ours has to argue the other
> side, and has to write down why."

---

## If something breaks

| Problem | Do this |
|---|---|
| Audit fails / red error box | Click **Try again** — it retries and falls back to a smaller model. Say: *"that's live infrastructure — the fallback is handling it."* |
| First request very slow | Cold start. Keep talking; it's ~30s once. |
| Verdict isn't the one you promised | **Don't fight it.** Say: *"live inference on synthetic footage — the verdict rules are identical, watch the trace."* Then narrate the checks. |
| Backend unreachable | Switch to the local backend: `.env.local` → `http://127.0.0.1:8000`, `npm run dev`. |
| Everything is on fire | `FORCE_SIMULATION=1` on the service. Deterministic, honest, labelled. |

**Never claim a verdict before it appears on screen.** Narrate what the trace is
doing, not what it's about to conclude.

---

## Timing

| Section | Time |
|---|---|
| Opening | 0:20 |
| Console — ISSUE | 0:45 |
| **Parallax — REJECT** | 1:00 |
| **Escalation + /review** | 1:15 |
| Citizen + dispute | 0:45 |
| Ledger | 0:40 |
| Dashboard | 0:30 |
| Close | 0:25 |
| **Total** | **~5:40** |

**If cut to 3 minutes:** opening → parallax REJECT → `/review` → close. Those
four carry the argument on their own.
