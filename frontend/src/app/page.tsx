import {
  ArrowRight,
  Eye,
  FileSearch,
  Fingerprint,
  Gavel,
  Languages,
  Link2,
  ScanLine,
  Scale,
  UserCheck,
} from "lucide-react";
import Link from "next/link";

import { LiveStats } from "@/components/live-stats";
import { SiteFooter, SiteNav } from "@/components/site-nav";
import { Badge, Card, Eyebrow, buttonVariants } from "@/components/ui/primitives";

const TRUST_BADGES = [
  "Gemini 2.5 Pro + Flash",
  "Google ADK",
  "Qdrant MCP",
  "Enkrypt AI guardrails",
  "SHA-256 hash chain",
];

const PIPELINE = [
  {
    icon: ScanLine,
    name: "Ingest",
    detail: "Samples frames across the event window from any existing CCTV or ANPR feed.",
  },
  {
    icon: Eye,
    name: "Detect + read plate",
    detail:
      "Two Gemini Flash agents run in parallel — one classifies the violation, one reads the plate with per-character confidence.",
  },
  {
    icon: FileSearch,
    name: "Recall",
    detail:
      "Qdrant sweeps for a near-identical event in the last 60 seconds and retrieves the governing Motor Vehicles Act section.",
  },
  {
    icon: Scale,
    name: "Adversarial audit",
    detail:
      "Gemini Pro argues against issuing. Parallax, occlusion, weak plate reads, duplicates and rule mismatch each have to survive scrutiny.",
    starred: true,
  },
  {
    icon: Gavel,
    name: "Decide",
    detail:
      "Issue only above 90% calibrated trust. Escalate genuine doubt to a person. Reject the rest.",
  },
  {
    icon: Link2,
    name: "Ledger",
    detail:
      "Every decision — issued, rejected or escalated — is appended to a hash chain that cannot be rewritten.",
  },
];

