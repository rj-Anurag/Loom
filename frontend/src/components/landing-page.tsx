"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Image from "next/image";
import { type ReactNode, useState } from "react";

import { LoomMark } from "@/components/loom-mark";

const mono = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
const docsUrl = "https://loom-docs.vercel.app";
const githubUrl = "https://github.com/rj-Anurag/Loom";

const installs = {
  unix: {
    label: "macOS / Linux",
    command:
      "git clone https://github.com/rj-Anurag/Loom.git\ncd Loom && ./install.sh",
  },
  windows: {
    label: "Windows",
    command:
      "git clone https://github.com/rj-Anurag/Loom.git\ncd Loom; .\\install.ps1",
  },
} as const;

type InstallTarget = keyof typeof installs;

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <Typography
      sx={{
        color: "primary.light",
        fontFamily: mono,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: ".14em",
        textTransform: "uppercase",
      }}
    >
      {children}
    </Typography>
  );
}

function TerminalLine({
  children,
  color = "text.secondary",
  prompt = false,
}: {
  children: ReactNode;
  color?: string;
  prompt?: boolean;
}) {
  return (
    <Typography
      component="div"
      sx={{
        color,
        fontFamily: mono,
        fontSize: { xs: 10.5, sm: 12 },
        lineHeight: 1.85,
        overflowWrap: "anywhere",
      }}
    >
      {prompt && (
        <Box component="span" sx={{ color: "primary.light", mr: 1 }}>
          $
        </Box>
      )}
      {children}
    </Typography>
  );
}

function ProductWindow() {
  return (
    <Card
      aria-label="Loom context moving from a browser conversation to a coding agent"
      sx={{
        bgcolor: "#0b0b0e",
        borderColor: "rgba(167,139,250,.24)",
        boxShadow: "0 34px 110px rgba(0,0,0,.55)",
        overflow: "hidden",
      }}
    >
      <Stack
        alignItems="center"
        direction="row"
        justifyContent="space-between"
        sx={{
          bgcolor: "rgba(255,255,255,.025)",
          borderBottom: "1px solid",
          borderColor: "divider",
          px: { xs: 2, sm: 2.5 },
          py: 1.4,
        }}
      >
        <Stack direction="row" spacing={0.75}>
          {["#ef4444", "#eab308", "#22c55e"].map((color) => (
            <Box
              key={color}
              sx={{
                bgcolor: color,
                borderRadius: "50%",
                height: 7,
                width: 7,
              }}
            />
          ))}
        </Stack>
        <Typography
          sx={{
            color: "text.secondary",
            fontFamily: mono,
            fontSize: 9,
            letterSpacing: ".12em",
            textTransform: "uppercase",
          }}
        >
          loom / context stream
        </Typography>
        <Box sx={{ width: 38 }} />
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "1fr 72px 1fr" },
          minHeight: { md: 330 },
        }}
      >
        <Box sx={{ p: { xs: 2.5, sm: 3.5 } }}>
          <Stack direction="row" justifyContent="space-between">
            <SectionLabel>Browser / ChatGPT</SectionLabel>
            <Typography
              sx={{ color: "#4ade80", fontFamily: mono, fontSize: 9 }}
            >
              ● LINKED
            </Typography>
          </Stack>
          <Stack spacing={2.2} sx={{ mt: 3.5 }}>
            <Box
              sx={{
                bgcolor: "rgba(96,165,250,.07)",
                border: "1px solid rgba(96,165,250,.14)",
                borderRadius: 2,
                ml: { sm: 4 },
                p: 2,
              }}
            >
              <Typography
                sx={{
                  color: "#93c5fd",
                  fontFamily: mono,
                  fontSize: 9,
                  mb: 1,
                }}
              >
                YOU / DECISION
              </Typography>
              <Typography sx={{ fontSize: 13, lineHeight: 1.6 }}>
                Use a project-scoped API key and keep credentials outside the
                repository.
              </Typography>
            </Box>
            <Box
              sx={{
                bgcolor: "rgba(167,139,250,.07)",
                border: "1px solid rgba(167,139,250,.14)",
                borderRadius: 2,
                mr: { sm: 4 },
                p: 2,
              }}
            >
              <Typography
                sx={{
                  color: "primary.light",
                  fontFamily: mono,
                  fontSize: 9,
                  mb: 1,
                }}
              >
                ASSISTANT / RESULT
              </Typography>
              <Typography sx={{ fontSize: 13, lineHeight: 1.6 }}>
                The dashboard, CLI, and extension now share one project
                identity.
              </Typography>
            </Box>
          </Stack>
        </Box>

        <Stack
          alignItems="center"
          justifyContent="center"
          sx={{
            borderColor: "divider",
            borderLeft: { md: "1px solid" },
            borderRight: { md: "1px solid" },
            borderTop: { xs: "1px solid", md: 0 },
            color: "primary.light",
            minHeight: { xs: 58, md: "auto" },
          }}
        >
          <Box
            sx={{
              alignItems: "center",
              bgcolor: "rgba(139,92,246,.12)",
              border: "1px solid rgba(167,139,250,.24)",
              borderRadius: "50%",
              display: "flex",
              height: 34,
              justifyContent: "center",
              transform: { xs: "rotate(90deg)", md: "none" },
              width: 34,
            }}
          >
            →
          </Box>
        </Stack>

        <Box sx={{ p: { xs: 2.5, sm: 3.5 } }}>
          <Stack direction="row" justifyContent="space-between">
            <SectionLabel>Terminal / Codex</SectionLabel>
            <Typography
              sx={{ color: "#4ade80", fontFamily: mono, fontSize: 9 }}
            >
              ● READY
            </Typography>
          </Stack>
          <Box sx={{ mt: 3.5 }}>
            <TerminalLine prompt>
              loom context &quot;authentication decision&quot;
            </TerminalLine>
            <TerminalLine color="#c4b5fd">
              Searching project memory…
            </TerminalLine>
            <Box
              sx={{
                borderLeft: "2px solid",
                borderColor: "primary.main",
                my: 1.8,
                pl: 2,
              }}
            >
              <TerminalLine color="#f5f3f7">
                Found 2 relevant context units
              </TerminalLine>
              <TerminalLine>decision · browser chat · 3m ago</TerminalLine>
              <TerminalLine>task_result · assistant · 2m ago</TerminalLine>
            </Box>
            <TerminalLine prompt>codex</TerminalLine>
            <TerminalLine color="#4ade80">
              ✓ Continuing with project context loaded.
            </TerminalLine>
          </Box>
        </Box>
      </Box>
    </Card>
  );
}

