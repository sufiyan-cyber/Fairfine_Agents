"use client";

import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  MapPin,
  MessageSquareWarning,
  ShieldCheck,
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
  ErrorState,
  Eyebrow,
  Skeleton,
  buttonVariants,
} from "@/components/ui/primitives";
import { ChecksList, TrustMeter } from "@/components/verdict";
import { api } from "@/lib/api";
import {
  LANGUAGES,
  VERDICT_META,
  formatDateTime,
  formatPercent,
  formatRupees,
  truncateHash,
} from "@/lib/format";
import type { CitizenView, DisputeOutcome, Language } from "@/lib/types";
import { cn } from "@/lib/utils";

export function CitizenPortal({ challanId }: { challanId: string }) {
  const [language, setLanguage] = React.useState<Language>("en");
  const [view, setView] = React.useState<CitizenView | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(
    (lang: Language) => {
      setLoading(true);
      setError(null);
      api
        .citizen(challanId, lang)
        .then(setView)
        .catch((cause: Error) => setError(cause.message))
        .finally(() => setLoading(false));
    },
    [challanId],
  );

  React.useEffect(() => load(language), [language, load]);

  return (
    <>
      <SiteNav />

      <main id="main" className="relative z-10 mx-auto w-full max-w-3xl flex-1 px-4 py-8 sm:px-6">
        <Link
          href="/ledger"
          className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-ink-dim transition-colors hover:text-ink"
        >
          <ArrowLeft className="size-3.5" aria-hidden="true" />
          All notices
        </Link>

        {error ? (
          <ErrorState title="Could not load this notice" message={error} onRetry={() => load(language)} />
        ) : null}

        {loading && !view ? <PortalSkeleton /> : null}

        {view ? (
          <PortalBody
            view={view}
            language={language}
            onLanguageChange={setLanguage}
            loading={loading}
            onDisputed={() => load(language)}
          />
        ) : null}
      </main>

      <SiteFooter />
    </>
  );
}

/* -------------------------------------------------------------------------- */