export default function LandingPage() {
  return (
    <>
      <SiteNav />

      <main id="main" className="relative z-10 flex-1">
        {/* ---------------------------------------------------------------- */}
        {/* Hero                                                              */}
        {/* ---------------------------------------------------------------- */}
        <section className="mx-auto max-w-7xl px-4 pb-16 pt-14 sm:px-6 sm:pt-20 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <Badge variant="signal" className="mb-6">
              <Fingerprint className="size-3" aria-hidden="true" />
              The accountability layer for automated enforcement
            </Badge>

            <h1 className="text-balance text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl lg:text-6xl">
              A camera flags you.
              <br />
              <span className="text-ink-dim">Something should argue back.</span>
            </h1>

            <p className="mx-auto mt-6 max-w-2xl text-pretty text-[15px] leading-relaxed text-ink-dim sm:text-base">
              Automated traffic enforcement issues fines from a single confidence score.
              FairFine puts an adversarial reviewer in front of that decision — one whose
              job is to prevent wrongful fines, not confirm them. It plugs into the CCTV
              and ANPR feeds a city already has.
            </p>

            <p className="mx-auto mt-5 max-w-xl text-pretty font-mono text-[13px] leading-relaxed text-signal">
              Adversarial audit + cryptographic evidence + public dispute — before a
              single rupee is charged.
            </p>

            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/console"
                className={buttonVariants({ variant: "primary", size: "lg", className: "w-full sm:w-auto" })}
              >
                Run an audit
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
              <Link
                href="/ledger"
                className={buttonVariants({ variant: "outline", size: "lg", className: "w-full sm:w-auto" })}
              >
                Inspect the ledger
              </Link>
            </div>

            <ul className="mt-10 flex flex-wrap items-center justify-center gap-2">
              {TRUST_BADGES.map((badge) => (
                <li key={badge}>
                  <span className="rounded-md border border-edge bg-panel/60 px-2.5 py-1 font-mono text-[11px] text-ink-faint">
                    {badge}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="mx-auto mt-14 max-w-4xl">
            <LiveStats />
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* The asymmetry                                                     */}
        {/* ---------------------------------------------------------------- */}
        <section className="border-y border-edge bg-panel/40">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-2xl text-center">
              <Eyebrow>The asymmetry nobody prices in</Eyebrow>
              <h2 className="mt-3 text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
                A missed violation costs the state a little revenue. A wrongful fine costs
                a person money, a day of work, and their trust.
              </h2>
              <p className="mt-4 text-pretty text-[14.5px] leading-relaxed text-ink-dim">
                Those two errors are not equivalent, so a system tuned to a single
                threshold gets the trade-off wrong by construction. FairFine encodes the
                asymmetry directly: the auditor is instructed to argue against issuance
                wherever doubt exists, and a fine needs 90% calibrated trust to survive.
              </p>
            </div>

            <div className="mx-auto mt-11 grid max-w-4xl gap-4 md:grid-cols-2">
              <Card className="border-danger/25 bg-danger/[0.05] p-6">
                <Eyebrow className="text-danger/80">Naive system</Eyebrow>
                <p className="mt-3 text-sm leading-relaxed text-ink-dim">
                  Reads one number — the detector&rsquo;s confidence. If it clears the
                  threshold, the challan is generated and posted. Nothing checks whether
                  the plate was actually legible, whether the camera angle manufactured
                  the violation, or whether this event was already charged.
                </p>
                <p className="mt-4 font-mono text-[12px] text-danger">
                  confidence ≥ 0.85 → issue fine
                </p>
              </Card>

              <Card className="border-good/25 bg-good/[0.05] p-6">
                <Eyebrow className="text-good/80">FairFine</Eyebrow>
                <p className="mt-3 text-sm leading-relaxed text-ink-dim">
                  Five independent checks, any one of which can stop the fine. The plate
                  floor is enforced separately from the violation itself, because a clear
                  violation charged to the wrong plate is still a wrongful fine. Doubt
                  goes to a human, not to a default.
                </p>
                <p className="mt-4 font-mono text-[12px] text-good">
                  5 checks pass ∧ trust ≥ 0.90 → issue fine
                </p>
              </Card>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Pipeline                                                          */}
        {/* ---------------------------------------------------------------- */}
        <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl text-center">
            <Eyebrow>How it works</Eyebrow>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
              Six agents, one decision, permanently recorded
            </h2>
          </div>

          <ol className="mx-auto mt-11 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {PIPELINE.map((stage, index) => (
              <li key={stage.name}>
                <Card
                  className={
                    stage.starred
                      ? "h-full border-signal/35 bg-signal/[0.06] p-5"
                      : "h-full p-5"
                  }
                >
                  <div className="flex items-center gap-2.5">
                    <span
                      className={
                        stage.starred
                          ? "flex size-8 items-center justify-center rounded-lg border border-signal/40 bg-signal/15 text-signal"
                          : "flex size-8 items-center justify-center rounded-lg border border-edge-strong bg-panel-2 text-ink-dim"
                      }
                    >
                      <stage.icon className="size-4" aria-hidden="true" />
                    </span>
                    <span className="font-mono text-[11px] text-ink-faint tabular">
                      0{index + 1}
                    </span>
                    <h3 className="text-sm font-semibold">{stage.name}</h3>
                  </div>
                  <p className="mt-3 text-[13px] leading-relaxed text-ink-dim">
                    {stage.detail}
                  </p>
                </Card>
              </li>
            ))}
          </ol>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Citizen                                                           */}
        {/* ---------------------------------------------------------------- */}
        <section className="border-t border-edge bg-panel/40">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <div className="mx-auto grid max-w-5xl items-center gap-10 lg:grid-cols-2">
              <div>
                <Eyebrow>For the person who receives the notice</Eyebrow>
                <h2 className="mt-3 text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
                  The reasoning that decided your fine, in your language
                </h2>
                <p className="mt-4 text-pretty text-[14.5px] leading-relaxed text-ink-dim">
                  Most people never learn why a machine charged them. FairFine hands the
                  auditor&rsquo;s actual reasoning to the citizen — the same text, not a
                  sanitised summary — alongside the frames, the trust score, every check
                  that ran, and a dispute that genuinely re-runs the audit.
                </p>

                <ul className="mt-6 space-y-3">
                  {[
                    {
                      icon: Languages,
                      text: "English, हिन्दी, ಕನ್ನಡ and தமிழ், written natively rather than translated.",
                    },
                    {
                      icon: UserCheck,
                      text: "Disputes re-run the adversarial auditor against the stored evidence — reversals are expected outcomes.",
                    },
                    {
                      icon: Link2,
                      text: "Both the original verdict and the re-audit stay in the chain, so a reversal is permanently visible.",
                    },
                  ].map((item) => (
                    <li key={item.text} className="flex gap-3">
                      <item.icon
                        className="mt-0.5 size-4 shrink-0 text-signal"
                        aria-hidden="true"
                      />
                      <span className="text-[13.5px] leading-relaxed text-ink-dim">
                        {item.text}
                      </span>
                    </li>
                  ))}
                </ul>

                <Link
                  href="/ledger"
                  className={buttonVariants({ variant: "secondary", className: "mt-7" })}
                >
                  Find a real notice
                  <ArrowRight className="size-4" aria-hidden="true" />
                </Link>
              </div>

              <Card className="overflow-hidden p-0">
                <div className="border-b border-edge bg-panel-2 px-5 py-3">
                  <Eyebrow>Citizen portal · sample</Eyebrow>
                </div>
                <div className="space-y-4 p-5">
                  <div className="rounded-lg border border-good/30 bg-good/[0.07] p-4">
                    <p className="text-sm font-semibold text-good">
                      No fine — this flag was dismissed
                    </p>
                    <p className="mt-2 text-[13px] leading-relaxed text-ink-dim">
                      &ldquo;The camera flagged this vehicle for crossing on red, but the
                      camera views the stop line at a steep angle rather than straight on.
                      From that viewpoint a vehicle stopped just behind the line can look
                      like it has crossed it. I cannot confirm the vehicle was actually
                      past the line while the signal was red, so no fine has been
                      issued.&rdquo;
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="danger">visually confirmed · failed</Badge>
                    <Badge variant="good">plate reliable · passed</Badge>
                    <Badge variant="good">not a duplicate · passed</Badge>
                  </div>
                  <p className="font-mono text-[11px] text-ink-faint">
                    ledger 7f3a91c4e0…8b21 · verifiable by anyone
                  </p>
                </div>
              </Card>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* CTA                                                               */}
        {/* ---------------------------------------------------------------- */}
        <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <Card className="mx-auto max-w-3xl border-signal/25 bg-signal/[0.05] px-6 py-12 text-center">
            <h2 className="text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
              Watch it reject a fine it was supposed to issue
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-pretty text-[14.5px] leading-relaxed text-ink-dim">
              Upload a clip, or run one of the built-in scenarios — a clean violation, an
              occluded plate, and the parallax false positive that a threshold-only system
              charges every time.
            </p>
            <Link
              href="/console"
              className={buttonVariants({ variant: "primary", size: "lg", className: "mt-8" })}
            >
              Open the audit console
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </Card>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