function ContextFlow() {
  const sources = ["ChatGPT", "Claude", "DeepSeek", "Perplexity"];
  const clients = ["Claude Code", "Codex", "Any MCP client"];

  return (
    <Card
      sx={{
        bgcolor: "#0b0b0e",
        display: "grid",
        gap: { xs: 2, md: 1 },
        gridTemplateColumns: {
          xs: "1fr",
          md: "1fr 70px 1.15fr 70px 1fr",
        },
        p: { xs: 2, sm: 3.5 },
      }}
    >
      <Stack spacing={1}>
        <SectionLabel>Capture</SectionLabel>
        {sources.map((source) => (
          <FlowItem key={source}>{source}</FlowItem>
        ))}
      </Stack>
      <Stack alignItems="center" justifyContent="center">
        <Box
          aria-hidden="true"
          sx={{
            color: "primary.light",
            transform: { xs: "rotate(90deg)", md: "none" },
          }}
        >
          →
        </Box>
      </Stack>
      <Stack
        alignItems="center"
        justifyContent="center"
        sx={{
          background:
            "radial-gradient(circle, rgba(139,92,246,.18), rgba(139,92,246,0) 68%)",
          minHeight: 210,
          textAlign: "center",
        }}
      >
        <Box
          sx={{
            alignItems: "center",
            bgcolor: "rgba(139,92,246,.1)",
            border: "1px solid rgba(167,139,250,.35)",
            borderRadius: "50%",
            display: "flex",
            height: 88,
            justifyContent: "center",
            mb: 2,
            width: 88,
          }}
        >
          <Image alt="" height={52} src="/loom-logo.png" width={52} />
        </Box>
        <Typography sx={{ fontSize: 17, fontWeight: 700 }}>
          Project context graph
        </Typography>
        <Typography
          sx={{
            color: "text.secondary",
            fontFamily: mono,
            fontSize: 9,
            mt: 0.75,
          }}
        >
          PERSISTENT · SCOPED · AUDITABLE
        </Typography>
      </Stack>
      <Stack alignItems="center" justifyContent="center">
        <Box
          aria-hidden="true"
          sx={{
            color: "primary.light",
            transform: { xs: "rotate(90deg)", md: "none" },
          }}
        >
          →
        </Box>
      </Stack>
      <Stack justifyContent="center" spacing={1}>
        <SectionLabel>Continue</SectionLabel>
        {clients.map((client) => (
          <FlowItem key={client}>{client}</FlowItem>
        ))}
      </Stack>
    </Card>
  );
}