function PortalBody({
  view,
  language,
  onLanguageChange,
  loading,
  onDisputed,
}: {
  view: CitizenView;
  language: Language;
  onLanguageChange: (lang: Language) => void;
  loading: boolean;
  onDisputed: () => void;
}) {
  const meta = VERDICT_META[view.verdict];
  const owes = view.verdict === "ISSUE" && view.fine_amount > 0;

  return (
    <div className={cn("space-y-6", loading && "opacity-60")}>
      {/* ---------------------------------------------------------------- */}
      {/* Language switcher — placed above the notice, because the notice   */}
      {/* is useless to someone who cannot read it.                         */}
      {/* ---------------------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-[12px] text-ink-faint">Read this in</span>
        <div
          role="group"
          aria-label="Choose language"
          className="flex flex-wrap gap-1.5 rounded-lg border border-edge bg-panel p-1"
        >
          {LANGUAGES.map((entry) => (
            <button
              key={entry.code}
              type="button"
              onClick={() => onLanguageChange(entry.code)}
              aria-pressed={language === entry.code}
              lang={entry.code}
              className={cn(
                "min-h-9 rounded-md px-3 text-[13px] transition-colors duration-200 cursor-pointer",
                language === entry.code
                  ? "bg-signal font-medium text-void"
                  : "text-ink-dim hover:bg-panel-2 hover:text-ink",
              )}
            >
              {entry.native}
            </button>
          ))}
        </div>
        {loading ? (
          <Loader2 className="size-3.5 animate-spin text-ink-faint" aria-label="Loading" />
        ) : null}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* The verdict, stated plainly, first.                               */}
      {/* ---------------------------------------------------------------- */}
      <Card className={cn("overflow-hidden", meta.border)}>
        <div className={cn("px-6 py-7", meta.bg)}>
          <div className="flex items-center gap-2">
            <span className={cn("size-2 rounded-full", meta.dot)} aria-hidden="true" />
            <Eyebrow className={meta.text}>{meta.short}</Eyebrow>
          </div>
          <h1
            lang={language}
            className={cn(
              "mt-3 text-balance text-2xl font-semibold leading-snug tracking-tight sm:text-3xl",
              meta.text,
            )}
          >
            {view.headline}
          </h1>
          <p lang={language} className="mt-3 text-pretty text-[15px] leading-relaxed text-ink">
            {view.what_this_means}
          </p>

          {owes ? (
            <p className="mt-5 font-mono text-4xl font-semibold text-danger tabular">
              {formatRupees(view.fine_amount)}
            </p>
          ) : (
            <p className="mt-5 inline-flex items-center gap-2 rounded-lg border border-good/30 bg-good/10 px-3 py-2 text-[13.5px] font-medium text-good">
              <CheckCircle2 className="size-4" aria-hidden="true" />
              Nothing is owed
            </p>
          )}
        </div>

        <CardContent className="space-y-5 border-t border-edge pt-5">
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <Field icon={FileText} label="Vehicle" value={view.plate} mono />
            <Field icon={FileText} label="Registered owner" value={view.owner_masked} mono />
            <Field icon={MapPin} label="Where" value={view.location} />
            <Field icon={Clock} label="When" value={formatDateTime(view.ts)} />
          </dl>

          <p className="text-[12px] leading-relaxed text-ink-faint">
            The owner&rsquo;s name is masked here and was withheld from every model in the
            pipeline. Who owns a vehicle is never a valid input to whether a violation
            occurred.
          </p>
        </CardContent>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Why                                                               */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Why this decision was made</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <p lang={language} className="text-pretty text-[14.5px] leading-relaxed text-ink">
            {view.explanation}
          </p>

          {language !== "en" ? (
            <details className="group rounded-lg border border-edge bg-panel-2/50 p-4">
              <summary className="cursor-pointer list-none text-[13px] font-medium text-ink-dim transition-colors hover:text-ink">
                Show the auditor&rsquo;s original English reasoning
              </summary>
              <p className="mt-3 text-[13.5px] leading-relaxed text-ink-dim">
                {view.auditor_reasoning}
              </p>
            </details>
          ) : null}

          <div className="rounded-lg border border-edge bg-panel-2/50 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Eyebrow>How certain the system was</Eyebrow>
              <span className={cn("font-mono text-lg font-semibold tabular", meta.text)}>
                {formatPercent(view.trust_score, 1)}
              </span>
            </div>
            <TrustMeter score={view.trust_score} className="mt-3" />
            <p className="mt-3 text-[12.5px] leading-relaxed text-ink-dim">
              A fine is only issued above 90%. Between 60% and 90% a person reviews it.
              Below that, it is dropped.
            </p>
          </div>

          <div>
            <Eyebrow className="mb-3">Every check that ran</Eyebrow>
            <ChecksList checks={view.checks} />
          </div>

          {view.rule_citation ? (
            <div className="rounded-lg border border-edge bg-panel-2/50 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="signal">{view.rule_citation}</Badge>
                <span className="text-[12.5px] text-ink-dim">{view.violation_label}</span>
              </div>
              {view.rule_text ? (
                <p className="mt-3 text-[12.5px] leading-relaxed text-ink-dim">
                  {view.rule_text}
                </p>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Evidence                                                          */}
      {/* ---------------------------------------------------------------- */}
      {view.frames.length ? (
        <Card>
          <CardHeader>
            <CardTitle>What the camera recorded</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {view.frames.map((uri, index) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={index}
                  src={uri}
                  alt={`Camera frame ${index + 1} of ${view.frames.length} for notice ${view.challan_id}`}
                  className="aspect-video w-full rounded-lg border border-edge object-cover"
                  loading="lazy"
                />
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      {/* Options                                                           */}
      {/* ---------------------------------------------------------------- */}
      {view.your_options.length ? (
        <Card>
          <CardHeader>
            <CardTitle>What you can do</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2.5">
              {view.your_options.map((option, index) => (
                <li key={index} className="flex items-start gap-2.5">
                  <span
                    className="mt-1.5 size-1.5 shrink-0 rounded-full bg-signal"
                    aria-hidden="true"
                  />
                  <span lang={language} className="text-[14px] leading-relaxed text-ink">
                    {option}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      {/* Dispute                                                           */}
      {/* ---------------------------------------------------------------- */}
      <DisputePanel view={view} language={language} onDisputed={onDisputed} />

      {/* ---------------------------------------------------------------- */}
      {/* Ledger                                                            */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-start gap-3">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-signal" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-[13.5px] font-medium text-ink">
                This decision is permanently recorded
              </p>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-dim">
                It sits in a public hash chain. If anyone edits this record after the fact —
                the verdict, the score, the reasoning — the chain stops verifying and the
                tampering becomes visible to everyone.
              </p>
              <p className="mt-2.5 break-all font-mono text-[11px] text-ink-faint">
                {truncateHash(view.ledger_hash, 24, 12)}
              </p>
            </div>
          </div>
          <Link
            href="/ledger"
            className={buttonVariants({ variant: "outline", size: "sm", className: "mt-4 w-full" })}
          >
            Verify this record yourself
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Dispute                                                                    */
/* -------------------------------------------------------------------------- */
function DisputePanel({
  view,
  language,
  onDisputed,
}: {
  view: CitizenView;
  language: Language;
  onDisputed: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [outcome, setOutcome] = React.useState<DisputeOutcome | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const fieldRef = React.useRef<HTMLTextAreaElement>(null);

  const tooShort = reason.trim().length > 0 && reason.trim().length < 10;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (reason.trim().length < 10) {
      fieldRef.current?.focus();
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.dispute(view.challan_id, reason.trim(), language);
      setOutcome(result);
      setReason("");
      onDisputed();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  if (outcome) {
    const meta = VERDICT_META[outcome.new_verdict];
    return (
      <Card className={cn("animate-fade-up", meta.border)}>
        <CardHeader>
          <CardTitle>Your dispute has been reviewed</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[12px] text-ink-faint line-through">
              {outcome.original_verdict}
            </span>
            <span className="text-ink-faint" aria-hidden="true">
              →
            </span>
            <span className={cn("font-mono text-[13px] font-semibold", meta.text)}>
              {outcome.new_verdict}
            </span>
            {outcome.changed ? (
              <Badge variant="good">verdict changed</Badge>
            ) : (
              <Badge variant="neutral">original verdict upheld</Badge>
            )}
          </div>

          <p className="text-[14px] leading-relaxed text-ink">{outcome.reasoning}</p>

          <div className="rounded-lg border border-edge bg-panel-2/50 p-4">
            <Eyebrow>Recorded in the chain</Eyebrow>
            <p className="mt-2 text-[12.5px] leading-relaxed text-ink-dim">
              The re-audit was appended alongside the original decision — the first verdict
              was not overwritten. Both remain permanently visible.
            </p>
            <p className="mt-2 break-all font-mono text-[11px] text-ink-faint">
              {truncateHash(outcome.ledger_hash, 24, 12)}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!view.disputable) {
    return (
      <Card className="border-good/25 bg-good/[0.05]">
        <CardContent className="pt-5">
          <p className="text-[13.5px] leading-relaxed text-good">
            There is nothing to contest — no fine was issued and no record is held against
            you.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Think this is wrong?</CardTitle>
      </CardHeader>
      <CardContent>
        {view.dispute_status ? (
          <p className="mb-4 rounded-lg border border-edge bg-panel-2/50 px-3 py-2 text-[12.5px] text-ink-dim">
            {view.dispute_status}
          </p>
        ) : null}

        {!open ? (
          <>
            <p className="text-[13.5px] leading-relaxed text-ink-dim">
              Filing a dispute re-runs the same adversarial review against the stored
              evidence, this time with your account of what happened in front of it. It can
              and does reverse decisions.
            </p>
            <Button variant="secondary" className="mt-4 w-full" onClick={() => setOpen(true)}>
              <MessageSquareWarning className="size-4" aria-hidden="true" />
              Contest this notice
            </Button>
          </>
        ) : (
          <form onSubmit={submit} noValidate>
            <label htmlFor="reason" className="mb-1.5 block text-[13px] font-medium text-ink">
              What happened? <span className="text-danger">*</span>
            </label>
            <textarea
              ref={fieldRef}
              id="reason"
              rows={5}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={4000}
              aria-describedby="reason-help reason-error"
              aria-invalid={tooShort || undefined}
              placeholder="Explain in your own words. For example: the signal was not working, the vehicle was sold before this date, or I had already paid this fine."
              className={cn(
                "w-full resize-y rounded-lg border bg-panel-2 px-3 py-2.5 text-[14px] leading-relaxed text-ink placeholder:text-ink-faint",
                "transition-colors focus:outline-none focus-visible:border-signal",
                tooShort ? "border-danger" : "border-edge-strong",
              )}
            />

            <p id="reason-help" className="mt-1.5 text-[11.5px] leading-snug text-ink-faint">
              Do not include your phone number, Aadhaar or any ID. Anything like that is
              automatically redacted before the text is stored or reviewed.
            </p>

            {tooShort ? (
              <p id="reason-error" role="alert" className="mt-1.5 text-[12px] text-danger">
                Please give a little more detail — at least 10 characters — so the auditor
                has something to weigh.
              </p>
            ) : null}

            {error ? (
              <p role="alert" className="mt-2 text-[12.5px] text-danger">
                {error}
              </p>
            ) : null}

            <div className="mt-4 flex gap-2">
              <Button
                type="submit"
                variant="primary"
                className="flex-1"
                disabled={submitting || reason.trim().length < 10}
              >
                {submitting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    Re-running the audit…
                  </>
                ) : (
                  "Submit dispute"
                )}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
                Cancel
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */

function Field({
  icon: Icon,
  label,
  value,
  mono,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11.5px] text-ink-faint">
        <Icon className="size-3" aria-hidden="true" />
        {label}
      </dt>
      <dd className={cn("mt-1 text-[13.5px] text-ink", mono && "font-mono")}>{value}</dd>
    </div>
  );
}

function PortalSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-10 w-64" />
      <Skeleton className="h-72 w-full" />
      <Skeleton className="h-56 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}
