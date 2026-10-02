import Image from "next/image";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Code2,
  GitBranch,
  Network,
  ShieldCheck,
  Terminal,
} from "lucide-react";

const guides = [
  {
    href: "/docs#quickstart",
    icon: Terminal,
    eyebrow: "Start here",
    title: "Quickstart",
    description:
      "Install Loom, create a project, and connect your first agent.",
  },
  {
    href: "/docs#core-concepts",
    icon: Network,
    eyebrow: "Understand Loom",
    title: "Core concepts",
    description: "Learn how projects, context, and trust fit together.",
  },
  {
    href: "/docs#browser-extension",
    icon: GitBranch,
    eyebrow: "Connect your tools",
    title: "Integrations",
    description:
      "Bring browser conversations and coding agents into one project.",
  },
];

export function DocsHome() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/80 bg-background/90">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between gap-4 px-5 sm:px-8">
          <Link
            href="/"
            aria-label="Loom docs home"
            className="flex items-center gap-3 font-semibold tracking-[-0.03em]"
          >
            <Image
              src="/loom-logo.png"
              alt=""
              aria-hidden="true"
              width={36}
              height={36}
              priority
              className="size-9 rounded-xl shadow-[0_0_30px_rgba(139,92,246,.3)]"
            />
            <span className="text-[17px]">
              Loom{" "}
              <span className="font-normal text-muted-foreground">Docs</span>
            </span>
          </Link>
          <nav
            aria-label="Main navigation"
            className="flex items-center gap-3 sm:gap-6"
          >
            <Link
              href="/docs"
              className="text-sm text-muted-foreground transition hover:text-foreground"
            >
              Documentation
            </Link>
            <a
              href="https://github.com/rj-Anurag/Loom"
              target="_blank"
              rel="noreferrer"
              className="hidden text-sm text-muted-foreground transition hover:text-foreground sm:inline"
            >
              GitHub
            </a>
          </nav>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden border-b border-border/70">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_72%_38%,rgba(139,92,246,.16),transparent_45%)]" />
          <div className="relative mx-auto grid max-w-[1200px] gap-14 px-5 py-20 sm:px-8 sm:py-28 lg:grid-cols-[minmax(0,1fr)_minmax(380px,.85fr)] lg:items-center lg:gap-20 lg:py-36">
            <div>
              <p className="mb-7 inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/8 px-3 py-1.5 text-xs font-medium tracking-wide text-primary">
                <BookOpen className="size-3.5" /> Developer documentation
              </p>
              <h1 className="max-w-2xl text-5xl font-semibold leading-[1.08] tracking-[-0.06em] sm:text-6xl lg:text-[68px]">
                Shared context for every coding agent.
              </h1>
              <p className="mt-7 max-w-xl text-base leading-8 text-muted-foreground sm:text-lg">
                Learn how to carry project history from browser conversations
                into Codex, Claude Code, OpenCode, and other MCP clients.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-3">
                <Link
                  href="/docs#quickstart"
                  className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Get started <ArrowRight className="size-4" />
                </Link>
                <Link
                  href="/docs"
                  className="inline-flex h-11 items-center gap-2 rounded-lg border border-border bg-card px-5 text-sm font-medium transition hover:border-primary/50 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Browse documentation
                </Link>
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-[#111014] p-5 shadow-[0_32px_100px_rgba(0,0,0,.35)] sm:p-7">
              <div className="flex items-center justify-between border-b border-border pb-5">
                <span className="text-sm font-medium">
                  One project, one context graph
                </span>
                <Network className="size-4 text-primary" />
              </div>
              <div className="grid gap-3 py-6">
                <div className="flex items-center gap-3 rounded-xl border border-border bg-background/70 p-4">
                  <BookOpen className="size-5 text-muted-foreground" />
                  <span className="text-sm">Browser conversations</span>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    capture
                  </span>
                </div>
                <div className="ml-6 h-6 border-l border-dashed border-primary/50" />
                <div className="flex items-center gap-3 rounded-xl border border-primary/40 bg-primary/10 p-4 shadow-[0_0_32px_rgba(139,92,246,.08)]">
                  <Network className="size-5 text-primary" />
                  <span className="text-sm font-medium">
                    Loom project context
                  </span>
                  <span className="ml-auto size-2 rounded-full bg-primary shadow-[0_0_12px_rgba(155,122,247,.8)]" />
                </div>
                <div className="ml-6 h-6 border-l border-dashed border-primary/50" />
                <div className="flex items-center gap-3 rounded-xl border border-border bg-background/70 p-4">
                  <Code2 className="size-5 text-muted-foreground" />
                  <span className="text-sm">Coding agents</span>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    retrieve
                  </span>
                </div>
              </div>
              <p className="border-t border-border pt-5 text-xs leading-6 text-muted-foreground">
                Project-scoped credentials keep access separate and auditable.
              </p>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-24">
          <div className="mb-9">
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
              Find your path
            </p>
            <h2 className="text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">
              Start building with Loom
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">
              Go from setup to a shared project history, then explore the tools
              and references you need.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {guides.map(({ href, icon: Icon, eyebrow, title, description }) => (
              <Link
                key={href}
                href={href}
                className="group flex min-h-56 flex-col rounded-xl border border-border bg-[linear-gradient(145deg,#141217_0%,#0e0d11_100%)] p-6 transition hover:border-primary/50 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Icon className="size-5 text-primary" />
                <p className="mt-8 text-xs font-semibold uppercase tracking-[0.12em] text-primary">
                  {eyebrow}
                </p>
                <h3 className="mt-2 text-lg font-semibold tracking-tight">
                  {title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {description}
                </p>
                <ArrowRight className="mt-auto size-4 self-end text-muted-foreground transition group-hover:translate-x-1 group-hover:text-primary" />
              </Link>
            ))}
          </div>
        </section>

        <section className="border-t border-border/70 bg-card/40">
          <div className="mx-auto flex max-w-[1200px] flex-col gap-6 px-5 py-12 sm:flex-row sm:items-center sm:justify-between sm:px-8">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-1 size-5 shrink-0 text-primary" />
              <div>
                <h2 className="font-semibold">Need the details?</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Explore CLI commands, MCP tools, configuration, and security.
                </p>
              </div>
            </div>
            <Link
              href="/docs#cli-reference"
              className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
            >
              Explore the reference <ArrowRight className="size-4" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-8 text-xs text-muted-foreground sm:px-8">
        <span>Loom Docs</span>
        <Link href="/docs" className="hover:text-foreground">
          All documentation
        </Link>
      </footer>
    </div>
  );
}
