"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { LoomMark } from "@/components/loom-mark";
import { formatDate } from "@/lib/api";
import type { ContextUnit, HistoryPage, Project } from "@/lib/types";

interface AgentPresence {
  agent_id?: string;
  status?: string;
}

interface Conflict {
  id?: string;
  conflict_type?: string;
  created_at?: string;
}

const mono = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
const allowedStatuses = new Set([
  "online",
  "idle",
  "working",
  "blocked",
  "offline",
]);

async function authenticatedRequest<T>(
  path: string,
  token: string,
): Promise<T> {
  const response = await fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok)
    throw new Error(`${response.status}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

function safeSourceUrl(value?: string): string {
  try {
    const parsed = new URL(value ?? "");
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.href
      : "";
  } catch {
    return "";
  }
}

function parseMessage(unit: ContextUnit) {
  const content = unit.content ?? "";
  if (/^(User|Human):/i.test(content) || unit.trust_tier === "user") {
    return {
      label: "Human message",
      color: "#60a5fa",
      icon: "●",
      body: content.replace(/^(User|Human):\s*/i, ""),
    };
  }
  if (/^(AI|Assistant):/i.test(content)) {
    return {
      label: "AI message",
      color: "#c084fc",
      icon: "◆",
      body: content.replace(/^(AI|Assistant):\s*/i, ""),
    };
  }
  return {
    label: (unit.type || "Agent").toUpperCase(),
    color: "#94a3b8",
    icon: "✦",
    body: content,
  };
}

export function ProjectDashboard({ projectId }: { projectId: string }) {
  const [token, setToken] = useState("");
  const [authorized, setAuthorized] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [agents, setAgents] = useState<AgentPresence[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [units, setUnits] = useState<ContextUnit[]>([]);
  const [ascending, setAscending] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.slice(1));
    const fragmentToken = hash.get("token") ?? "";
    if (fragmentToken) {
      sessionStorage.setItem("loom_dashboard_token", fragmentToken);
      window.history.replaceState(null, "", window.location.pathname);
    }
    const stored =
      fragmentToken || sessionStorage.getItem("loom_dashboard_token") || "";
    const initialize = window.setTimeout(() => {
      setToken(stored);
      setAuthorized(Boolean(stored));
      if (!stored) setLoading(false);
    }, 0);
    return () => window.clearTimeout(initialize);
  }, []);

  const loadHistory = useCallback(
    async (accessToken: string) => {
      const collected: ContextUnit[] = [];
      const seen = new Set<string>();
      let cursor = "";
      do {
        const suffix = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
        const page = await authenticatedRequest<HistoryPage>(
          `/v1/projects/${projectId}/context/history?limit=200${suffix}`,
          accessToken,
        );
        collected.push(...(page.units ?? []));
        cursor = page.has_more ? (page.next_cursor ?? "") : "";
        if (cursor && seen.has(cursor))
          throw new Error("History pagination did not advance.");
        if (cursor) seen.add(cursor);
      } while (cursor);
      return collected;
    },
    [projectId],
  );

  const refresh = useCallback(
    async (accessToken: string, initial = false) => {
      try {
        const [projectData, agentData, conflictData, historyData] =
          await Promise.all([
            authenticatedRequest<Project>(
              `/v1/projects/${projectId}`,
              accessToken,
            ),
            authenticatedRequest<AgentPresence[]>(
              `/v1/projects/${projectId}/agents/presence`,
              accessToken,
            ),
            authenticatedRequest<Conflict[]>(
              `/v1/projects/${projectId}/conflicts`,
              accessToken,
            ),
            loadHistory(accessToken),
          ]);
        setProject(projectData);
        setAgents(agentData ?? []);
        setConflicts(conflictData ?? []);
        setUnits(historyData);
        setError("");
      } catch (reason) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not load this project.",
        );
      } finally {
        if (initial) setLoading(false);
      }
    },
    [loadHistory, projectId],
  );

  useEffect(() => {
    if (!token) return;
    const initialRefresh = window.setTimeout(
      () => void refresh(token, true),
      0,
    );
    const timer = window.setInterval(() => void refresh(token), 10_000);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(timer);
    };
  }, [refresh, token]);

  const orderedUnits = useMemo(
    () => (ascending ? units.toReversed() : units),
    [ascending, units],
  );

  if (!authorized) {
    return (
      <Stack
        alignItems="center"
        justifyContent="center"
        sx={{ minHeight: "100vh", p: 2 }}
      >
        <Card sx={{ maxWidth: 560, p: 4, textAlign: "center" }}>
          <LoomMark />
          <EmptyState title="Project access required">
            Open this dashboard from a linked conversation in the Loom
            extension.
          </EmptyState>
        </Card>
      </Stack>
    );
  }

  return (
    <Box component="main" sx={{ minHeight: "100vh", p: { xs: 2, sm: 4 } }}>
      <Box sx={{ maxWidth: 1120, mx: "auto" }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          alignItems={{ sm: "flex-end" }}
          justifyContent="space-between"
          spacing={2}
          sx={{
            borderBottom: "1px solid",
            borderColor: "divider",
            mb: 3,
            pb: 2.5,
          }}
        >
          <Stack direction="row" alignItems="center" spacing={1.5}>
            <LoomMark compact />
            <Box>
              <Typography
                sx={{
                  color: "primary.light",
                  fontFamily: mono,
                  fontSize: 9,
                  textTransform: "uppercase",
                }}
              >
                Loom / Project
              </Typography>
              <Typography
                component="h1"
                variant="h1"
                sx={{ fontSize: { xs: 30, sm: 38 }, mt: 0.5 }}
              >
                {project?.name || (loading ? "Loading…" : "Project")}
              </Typography>
              <Typography
                color="text.secondary"
                sx={{ fontFamily: mono, fontSize: 10 }}
              >
                ID: {project?.id || projectId} · Created:{" "}
                {formatDate(project?.created_at)}
              </Typography>
            </Box>
          </Stack>
          <Stack direction="row" spacing={1}>
            {[
              ["Context", project?.context_unit_count ?? units.length],
              ["Chats", project?.linked_chat_count ?? 0],
              ["Agents", project?.agent_count ?? agents.length],
            ].map(([label, value]) => (
              <Card key={String(label)} sx={{ minWidth: 88, px: 1.5, py: 1 }}>
                <Typography sx={{ fontSize: 17, fontWeight: 650 }}>
                  {value}
                </Typography>
                <Typography
                  sx={{
                    color: "text.secondary",
                    fontFamily: mono,
                    fontSize: 8,
                    textTransform: "uppercase",
                  }}
                >
                  {label}
                </Typography>
              </Card>
            ))}
          </Stack>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        {loading ? (
          <Stack alignItems="center" sx={{ py: 10 }}>
            <CircularProgress />
          </Stack>
        ) : (
          <>
            <Box
              sx={{
                display: "grid",
                gap: 2,
                gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
              }}
            >
              <Card sx={{ p: 2.5 }}>
                <Typography
                  component="h2"
                  sx={{
                    color: "primary.light",
                    fontFamily: mono,
                    fontSize: 11,
                    fontWeight: 750,
                    mb: 2,
                    textTransform: "uppercase",
                  }}
                >
                  Active agents
                </Typography>
                {agents.length === 0 ? (
                  <Typography color="text.secondary">
                    No active agents
                  </Typography>
                ) : (
                  <Stack
                    divider={
                      <Box
                        sx={{ borderTop: "1px solid", borderColor: "divider" }}
                      />
                    }
                  >
                    {agents.map((agent, index) => {
                      const status = allowedStatuses.has(agent.status ?? "")
                        ? agent.status!
                        : "idle";
                      return (
                        <Stack
                          key={`${agent.agent_id}-${index}`}
                          direction="row"
                          justifyContent="space-between"
                          alignItems="center"
                          sx={{ py: 1 }}
                        >
                          <Typography sx={{ fontFamily: mono, fontSize: 12 }}>
                            {agent.agent_id || "unknown"}
                          </Typography>
                          <Chip
                            size="small"
                            label={status}
                            color={
                              status === "blocked"
                                ? "error"
                                : status === "working" || status === "online"
                                  ? "success"
                                  : "default"
                            }
                          />
                        </Stack>
                      );
                    })}
                  </Stack>
                )}
              </Card>
              <Card sx={{ p: 2.5 }}>
                <Typography
                  component="h2"
                  sx={{
                    color: "primary.light",
                    fontFamily: mono,
                    fontSize: 11,
                    fontWeight: 750,
                    mb: 2,
                    textTransform: "uppercase",
                  }}
                >
                  Pending conflicts
                </Typography>
                {conflicts.length === 0 ? (
                  <Typography color="text.secondary">
                    No pending conflicts
                  </Typography>
                ) : (
                  <Stack
                    divider={
                      <Box
                        sx={{ borderTop: "1px solid", borderColor: "divider" }}
                      />
                    }
                  >
                    {conflicts.map((conflict, index) => (
                      <Stack
                        key={conflict.id ?? index}
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        sx={{ py: 1 }}
                      >
                        <Box>
                          <Typography color="error.light" sx={{ fontSize: 13 }}>
                            {conflict.conflict_type || "unknown"}
                          </Typography>
                          <Typography
                            color="text.secondary"
                            sx={{ fontFamily: mono, fontSize: 9 }}
                          >
                            {formatDate(conflict.created_at)}
                          </Typography>
                        </Box>
                        <Chip color="error" label="pending" size="small" />
                      </Stack>
                    ))}
                  </Stack>
                )}
              </Card>
            </Box>

            <Card sx={{ mt: 2, p: { xs: 2, sm: 2.5 } }}>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                alignItems={{ sm: "center" }}
                justifyContent="space-between"
                spacing={1.5}
                sx={{ mb: 2 }}
              >
                <Typography
                  component="h2"
                  sx={{
                    color: "primary.light",
                    fontFamily: mono,
                    fontSize: 11,
                    fontWeight: 750,
                    textTransform: "uppercase",
                  }}
                >
                  Chat history & context
                </Typography>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => setAscending((value) => !value)}
                >
                  Sort: {ascending ? "Oldest first" : "Newest first"}
                </Button>
              </Stack>
              {orderedUnits.length === 0 ? (
                <EmptyState title="No context yet">
                  No context units have been captured for this project.
                </EmptyState>
              ) : (
                <Stack spacing={1.25}>
                  {orderedUnits.map((unit, index) => {
                    const message = parseMessage(unit);
                    const isLong = message.body.length > 350;
                    const isExpanded = expanded.has(index);
                    const source = safeSourceUrl(unit.source_url);
                    return (
                      <Box
                        component="article"
                        key={unit.id ?? `${unit.created_at}-${index}`}
                        sx={{
                          bgcolor: "#0a0a0c",
                          border: "1px solid",
                          borderColor: "divider",
                          borderLeft: `3px solid ${message.color}`,
                          borderRadius: 1.5,
                          containIntrinsicSize: "0 180px",
                          contentVisibility: "auto",
                          p: 2,
                        }}
                      >
                        <Stack
                          direction={{ xs: "column", sm: "row" }}
                          justifyContent="space-between"
                          spacing={0.75}
                        >
                          <Typography
                            sx={{
                              color: message.color,
                              fontFamily: mono,
                              fontSize: 10,
                              fontWeight: 750,
                              textTransform: "uppercase",
                            }}
                          >
                            {message.icon} {message.label}
                          </Typography>
                          <Typography
                            sx={{
                              color: "text.secondary",
                              fontFamily: mono,
                              fontSize: 9,
                            }}
                          >
                            {formatDate(unit.created_at)} · Tier:{" "}
                            {unit.trust_tier || "agent"}
                            {source && (
                              <>
                                {" "}
                                ·{" "}
                                <Box
                                  component="a"
                                  href={source}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  sx={{ color: "primary.light" }}
                                >
                                  Source ↗
                                </Box>
                              </>
                            )}
                          </Typography>
                        </Stack>
                        <Typography
                          sx={{
                            display: "-webkit-box",
                            lineHeight: 1.7,
                            mt: 1.25,
                            overflow: "hidden",
                            WebkitBoxOrient: "vertical",
                            WebkitLineClamp:
                              isLong && !isExpanded ? 6 : "unset",
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                          }}
                        >
                          {message.body}
                        </Typography>
                        {isLong && (
                          <Button
                            size="small"
                            onClick={() =>
                              setExpanded((current) => {
                                const next = new Set(current);
                                if (next.has(index)) next.delete(index);
                                else next.add(index);
                                return next;
                              })
                            }
                            sx={{ mt: 1, px: 0 }}
                          >
                            {isExpanded
                              ? "− Collapse message"
                              : "+ Show full message"}
                          </Button>
                        )}
                      </Box>
                    );
                  })}
                </Stack>
              )}
            </Card>
            <Typography
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 9,
                mt: 1.5,
                textAlign: "right",
              }}
            >
              ○ secure polling
            </Typography>
          </>
        )}
      </Box>
    </Box>
  );
}
