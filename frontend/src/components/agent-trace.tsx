"use client";

import { AlertTriangle, Check, ChevronRight, Circle, MinusCircle } from "lucide-react";
import * as React from "react";

import { Eyebrow } from "@/components/ui/primitives";
import type { AuditTrace, TraceStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_META: Record<
  TraceStatus,
  { ring: string; dot: string; text: string; srLabel: string }
> = {
  pending: {
    ring: "border-edge bg-panel-2",
    dot: "text-ink-faint",
    text: "text-ink-faint",
    srLabel: "waiting",
  },
  running: {
    ring: "border-signal/60 bg-signal/15",
    dot: "text-signal",
    text: "text-signal",
    srLabel: "running",
  },
  done: {
    ring: "border-good/45 bg-good/12",
    dot: "text-good",
    text: "text-ink",
    srLabel: "complete",
  },
  skipped: {
    ring: "border-edge bg-panel-2",
    dot: "text-ink-faint",
    text: "text-ink-faint",
    srLabel: "skipped",
  },
  error: {
    ring: "border-danger/50 bg-danger/12",
    dot: "text-danger",
    text: "text-danger",
    srLabel: "failed",
  },
};

function StatusIcon({ status }: { status: TraceStatus }) {
  const cls = "size-3.5";
  switch (status) {
    case "done":
      return <Check className={cls} />;
    case "error":
      return <AlertTriangle className={cls} />;
    case "skipped":
      return <MinusCircle className={cls} />;
    case "running":
      return <Circle className={cn(cls, "fill-current")} />;
    default:
      return <Circle className={cls} />;
  }
}

/**
 * The live agent trace. Each step lights up as its agent runs and exposes the
 * structured JSON that agent actually returned — this is what makes the
 * pipeline legible as agentic rather than as one opaque API call.
 */
export function AgentTrace({
  trace,
  className,
}: {
  trace: AuditTrace[];
  className?: string;
}) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  const toggle = (agent: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(agent)) next.delete(agent);
      else next.add(agent);
      return next;
    });

  const activeAgent = trace.find((step) => step.status === "running")?.agent;

  return (
    <div className={className}>
      {/* Screen readers get a single polite announcement rather than a torrent
          of individual step changes. */}
      <p className="sr-only" role="status" aria-live="polite">
        {activeAgent
          ? `${activeAgent} is running`
          : trace.every((step) => step.status === "done")
            ? "All agents complete"
            : ""}
      </p>

      <ol className="space-y-1">
        {trace.map((step, index) => {
          const meta = STATUS_META[step.status];
          const isOpen = expanded.has(step.agent);
          const hasOutput = Boolean(step.output);
          const isLast = index === trace.length - 1;

          return (
            <li key={step.agent} className="relative">
              {/* Connector rail */}
              {!isLast ? (
                <span
                  className={cn(
                    "absolute left-[15px] top-8 h-[calc(100%-14px)] w-px",
                    step.status === "done" ? "bg-good/30" : "bg-edge",
                  )}
                  aria-hidden="true"
                />
              ) : null}

              <div
                className={cn(
                  "relative rounded-lg border border-transparent transition-colors duration-200",
                  step.status === "running" && "border-signal/25 bg-signal/[0.05]",
                )}
              >
                <button
                  type="button"
                  onClick={() => hasOutput && toggle(step.agent)}
                  disabled={!hasOutput}
                  aria-expanded={hasOutput ? isOpen : undefined}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors",
                    hasOutput
                      ? "cursor-pointer hover:bg-panel-2/70"
                      : "cursor-default",
                  )}
                >
                  <span
                    className={cn(
                      "relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border",
                      meta.ring,
                      meta.dot,
                      step.status === "running" && "animate-pulse-ring",
                    )}
                  >
                    <StatusIcon status={step.status} />
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span
                        className={cn(
                          "truncate font-mono text-[12.5px] font-medium",
                          meta.text,
                        )}
                      >
                        {step.agent}
                      </span>
                      <span className="sr-only">— {meta.srLabel}</span>
                      {step.duration_ms !== null && step.status === "done" ? (
                        <span className="shrink-0 font-mono text-[10.5px] text-ink-faint tabular">
                          {step.duration_ms}ms
                        </span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 block truncate text-[12px] text-ink-dim">
                      {step.detail || step.label}
                    </span>
                  </span>

                  {hasOutput ? (
                    <ChevronRight
                      className={cn(
                        "size-4 shrink-0 text-ink-faint transition-transform duration-200",
                        isOpen && "rotate-90",
                      )}
                      aria-hidden="true"
                    />
                  ) : null}
                </button>

                {/* Running indicator bar */}
                {step.status === "running" ? (
                  <div className="mx-2 mb-2 h-0.5 overflow-hidden rounded-full bg-panel-3">
                    <div className="sweep h-full w-full" />
                  </div>
                ) : null}

                {isOpen && step.output ? (
                  <div className="animate-fade-up px-2 pb-2">
                    <pre className="max-h-72 overflow-auto rounded-lg border border-edge bg-void/70 p-3 font-mono text-[11px] leading-relaxed text-ink-dim">
                      {JSON.stringify(step.output, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function TraceLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      <Eyebrow>Agent pipeline</Eyebrow>
      <span className="text-[11px] text-ink-faint">click a completed step for its raw JSON</span>
    </div>
  );
}
