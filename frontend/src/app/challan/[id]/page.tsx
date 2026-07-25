import type { Metadata } from "next";

import { CitizenPortal } from "./citizen-portal";

export const metadata: Metadata = {
  title: "Your notice",
  description: "Why this decision was made, and how to contest it.",
};

/**
 * `params` is a Promise in Next 16 — it must be awaited before use.
 */
export default async function ChallanPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CitizenPortal challanId={decodeURIComponent(id)} />;
}
