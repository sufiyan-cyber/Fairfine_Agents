"use client";

import { BarChart3 } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import {
  HourHistogram,
  SliceTable,
  StatTile,
  TrendLine,
  VerdictComposition,
} from "@/components/charts";
import { SiteFooter, SiteNav } from "@/components/site-nav";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Eyebrow,
  Skeleton,
  buttonVariants,
} from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import type { BiasDashboard } from "@/lib/types";

export default function DashboardPage() {
  const [data, setData] = React.useState<BiasDashboard | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .dashboard()
      .then(setData)
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  React.useEffect(load, [load]);

  return (
    <>
      <SiteNav />

      <main id="main" className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-7">
          <Eyebrow>Oversight</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Bias dashboard
          </h1>
          <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-ink-dim">
            The headline metric is the share of AI-flagged alerts the auditor stopped before
            anyone&rsquo;s money was held. A high rate concentrated in one region or one
            customer segment is not a compliment to the auditor — it means the upstream
            model performs worse there, which is exactly the disparity a fraud engine
            usually hides.
          </p>
        </header>

        {error ? <ErrorState message={error} onRetry={load} /> : null}

        {loading && !data ? (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-[104px]" />
              ))}
            </div>
            <Skeleton className="h-72 w-full" />
            <div className="grid gap-5 lg:grid-cols-2">
              <Skeleton className="h-80 w-full" />
              <Skeleton className="h-80 w-full" />
            </div>
          </div>
        ) : null}

        {data && data.total_events === 0 ? (
          <Card>
            <EmptyState
              icon={<BarChart3 className="size-8" />}
              title="No decisions to analyse yet"
              action={
                <Link href="/console" className={buttonVariants({ variant: "primary", size: "sm" })}>
                  Run an audit
                </Link>
              }
            >
              Aggregate views appear once the pipeline has decided on some events.
            </EmptyState>
          </Card>
        ) : null}

        {data && data.total_events > 0 ? (
          <div className="space-y-5">
            {/* Headline tiles */}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                value={data.total_events.toLocaleString("en-IN")}
                label="Alerts audited"
                hint="Every alert the pipeline decided on"
              />
              <StatTile
                value={data.wrongful_blocks_prevented.toLocaleString("en-IN")}
                label="Blocks stopped"
                hint="Dismissed outright or held for a human"
                tone="text-good"
              />
              <StatTile
                value={formatPercent(data.prevention_rate)}
                label="Did not survive audit"
                hint="Share of AI alerts that failed at least one check"
                tone="text-warn"
              />
              <StatTile
                value={data.issued.toLocaleString("en-IN")}
                label="Blocks placed"
                hint="Cleared all five checks and the 90% trust bar"
                tone="text-danger"
              />
            </div>

            {/* Trend */}
            <Card>
              <CardHeader>
                <CardTitle>Prevention rate over the decision sequence</CardTitle>
                <CardDescription>
                  Cumulative share of alerts stopped, with each decision coloured by its
                  verdict. A rate that keeps climbing means the model is drifting.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <TrendLine points={data.over_time} />
              </CardContent>
            </Card>

            {/* Region + segment */}
            <div className="grid gap-5 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>By region</CardTitle>
                  <CardDescription>
                    Where the model is least reliable. Geographic disparity here maps
                    directly onto whose money stops working.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <VerdictComposition
                    slices={data.by_region}
                    caption="Bar length is the number of alerts; segments are the verdict split."
                  />
                  <SliceTable slices={data.by_region} keyLabel="Region" />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>By customer segment</CardTitle>
                  <CardDescription>
                    The disparity that matters most. A student or pensioner blocked wrongly
                    has no buffer — and thin transaction histories make them likelier to be
                    flagged as &ldquo;out of pattern&rdquo; in the first place.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <VerdictComposition
                    slices={data.by_segment}
                    caption="Segment comes from the account record, never from the model's reasoning."
                  />
                  <SliceTable slices={data.by_segment} keyLabel="Segment" />
                </CardContent>
              </Card>
            </div>

            {/* Pattern + hour */}
            <div className="grid gap-5 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>By fraud pattern</CardTitle>
                  <CardDescription>
                    Which patterns the model over-flags relative to what survives review.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <VerdictComposition
                    slices={data.by_fraud_type}
                    caption="Impossible-travel calls fail pattern confirmation most often — batch settlement."
                  />
                  <SliceTable slices={data.by_fraud_type} keyLabel="Pattern" />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>By hour of day</CardTitle>
                  <CardDescription>
                    Overnight alerts should show a visibly higher stop rate. If they do not,
                    the model is overconfident on activity nobody is awake to confirm.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <HourHistogram slices={data.by_hour} />
                  <SliceTable slices={data.by_hour} keyLabel="Hour" />
                </CardContent>
              </Card>
            </div>

            <p className="text-[11.5px] text-ink-faint">
              Generated {new Date(data.generated_at).toLocaleString("en-IN")}
            </p>
          </div>
        ) : null}
      </main>

      <SiteFooter />
    </>
  );
}
