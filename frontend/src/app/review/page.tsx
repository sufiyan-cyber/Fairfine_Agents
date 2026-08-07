"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Link2,
  Loader2,
  UserCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SiteFooter, SiteNav } from "@/components/site-nav";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Eyebrow,
  Skeleton,
} from "@/components/ui/primitives";
import { ChecksList, TrustMeter } from "@/components/verdict";
import { api } from "@/lib/api";
import { formatTime, truncateHash } from "@/lib/format";
import type { AuditResult, PendingReview, ReviewOutcome } from "@/lib/types";
import { cn } from "@/lib/utils";

const MIN_NOTE = 10;

export default function ReviewPage() {
  const [queue, setQueue] = React.useState<PendingReview[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [selected, setSelected] = React.useState<PendingReview | null>(null);
  const [evidence, setEvidence] = React.useState<AuditResult | null>(null);
  const [loadingEvidence, setLoadingEvidence] = React.useState(false);

  const [officer, setOfficer] = React.useState("");
  const [note, setNote] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [outcome, setOutcome] = React.useState<ReviewOutcome | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);

  React.useEffect(() => {
    // `loading` already starts true, so nothing is set synchronously here —
    // doing so would cascade a second render before the fetch even begins.
    let cancelled = false;
    api
      .reviewQueue()
      .then((data) => {
        if (cancelled) return;
        setQueue(data.items);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function open(review: PendingReview) {
    setSelected(review);
    setEvidence(null);
    setOutcome(null);
    setFormError(null);
    setNote("");
    setLoadingEvidence(true);
    api
      .challan(review.challan_id)
      .then((data) => setEvidence(data))
      .catch(() => setEvidence(null))
      .finally(() => setLoadingEvidence(false));
  }

  async function decide(decision: "ISSUE" | "REJECT") {
    if (!selected) return;
    if (!officer.trim()) {
      setFormError("Enter your officer ID — a decision has to be attributable.");
      return;
    }
    if (note.trim().length < MIN_NOTE) {
      setFormError(`Give a reason of at least ${MIN_NOTE} characters. It is ledgered with your decision.`);
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const result = await api.decideReview(selected.id, decision, officer.trim(), note.trim());
      setOutcome(result);
      setQueue((items) => items.filter((item) => item.id !== selected.id));
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <SiteNav />
      <main className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 py-10 sm:px-6 lg:px-8">
        <Eyebrow>Human review</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
          Escalated cases
        </h1>
        <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-ink-dim">
          The auditor sends a case here when it cannot rule it out and cannot stand behind
          it either. No fine is issued until an officer decides, and the decision is
          appended to the ledger with its reason — the machine&apos;s verdict is never
          overwritten, only answered.
        </p>

        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
          {/* ---- queue -------------------------------------------------- */}
          <Card className="h-fit">
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="text-[15px]">
                Queue
                {!loading ? (
                  <span className="ml-2 font-mono text-[12px] font-normal text-ink-faint">
                    {queue.length} open
                  </span>
                ) : null}
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {loading ? (
                <div className="flex flex-col gap-2">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : error ? (
                <ErrorState title="Could not load the queue" message={error} />
              ) : queue.length === 0 ? (
                <EmptyState
                  icon={<CheckCircle2 className="size-8" />}
                  title="Nothing waiting"
                >
                  Every escalated case has been decided.
                </EmptyState>
              ) : (
                <ul className="flex flex-col gap-2">
                  {queue.map((review) => {
                    const active = selected?.id === review.id;
                    return (
                      <li key={review.id}>
                        <button
                          type="button"
                          onClick={() => open(review)}
                          className={cn(
                            "w-full rounded-lg border p-3 text-left transition-colors",
                            active
                              ? "border-signal/45 bg-signal/[0.07]"
                              : "border-edge bg-panel-2/40 hover:border-edge-strong hover:bg-panel-2/70",
                          )}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-mono text-[12.5px] text-ink">
                              {review.challan_id}
                            </span>
                            <Badge variant="warn">
                              {Math.round(review.trust_score * 100)}% trust
                            </Badge>
                          </div>
                          <p className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-ink-faint">
                            {review.uncertainty || "No uncertainty note recorded."}
                          </p>
                          <p className="mt-1.5 font-mono text-[10.5px] text-ink-faint">
                            {formatTime(review.created_at)}
                          </p>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>

          {/* ---- detail ------------------------------------------------- */}
          <div>
            {!selected ? (
              <Card>
                <CardContent className="py-16">
                  <EmptyState
                    icon={<UserCheck className="size-8" />}
                    title="Select a case"
                  >
                    You will see everything the auditor saw, and what it could not resolve.
                  </EmptyState>
                </CardContent>
              </Card>
            ) : (
              <div className="flex flex-col gap-6">
                <Card>
                  <CardHeader>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <CardTitle className="font-mono text-[15px]">
                        {selected.challan_id}
                      </CardTitle>
                      <Link
                        href={`/challan/${selected.challan_id}`}
                        className="text-[12.5px] text-signal hover:underline"
                      >
                        Citizen view →
                      </Link>
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-5 pt-0">
                    <div className="rounded-lg border border-warn/30 bg-warn/[0.06] p-3.5">
                      <p className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wider text-warn">
                        <AlertTriangle className="size-3.5" aria-hidden="true" />
                        Why this was escalated
                      </p>
                      <p className="mt-2 whitespace-pre-line text-[13.5px] leading-relaxed text-ink-dim">
                        {selected.uncertainty || "No uncertainty note recorded."}
                      </p>
                    </div>

                    <TrustMeter score={selected.trust_score} />

                    {loadingEvidence ? (
                      <Skeleton className="h-40 w-full" />
                    ) : evidence ? (
                      <>
                        <ChecksList checks={evidence.verdict.checks} />

                        <div>
                          <p className="text-[12px] font-medium uppercase tracking-wider text-ink-faint">
                            Auditor reasoning
                          </p>
                          <p className="mt-2 text-[13.5px] leading-relaxed text-ink-dim">
                            {evidence.verdict.reasoning}
                          </p>
                        </div>

                        {evidence.frame_uris?.length ? (
                          <div>
                            <p className="text-[12px] font-medium uppercase tracking-wider text-ink-faint">
                              Evidence frames
                            </p>
                            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                              {evidence.frame_uris.map((uri, i) => (
                                /* eslint-disable-next-line @next/next/no-img-element */
                                <img
                                  key={i}
                                  src={uri}
                                  alt={`Evidence frame ${i + 1}`}
                                  className="w-full rounded-md border border-edge"
                                />
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </>
                    ) : (
                      <p className="text-[13px] text-ink-faint">
                        Evidence packet unavailable for this challan.
                      </p>
                    )}
                  </CardContent>
                </Card>

                {/* ---- decision ------------------------------------------ */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-[15px]">Your decision</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    {outcome ? (
                      <div className="rounded-lg border border-good/30 bg-good/[0.06] p-4">
                        <p className="flex items-center gap-2 text-[13.5px] font-medium text-good">
                          <CheckCircle2 className="size-4" aria-hidden="true" />
                          Recorded as {outcome.decision} by {outcome.officer}
                        </p>
                        <p className="mt-2 text-[13px] leading-relaxed text-ink-dim">
                          {outcome.note}
                        </p>
                        <p className="mt-3 flex items-center gap-1.5 font-mono text-[11px] text-ink-faint">
                          <Link2 className="size-3" aria-hidden="true" />
                          {truncateHash(outcome.ledger_hash)}
                        </p>
                        <Link
                          href="/ledger"
                          className="mt-3 inline-block text-[12.5px] text-signal hover:underline"
                        >
                          See it in the ledger →
                        </Link>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-4">
                        <div>
                          <label
                            htmlFor="officer"
                            className="text-[12px] font-medium uppercase tracking-wider text-ink-faint"
                          >
                            Officer ID
                          </label>
                          <input
                            id="officer"
                            value={officer}
                            onChange={(e) => setOfficer(e.target.value)}
                            placeholder="e.g. HC 4417"
                            disabled={submitting}
                            className="mt-1.5 w-full rounded-lg border border-edge-strong bg-panel-2/50 px-3 py-2.5 text-[13.5px] text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-signal/50"
                          />
                        </div>

                        <div>
                          <label
                            htmlFor="note"
                            className="text-[12px] font-medium uppercase tracking-wider text-ink-faint"
                          >
                            Reason (required, ledgered)
                          </label>
                          <textarea
                            id="note"
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            rows={3}
                            placeholder="What did you see that the auditor could not resolve?"
                            disabled={submitting}
                            className="mt-1.5 w-full resize-y rounded-lg border border-edge-strong bg-panel-2/50 px-3 py-2.5 text-[13.5px] leading-relaxed text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-signal/50"
                          />
                          <p className="mt-1 text-[11.5px] text-ink-faint">
                            Stored with your decision and shown to the citizen. Personal
                            details are redacted before it is saved.
                          </p>
                        </div>

                        {formError ? (
                          <p className="text-[12.5px] text-danger">{formError}</p>
                        ) : null}

                        <div className="flex flex-wrap gap-3">
                          <Button
                            variant="danger"
                            onClick={() => decide("ISSUE")}
                            disabled={submitting}
                          >
                            {submitting ? (
                              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                            ) : (
                              <AlertTriangle className="size-4" aria-hidden="true" />
                            )}
                            Issue the fine
                          </Button>
                          <Button
                            variant="secondary"
                            onClick={() => decide("REJECT")}
                            disabled={submitting}
                          >
                            {submitting ? (
                              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                            ) : (
                              <XCircle className="size-4" aria-hidden="true" />
                            )}
                            Reject — no fine
                          </Button>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
