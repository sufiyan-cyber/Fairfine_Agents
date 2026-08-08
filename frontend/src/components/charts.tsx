"use client";

import * as React from "react";

import { Eyebrow } from "@/components/ui/primitives";
import { formatPercent } from "@/lib/format";
import type { BiasSlice } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Charts are hand-built SVG so the whole dashboard reads as one system and
 * every mark is keyboard- and screen-reader reachable. Verdict colours match
 * the rest of the product exactly: green stopped, amber held, red charged.
 */

const SERIES = {
  issued: { label: "Blocked", color: "var(--color-danger)" },
  escalated: { label: "Escalated", color: "var(--color-warn)" },
  rejected: { label: "Rejected", color: "var(--color-good)" },
} as const;

/* -------------------------------------------------------------------------- */
/*  Composition bars — how each slice's decisions split                        */
/* -------------------------------------------------------------------------- */
export function VerdictComposition({
  slices,
  caption,
  emptyLabel = "No data yet",
}: {
  slices: BiasSlice[];
  caption: string;
  emptyLabel?: string;
}) {
  if (!slices.length) {
    return <p className="py-8 text-center text-[13px] text-ink-faint">{emptyLabel}</p>;
  }

  const max = Math.max(...slices.map((slice) => slice.total), 1);

  return (
    <div>
      <ul className="space-y-3.5">
        {slices.map((slice) => {
          const width = (slice.total / max) * 100;
          const segments = [
            { key: "rejected" as const, value: slice.rejected },
            { key: "escalated" as const, value: slice.escalated },
            { key: "issued" as const, value: slice.issued },
          ].filter((segment) => segment.value > 0);

          return (
            <li key={slice.key}>
              <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <span className="truncate text-[12.5px] text-ink" title={slice.key}>
                  {slice.key}
                </span>
                <span className="shrink-0 font-mono text-[11px] text-ink-dim tabular">
                  {formatPercent(slice.false_positive_rate)} stopped
                  <span className="ml-2 text-ink-faint">n={slice.total}</span>
                </span>
              </div>

              <div
                className="h-5 w-full overflow-hidden rounded-md bg-panel-3"
                role="img"
                aria-label={`${slice.key}: ${slice.total} alerts — ${slice.issued} blocked, ${slice.escalated} escalated, ${slice.rejected} allowed`}
              >
                <div className="flex h-full" style={{ width: `${width}%` }}>
                  {segments.map((segment) => (
                    <div
                      key={segment.key}
                      className="h-full transition-[width] duration-500"
                      style={{
                        width: `${(segment.value / slice.total) * 100}%`,
                        backgroundColor: SERIES[segment.key].color,
                      }}
                      title={`${SERIES[segment.key].label}: ${segment.value}`}
                    />
                  ))}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="mt-4 text-[11.5px] leading-snug text-ink-faint">{caption}</p>
      <ChartLegend />
    </div>
  );
}

export function ChartLegend() {
  return (
    <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {(Object.keys(SERIES) as Array<keyof typeof SERIES>).map((key) => (
        <li key={key} className="flex items-center gap-1.5">
          <span
            className="size-2.5 rounded-sm"
            style={{ backgroundColor: SERIES[key].color }}
            aria-hidden="true"
          />
          <span className="text-[11.5px] text-ink-dim">{SERIES[key].label}</span>
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/*  Trend line — cumulative prevention rate across the decision sequence       */
/* -------------------------------------------------------------------------- */
export function TrendLine({
  points,
  height = 200,
}: {
  points: Array<{ index: number; prevention_rate: number; verdict: string; challan_id: string }>;
  height?: number;
}) {
  const [hover, setHover] = React.useState<number | null>(null);

  if (points.length < 2) {
    return (
      <p className="py-10 text-center text-[13px] text-ink-faint">
        At least two decisions are needed to plot a trend.
      </p>
    );
  }

  const width = 640;
  const padding = { top: 14, right: 14, bottom: 26, left: 38 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const x = (index: number) => padding.left + (index / (points.length - 1)) * plotWidth;
  const y = (rate: number) => padding.top + (1 - rate) * plotHeight;

  const linePath = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${x(index)} ${y(point.prevention_rate)}`)
    .join(" ");

  const areaPath = `${linePath} L ${x(points.length - 1)} ${padding.top + plotHeight} L ${x(0)} ${padding.top + plotHeight} Z`;

  const latest = points[points.length - 1];
  const active = hover !== null ? points[hover] : null;

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={`Cumulative share of AI flags stopped before a fine, across ${points.length} decisions. Currently ${formatPercent(latest.prevention_rate)}.`}
        onMouseLeave={() => setHover(null)}
      >
        {/* Gridlines — low contrast so they never compete with the data */}
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--color-edge)"
              strokeWidth="1"
            />
            <text
              x={padding.left - 8}
              y={y(tick) + 3.5}
              textAnchor="end"
              className="fill-[var(--color-ink-faint)] font-mono text-[9px]"
            >
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}

        <defs>
          <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-signal)" stopOpacity="0.30" />
            <stop offset="100%" stopColor="var(--color-signal)" stopOpacity="0" />
          </linearGradient>
        </defs>

        <path d={areaPath} fill="url(#trend-fill)" />
        <path
          d={linePath}
          fill="none"
          stroke="var(--color-signal)"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Per-decision markers, coloured by verdict */}
        {points.map((point, index) => (
          <circle
            key={point.challan_id + index}
            cx={x(index)}
            cy={y(point.prevention_rate)}
            r={hover === index ? 5 : 3}
            fill={
              point.verdict === "ISSUE"
                ? "var(--color-danger)"
                : point.verdict === "ESCALATE"
                  ? "var(--color-warn)"
                  : "var(--color-good)"
            }
            stroke="var(--color-void)"
            strokeWidth="1.5"
            className="cursor-pointer transition-[r] duration-150"
            onMouseEnter={() => setHover(index)}
            tabIndex={0}
            role="button"
            aria-label={`Decision ${index + 1}: ${point.verdict}, cumulative prevention ${formatPercent(point.prevention_rate)}`}
            onFocus={() => setHover(index)}
            onBlur={() => setHover(null)}
          />
        ))}

        <text
          x={padding.left}
          y={height - 6}
          className="fill-[var(--color-ink-faint)] font-mono text-[9px]"
        >
          decision 1
        </text>
        <text
          x={width - padding.right}
          y={height - 6}
          textAnchor="end"
          className="fill-[var(--color-ink-faint)] font-mono text-[9px]"
        >
          decision {points.length}
        </text>
      </svg>

      <div className="mt-2 min-h-[20px]">
        {active ? (
          <p className="font-mono text-[11.5px] text-ink-dim tabular">
            {active.challan_id} · {active.verdict} · cumulative{" "}
            {formatPercent(active.prevention_rate)}
          </p>
        ) : (
          <p className="text-[11.5px] text-ink-faint">
            Hover or tab through a point for its decision.
          </p>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Hour histogram                                                             */
/* -------------------------------------------------------------------------- */
export function HourHistogram({ slices }: { slices: BiasSlice[] }) {
  if (!slices.length) {
    return <p className="py-8 text-center text-[13px] text-ink-faint">No data yet</p>;
  }

  const max = Math.max(...slices.map((slice) => slice.total), 1);

  return (
    <div>
      <div className="flex h-40 items-end gap-1.5" role="img" aria-label="Events by hour of day">
        {slices.map((slice) => {
          const stopped = slice.rejected + slice.escalated;
          return (
            <div key={slice.key} className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
              <div
                className="relative flex w-full flex-col justify-end rounded-t"
                style={{ height: `${(slice.total / max) * 100}%` }}
                title={`${slice.key} — ${slice.total} events, ${stopped} stopped`}
              >
                <div
                  className="w-full rounded-t-sm bg-danger"
                  style={{ height: `${(slice.issued / slice.total) * 100}%` }}
                />
                <div
                  className="w-full bg-warn"
                  style={{ height: `${(slice.escalated / slice.total) * 100}%` }}
                />
                <div
                  className="w-full rounded-b-sm bg-good"
                  style={{ height: `${(slice.rejected / slice.total) * 100}%` }}
                />
              </div>
              <span className="w-full truncate text-center font-mono text-[9px] text-ink-faint">
                {slice.key.replace(":00", "")}
              </span>
            </div>
          );
        })}
      </div>
      <ChartLegend />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Stat tile                                                                  */
/* -------------------------------------------------------------------------- */
export function StatTile({
  value,
  label,
  hint,
  tone = "text-ink",
}: {
  value: string;
  label: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-xl border border-edge bg-panel/70 p-4">
      <p className={cn("font-mono text-2xl font-semibold tabular", tone)}>{value}</p>
      <p className="mt-1.5 text-[12.5px] font-medium text-ink">{label}</p>
      {hint ? <p className="mt-1 text-[11.5px] leading-snug text-ink-faint">{hint}</p> : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Accessible data table — charts alone are not screen-reader friendly        */
/* -------------------------------------------------------------------------- */
export function SliceTable({ slices, keyLabel }: { slices: BiasSlice[]; keyLabel: string }) {
  if (!slices.length) return null;

  return (
    <details className="mt-4">
      <summary className="cursor-pointer text-[12px] text-ink-faint transition-colors hover:text-ink-dim">
        View as a table
      </summary>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-[12px]">
          <caption className="sr-only">
            Verdict breakdown by {keyLabel}, with the share of AI flags stopped before a fine
          </caption>
          <thead>
            <tr className="border-b border-edge">
              <th scope="col" className="py-2 pr-3 font-medium text-ink-dim">
                {keyLabel}
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium text-ink-dim">
                Total
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium text-ink-dim">
                Issued
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium text-ink-dim">
                Escalated
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium text-ink-dim">
                Rejected
              </th>
              <th scope="col" className="py-2 text-right font-medium text-ink-dim">
                Stopped
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-edge">
            {slices.map((slice) => (
              <tr key={slice.key}>
                <th scope="row" className="py-2 pr-3 font-normal text-ink">
                  {slice.key}
                </th>
                <td className="py-2 pr-3 text-right font-mono text-ink-dim tabular">{slice.total}</td>
                <td className="py-2 pr-3 text-right font-mono text-danger tabular">{slice.issued}</td>
                <td className="py-2 pr-3 text-right font-mono text-warn tabular">{slice.escalated}</td>
                <td className="py-2 pr-3 text-right font-mono text-good tabular">{slice.rejected}</td>
                <td className="py-2 text-right font-mono text-ink tabular">
                  {formatPercent(slice.false_positive_rate)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