function FlowItem({ children }: { children: ReactNode }) {
  return (
    <Box
      sx={{
        bgcolor: "rgba(255,255,255,.025)",
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 1.5,
        color: "text.secondary",
        fontFamily: mono,
        fontSize: 11,
        px: 1.5,
        py: 1.2,
      }}
    >
      {children}
    </Box>
  );
}

function InstallCard() {
  const [installTarget, setInstallTarget] = useState<InstallTarget>("unix");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  const install = installs[installTarget];

  async function copyInstallCommand() {
    try {
      await navigator.clipboard.writeText(install.command);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1800);
    } catch {
      setCopyState("failed");
    }
  }

  function chooseInstallTarget(target: InstallTarget) {
    setInstallTarget(target);
    setCopyState("idle");
  }

  return (
    <Card
      sx={{
        bgcolor: "rgba(14,14,18,.88)",
        borderColor: "rgba(255,255,255,.13)",
        maxWidth: 810,
        mt: { xs: 7, md: 8 },
        mx: "auto",
        overflow: "hidden",
        textAlign: "left",
      }}
    >
      <Stack
        direction="row"
        sx={{
          bgcolor: "rgba(255,255,255,.025)",
          borderBottom: "1px solid",
          borderColor: "divider",
        }}
      >
        {(Object.keys(installs) as InstallTarget[]).map((target) => (
          <Button
            aria-pressed={installTarget === target}
            key={target}
            onClick={() => chooseInstallTarget(target)}
            sx={{
              borderBottom: "2px solid",
              borderColor:
                installTarget === target ? "primary.light" : "transparent",
              borderRadius: 0,
              color:
                installTarget === target ? "text.primary" : "text.secondary",
              fontFamily: mono,
              fontSize: 10,
              letterSpacing: ".08em",
              px: { xs: 1.5, sm: 3 },
            }}
          >
            {installs[target].label}
          </Button>
        ))}
      </Stack>
      <Stack
        alignItems={{ xs: "stretch", sm: "center" }}
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        spacing={2}
        sx={{ p: { xs: 2, sm: 2.5 } }}
      >
        <Typography
          component="pre"
          sx={{
            color: "#d8d4de",
            fontFamily: mono,
            fontSize: { xs: 10.5, sm: 12 },
            lineHeight: 1.8,
            m: 0,
            overflowX: "auto",
            whiteSpace: "pre-wrap",
          }}
        >
          <Box component="span" sx={{ color: "primary.light" }}>
            \${" "}
          </Box>
          {install.command}
        </Typography>
        <Button
          aria-live="polite"
          onClick={copyInstallCommand}
          size="small"
          variant="outlined"
        >
          {copyState === "copied"
            ? "Copied ✓"
            : copyState === "failed"
              ? "Copy failed"
              : "Copy"}
        </Button>
      </Stack>
    </Card>
  );
}

