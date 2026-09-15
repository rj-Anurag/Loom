import type { Metadata } from "next";

import { LandingPage } from "@/components/landing-page";

export const metadata: Metadata = {
  title: "Loom — Shared context for every coding agent",
  description:
    "Carry useful project history from browser conversations into Claude Code, Codex, and every MCP-capable agent.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Loom — Shared context for every coding agent",
    description:
      "One project. Every agent. Shared context across browser conversations, Claude Code, Codex, and MCP.",
    siteName: "Loom",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Loom — Shared context for every coding agent",
    description:
      "One project. Every agent. Shared context across browser conversations, Claude Code, Codex, and MCP.",
  },
};

export default function HomePage() {
  return <LandingPage />;
}
