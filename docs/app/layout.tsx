import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Loom Docs — Shared context for coding agents",
  description: "Install, integrate, and operate Loom across browser AI chats, Claude Code, Codex, and MCP clients.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className="antialiased" suppressHydrationWarning>{children}</body></html>;
}
