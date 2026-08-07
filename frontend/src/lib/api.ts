import type {
  Architecture,
  AuditResult,
  AuditTrace,
  BiasDashboard,
  ChallanSummary,
  CitizenView,
  DisputeOutcome,
  Health,
  Language,
  LedgerRecord,
  LedgerVerification,
  PendingReview,
  ReviewOutcome,
} from "./types";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(
      `Cannot reach the FairFine API at ${API_BASE}. Is the backend running?`,
      0,
    );
  }
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    let message = `Request failed (${response.status})`;
    try {
      const parsed = JSON.parse(detail);
      if (parsed.detail) message = String(parsed.detail);
    } catch {
      if (detail) message = detail.slice(0, 300);
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/api/health"),
  architecture: () => get<Architecture>("/api/architecture"),

  challans: (limit = 50) =>
    get<{ items: ChallanSummary[]; count: number }>(`/api/challans?limit=${limit}`),
  challan: (id: string) => get<AuditResult & { disputes: unknown[] }>(`/api/challan/${id}`),
  citizen: (id: string, lang: Language) =>
    get<CitizenView>(`/api/challan/${encodeURIComponent(id)}/citizen?lang=${lang}`),

  dispute: (id: string, reason: string, language: Language = "en") =>
    get<DisputeOutcome>(`/api/challan/${encodeURIComponent(id)}/dispute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, language }),
    }),

  ledger: (limit = 50, offset = 0) =>
    get<{ items: LedgerRecord[]; total: number; limit: number; offset: number }>(
      `/api/ledger?limit=${limit}&offset=${offset}`,
    ),
  verifyLedger: () => get<LedgerVerification>("/api/ledger/verify"),

  dashboard: () => get<BiasDashboard>("/api/dashboard/bias"),
  reviewQueue: () => get<{ items: PendingReview[]; count: number }>("/api/review-queue"),
  decideReview: (reviewId: string, decision: "ISSUE" | "REJECT", officer: string, note: string) =>
    get<ReviewOutcome>(`/api/review/${encodeURIComponent(reviewId)}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, officer, note }),
    }),

  scenarios: () =>
    get<{ scenarios: Array<{ id: string; label: string; violation: string; expected_verdict: string }>; mode: string }>(
      "/api/demo/scenarios",
    ),
  reset: () => get<{ status: string }>("/api/demo/reset", { method: "POST" }),
};

/* -------------------------------------------------------------------------- */
/*  Audit streaming                                                            */
/* -------------------------------------------------------------------------- */

export interface AuditStreamHandlers {
  onMeta?: (meta: { challan_id: string; mode: string }) => void;
  onTrace?: (trace: AuditTrace[]) => void;
  onResult?: (result: AuditResult) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
}

/**
 * POST a clip to `/api/audit` and stream the agent trace back.
 *
 * `EventSource` cannot issue a POST with a file body, so this reads the SSE
 * stream off `fetch` directly and parses the `event:`/`data:` framing by hand.
 * Returns an abort function.
 */
export function streamAudit(
  file: File,
  handlers: AuditStreamHandlers,
  options: { operatorNote?: string; scenario?: string } = {},
): () => void {
  const controller = new AbortController();
  const form = new FormData();
  form.append("file", file);
  if (options.operatorNote) form.append("operator_note", options.operatorNote);
  if (options.scenario) form.append("scenario", options.scenario);

  (async () => {
    try {
      const response = await fetch(`${API_BASE}/api/audit?stream=true`, {
        method: "POST",
        body: form,
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        const text = await response.text().catch(() => "");
        let message = `Audit failed (${response.status})`;
        try {
          const parsed = JSON.parse(text);
          if (parsed.detail) message = String(parsed.detail);
        } catch {
          /* keep the status-code message */
        }
        handlers.onError?.(message);
        handlers.onDone?.();
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          let eventName = "message";
          const dataLines: string[] = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;

          let payload: unknown;
          try {
            payload = JSON.parse(dataLines.join("\n"));
          } catch {
            continue;
          }

          switch (eventName) {
            case "meta":
              handlers.onMeta?.(payload as { challan_id: string; mode: string });
              break;
            case "trace":
              handlers.onTrace?.(payload as AuditTrace[]);
              break;
            case "result":
              handlers.onResult?.(payload as AuditResult);
              break;
            case "error":
              handlers.onError?.((payload as { message: string }).message);
              break;
            case "done":
              handlers.onDone?.();
              break;
          }
        }
      }
      handlers.onDone?.();
    } catch (error) {
      if ((error as Error).name === "AbortError") return;
      handlers.onError?.(
        `Cannot reach the FairFine API at ${API_BASE}. Is the backend running?`,
      );
      handlers.onDone?.();
    }
  })();

  return () => controller.abort();
}