export function LandingPage() {
  return (
    <Box
      component="main"
      sx={{
        backgroundColor: "background.default",
        backgroundImage:
          "linear-gradient(rgba(255,255,255,.018) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px)",
        backgroundSize: "36px 36px",
        minHeight: "100vh",
        overflow: "hidden",
      }}
    >
      <Box
        aria-hidden="true"
        sx={{
          background: "rgba(139,92,246,.18)",
          borderRadius: "50%",
          filter: "blur(110px)",
          height: 430,
          left: "50%",
          pointerEvents: "none",
          position: "absolute",
          top: 150,
          transform: "translateX(-50%)",
          width: 660,
        }}
      />

      <Box
        sx={{
          maxWidth: 1180,
          mx: "auto",
          px: { xs: 2, sm: 3, md: 4 },
          position: "relative",
        }}
      >
        <Stack
          alignItems="center"
          component="nav"
          direction="row"
          justifyContent="space-between"
          sx={{
            backdropFilter: "blur(18px)",
            bgcolor: "rgba(12,12,15,.76)",
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 2,
            mt: { xs: 1.5, sm: 2.5 },
            px: { xs: 1.5, sm: 2.25 },
            py: 1.3,
            position: "relative",
            zIndex: 10,
          }}
        >
          <a
            aria-label="Loom home"
            href="#top"
            style={{ color: "inherit", textDecoration: "none" }}
          >
            <LoomMark />
          </a>
          <Stack
            alignItems="center"
            direction="row"
            spacing={{ sm: 2.5, md: 3.5 }}
            sx={{ display: { xs: "none", sm: "flex" } }}
          >
            {[
              ["Product", "#product"],
              ["How it works", "#how-it-works"],
              ["Security", "#security"],
            ].map(([label, href]) => (
              <Typography
                component="a"
                href={href}
                key={label}
                sx={{
                  color: "text.secondary",
                  fontFamily: mono,
                  fontSize: 10,
                  letterSpacing: ".08em",
                  textDecoration: "none",
                  textTransform: "uppercase",
                  transition: "color 160ms ease",
                  "&:hover": { color: "text.primary" },
                }}
              >
                {label}
              </Typography>
            ))}
            <Typography
              component="a"
              href={docsUrl}
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 10,
                letterSpacing: ".08em",
                textDecoration: "none",
                textTransform: "uppercase",
                "&:hover": { color: "text.primary" },
              }}
            >
              Docs ↗
            </Typography>
          </Stack>
          <Button
            component="a"
            href="/dashboard"
            size="small"
            variant="outlined"
          >
            Dashboard{" "}
            <Box component="span" sx={{ ml: 1 }}>
              →
            </Box>
          </Button>
        </Stack>

        <Box
          id="top"
          sx={{
            pb: { xs: 8, md: 12 },
            pt: { xs: 9, sm: 12, md: 15 },
            textAlign: "center",
          }}
        >
          <Chip
            label="OPEN SOURCE · PHASE 1"
            size="small"
            sx={{
              bgcolor: "rgba(139,92,246,.1)",
              border: "1px solid rgba(167,139,250,.24)",
              color: "primary.light",
              fontFamily: mono,
              fontSize: 9,
              letterSpacing: ".12em",
            }}
          />
          <Typography
            component="h1"
            variant="h1"
            sx={{
              fontSize: { xs: 49, sm: 72, md: 96 },
              lineHeight: { xs: 0.98, md: 0.93 },
              maxWidth: 1000,
              mx: "auto",
              mt: 3,
              wordSpacing: ".08em",
            }}
          >
            One project. Every agent.{" "}
            <Box
              component="span"
              sx={{
                background:
                  "linear-gradient(115deg, #c4b5fd, #8b5cf6 65%, #6d4bed)",
                backgroundClip: "text",
                color: "transparent",
              }}
            >
              Shared context.
            </Box>
          </Typography>
          <Typography
            sx={{
              color: "text.secondary",
              fontSize: { xs: 16, sm: 18 },
              lineHeight: 1.75,
              maxWidth: 700,
              mx: "auto",
              mt: 4,
            }}
          >
            Loom carries useful project history from browser conversations into
            Claude Code, Codex, and every MCP-capable agent—so the next session
            starts with the decisions that already matter.
          </Typography>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            justifyContent="center"
            spacing={1.5}
            sx={{ mt: 4 }}
          >
            <Button
              component="a"
              href="/v1/dashboard"
              size="large"
              variant="contained"
            >
              Open dashboard{" "}
              <Box component="span" sx={{ ml: 1 }}>
                →
              </Box>
            </Button>
            <Button
              component="a"
              href={docsUrl + "/#quickstart"}
              size="large"
              variant="outlined"
            >
              Read the quickstart
            </Button>
          </Stack>

          <InstallCard />
        </Box>

        <Box id="product" sx={{ pb: { xs: 10, md: 16 }, scrollMarginTop: 24 }}>
          <ProductWindow />
        </Box>

        <Box sx={{ pb: { xs: 10, md: 16 } }}>
          <Box
            sx={{
              display: "grid",
              gap: { xs: 3, md: 8 },
              gridTemplateColumns: { xs: "1fr", md: ".8fr 1.2fr" },
              mb: 6,
            }}
          >
            <Box>
              <SectionLabel>Why Loom?</SectionLabel>
              <Typography
                component="h2"
                variant="h2"
                sx={{
                  fontSize: { xs: 37, sm: 49 },
                  lineHeight: 1.05,
                  mt: 2,
                  wordSpacing: ".06em",
                }}
              >
                Your agents forget. Your project shouldn&apos;t.
              </Typography>
            </Box>
            <Typography
              sx={{
                color: "text.secondary",
                fontSize: { xs: 16, md: 18 },
                lineHeight: 1.8,
                pt: { md: 3 },
              }}
            >
              The best decisions are often trapped in a browser tab while the
              work happens in a terminal. Loom makes project context a shared
              layer—durable across tools, scoped to the right codebase, and
              ready when an agent needs it.
            </Typography>
          </Box>
          <ContextFlow />
        </Box>

        <Box
          id="how-it-works"
          sx={{ pb: { xs: 10, md: 16 }, scrollMarginTop: 24 }}
        >
          <Stack
            alignItems={{ md: "flex-end" }}
            direction={{ xs: "column", md: "row" }}
            justifyContent="space-between"
            spacing={3}
            sx={{ mb: 5 }}
          >
            <Box>
              <SectionLabel>How it works</SectionLabel>
              <Typography
                component="h2"
                variant="h2"
                sx={{
                  fontSize: { xs: 37, sm: 52 },
                  mt: 2,
                  wordSpacing: ".06em",
                }}
              >
                Start once. Continue anywhere.
              </Typography>
            </Box>
            <Typography
              sx={{
                color: "text.secondary",
                lineHeight: 1.7,
                maxWidth: 460,
              }}
            >
              One project identity connects the browser extension, CLI,
              dashboard, and coding agents.
            </Typography>
          </Stack>
          <Box
            sx={{
              display: "grid",
              gap: 2,
              gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" },
            }}
          >
            {[
              {
                number: "01",
                title: "Connect the project",
                body: "Sign in, run loom init inside the repository, and Loom creates a project-scoped identity for this machine.",
                detail: "loom login → loom init",
              },
              {
                number: "02",
                title: "Link the conversation",
                body: "The Chrome extension captures useful history from supported AI chats and keeps new messages synced.",
                detail: "Browser → context graph",
              },
              {
                number: "03",
                title: "Keep building",
                body: "Claude Code, Codex, and MCP clients retrieve the decisions, summaries, and results relevant to the task.",
                detail: "Context graph → terminal",
              },
            ].map((step) => (
              <Card
                key={step.number}
                sx={{
                  bgcolor: "rgba(17,17,20,.82)",
                  minHeight: 285,
                  p: { xs: 3, md: 3.5 },
                }}
              >
                <Typography
                  sx={{
                    color: "primary.light",
                    fontFamily: mono,
                    fontSize: 11,
                  }}
                >
                  {step.number} / 03
                </Typography>
                <Typography
                  component="h3"
                  sx={{
                    fontSize: 24,
                    fontWeight: 650,
                    letterSpacing: "-.035em",
                    mt: 6,
                  }}
                >
                  {step.title}
                </Typography>
                <Typography
                  sx={{
                    color: "text.secondary",
                    fontSize: 14,
                    lineHeight: 1.7,
                    mt: 1.5,
                  }}
                >
                  {step.body}
                </Typography>
                <Typography
                  sx={{
                    borderTop: "1px solid",
                    borderColor: "divider",
                    color: "text.secondary",
                    fontFamily: mono,
                    fontSize: 9,
                    letterSpacing: ".06em",
                    mt: 3,
                    pt: 2,
                    textTransform: "uppercase",
                  }}
                >
                  {step.detail}
                </Typography>
              </Card>
            ))}
          </Box>
        </Box>

        <Box id="security" sx={{ pb: { xs: 10, md: 16 }, scrollMarginTop: 24 }}>
          <Card
            sx={{
              background:
                "radial-gradient(circle at 85% 20%, rgba(139,92,246,.17), transparent 34%), #0d0d10",
              display: "grid",
              gap: { xs: 5, md: 8 },
              gridTemplateColumns: { xs: "1fr", md: "1.05fr .95fr" },
              overflow: "hidden",
              p: { xs: 3, sm: 5, md: 7 },
            }}
          >
            <Box>
              <SectionLabel>Scoped by design</SectionLabel>
              <Typography
                component="h2"
                variant="h2"
                sx={{
                  fontSize: { xs: 36, sm: 49 },
                  lineHeight: 1.06,
                  mt: 2,
                  wordSpacing: ".06em",
                }}
              >
                Shared context without shared secrets.
              </Typography>
              <Typography
                sx={{
                  color: "text.secondary",
                  lineHeight: 1.8,
                  mt: 3,
                  maxWidth: 520,
                }}
              >
                Every browser and CLI installation gets its own revocable
                project credential and audit identity. Credentials stay in
                private user-level storage—not in your repository.
              </Typography>
              <Button
                component="a"
                href={docsUrl + "/#security"}
                sx={{ mt: 3 }}
                variant="outlined"
              >
                Read security notes{" "}
                <Box component="span" sx={{ ml: 1 }}>
                  ↗
                </Box>
              </Button>
            </Box>
            <Stack justifyContent="center" spacing={1.25}>
              {[
                ["01", "Project-scoped access"],
                ["02", "Revocable client credentials"],
                ["03", "Distinct trust tiers"],
                ["04", "Append-only event history"],
              ].map(([number, label]) => (
                <Stack
                  alignItems="center"
                  direction="row"
                  key={number}
                  spacing={2}
                  sx={{
                    bgcolor: "rgba(255,255,255,.025)",
                    border: "1px solid",
                    borderColor: "divider",
                    borderRadius: 1.5,
                    p: 1.6,
                  }}
                >
                  <Typography
                    sx={{
                      color: "primary.light",
                      fontFamily: mono,
                      fontSize: 9,
                    }}
                  >
                    {number}
                  </Typography>
                  <Typography sx={{ fontSize: 14 }}>{label}</Typography>
                  <Box
                    sx={{
                      color: "#4ade80",
                      fontFamily: mono,
                      fontSize: 11,
                      ml: "auto !important",
                    }}
                  >
                    ✓
                  </Box>
                </Stack>
              ))}
            </Stack>
          </Card>
        </Box>

        <Box sx={{ pb: { xs: 8, md: 12 }, textAlign: "center" }}>
          <SectionLabel>Keep the thread</SectionLabel>
          <Typography
            component="h2"
            variant="h2"
            sx={{
              fontSize: { xs: 41, sm: 62 },
              lineHeight: 1,
              maxWidth: 820,
              mx: "auto",
              mt: 2,
              wordSpacing: ".06em",
            }}
          >
            Give every agent the context to do its best work.
          </Typography>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            justifyContent="center"
            spacing={1.5}
            sx={{ mt: 4 }}
          >
            <Button
              component="a"
              href={docsUrl + "/#installation"}
              size="large"
              variant="contained"
            >
              Install Loom{" "}
              <Box component="span" sx={{ ml: 1 }}>
                →
              </Box>
            </Button>
            <Button
              component="a"
              href={githubUrl}
              size="large"
              variant="outlined"
            >
              View on GitHub ↗
            </Button>
          </Stack>
        </Box>

        <Stack
          component="footer"
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          spacing={2}
          sx={{
            borderTop: "1px solid",
            borderColor: "divider",
            color: "text.secondary",
            fontFamily: mono,
            fontSize: 9,
            letterSpacing: ".07em",
            py: 3.5,
            textTransform: "uppercase",
          }}
        >
          <span>Loom / Shared agent context</span>
          <Stack direction="row" spacing={2.5}>
            <FooterLink href={docsUrl}>Docs</FooterLink>
            <FooterLink href={githubUrl}>GitHub</FooterLink>
            <FooterLink href="/dashboard">Dashboard</FooterLink>
          </Stack>
          <span>MIT License</span>
        </Stack>
      </Box>
    </Box>
  );
}

function FooterLink({ children, href }: { children: ReactNode; href: string }) {
  return (
    <Box
      component="a"
      href={href}
      sx={{
        color: "inherit",
        textDecoration: "none",
        "&:hover": { color: "text.primary" },
      }}
    >
      {children}
    </Box>
  );
}
