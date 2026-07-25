import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";

import "./globals.css";

/**
 * IBM Plex Sans carries institutional credibility — this product asks people
 * to trust an enforcement decision. JetBrains Mono handles every value that is
 * read character by character: plates, hashes, trust scores.
 */
const plex = IBM_Plex_Sans({
  variable: "--font-plex",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "FairFine — accountability for automated traffic enforcement",
    template: "%s · FairFine",
  },
  description:
    "An adversarial agent pipeline audits every AI-flagged traffic violation, issues fines only above a calibrated trust threshold, escalates ambiguity to a human, and writes every decision to a hash-chained ledger.",
  openGraph: {
    title: "FairFine",
    description:
      "Adversarial audit + cryptographic evidence + public dispute — before a single rupee is charged.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#08090c",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${plex.variable} ${jetbrains.variable} h-full`}>
      <body className="flex min-h-full flex-col antialiased">
        <div className="ff-field" aria-hidden="true" />
        <a
          href="#main"
          className="sr-only z-50 rounded-lg bg-signal px-4 py-2 font-medium text-void focus:not-sr-only focus:absolute focus:left-4 focus:top-4"
        >
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
