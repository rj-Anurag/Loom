"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import {
  Bot,
  ExternalLink,
  FileText,
  Globe2,
  Layers3,
  Settings2,
  TerminalSquare,
} from "lucide-react";
import { useMemo } from "react";

import { EmptyState } from "@/components/empty-state";
import { formatDate } from "@/lib/api";
import {
  ALL_SOURCES_ID,
  orderTerminalMessages,
  sourceTypeLabel,
  unitMatchesSource,
} from "@/lib/sources";
import { SETUP_SHARING_ID } from "@/lib/setup-sharing";
import type {
  ContextMetadata,
  ContextUnit,
  MemorySource,
  Project,
  TaskResultTest,
} from "@/lib/types";

const mono = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";

function sourceIcon(source: MemorySource) {
  if (source.kind === "browser") return <Globe2 aria-hidden size={16} />;
  if (source.source_type === "codex_cli" || source.source_type === "opencode") {
    return <TerminalSquare aria-hidden size={16} />;
  }
  return <Bot aria-hidden size={16} />;
}

function SourceButton({
  source,
  selected,
  onSelect,
}: {
  source: MemorySource;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <Button
      fullWidth
      aria-pressed={selected}
      onClick={onSelect}
      sx={{
        alignItems: "flex-start",
        bgcolor: selected ? "rgba(139,92,246,.13)" : "transparent",
        color: "text.primary",
        justifyContent: "flex-start",
        mb: 0.5,
        minHeight: 56,
        px: 1.25,
        py: 1,
      }}
    >
      <Box sx={{ color: "primary.light", display: "flex", mr: 1.25, mt: 0.25 }}>
        {sourceIcon(source)}
      </Box>
      <Box sx={{ minWidth: 0, textAlign: "left", width: "100%" }}>
        <Stack direction="row" justifyContent="space-between" spacing={1}>
          <Typography noWrap sx={{ fontSize: 13, fontWeight: 650 }}>
            {source.title}
          </Typography>
          <Typography
            sx={{ color: "text.secondary", fontFamily: mono, fontSize: 9 }}
          >
            {source.unit_count}
          </Typography>
        </Stack>
        <Typography
          noWrap
          sx={{
            color: "text.secondary",
            fontFamily: mono,
            fontSize: 9,
            mt: 0.25,
          }}
        >
          {source.subtitle}
        </Typography>
      </Box>
    </Button>
  );
}

function SourceGroup({
  label,
  sources,
  selectedSourceId,
  onSelect,
}: {
  label: string;
  sources: MemorySource[];
  selectedSourceId: string;
  onSelect: (sourceId: string) => void;
}) {
  if (sources.length === 0) return null;
  return (
    <Box sx={{ mt: 2 }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        sx={{ mb: 0.75, px: 1.25 }}
      >
        <Typography
          sx={{
            color: "text.secondary",
            fontFamily: mono,
            fontSize: 9,
            textTransform: "uppercase",
          }}
        >
          {label}
        </Typography>
        <Typography
          sx={{ color: "text.secondary", fontFamily: mono, fontSize: 9 }}
        >
          {sources.length}
        </Typography>
      </Stack>
      {sources.map((source) => (
        <SourceButton
          key={source.id}
          source={source}
          selected={selectedSourceId === source.id}
          onSelect={() => onSelect(source.id)}
        />
      ))}
    </Box>
  );
}

export function SourceNavigation({
  project,
  sources,
  selectedSourceId,
  onSelect,
}: {
  project: Project | null;
  sources: MemorySource[];
  selectedSourceId: string;
  onSelect: (sourceId: string) => void;
}) {
  const browserSources = sources.filter((source) => source.kind === "browser");
  const sessionSources = sources.filter((source) => source.kind === "session");
  const unscopedSources = sources.filter(
    (source) => source.kind === "unscoped",
  );

  return (
    <Box>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="end"
        sx={{ mb: 1.5 }}
      >
        <Box>
          <Typography
            sx={{
              color: "primary.light",
              fontFamily: mono,
              fontSize: 9,
              textTransform: "uppercase",
            }}
          >
            Selected project
          </Typography>
          <Typography component="h2" sx={{ fontSize: 18, fontWeight: 620 }}>
            Memory sources
          </Typography>
        </Box>
        <Typography
          sx={{ color: "text.secondary", fontFamily: mono, fontSize: 11 }}
        >
          {sources.length}
        </Typography>
      </Stack>
      {project ? (
        <>
          <Button
            fullWidth
            aria-pressed={selectedSourceId === ALL_SOURCES_ID}
            onClick={() => onSelect(ALL_SOURCES_ID)}
            sx={{
              bgcolor:
                selectedSourceId === ALL_SOURCES_ID
                  ? "rgba(139,92,246,.13)"
                  : "transparent",
              color: "text.primary",
              justifyContent: "flex-start",
              minHeight: 56,
              px: 1.25,
              py: 1,
            }}
          >
            <Box sx={{ color: "primary.light", display: "flex", mr: 1.25 }}>
              <Layers3 aria-hidden size={16} />
            </Box>
            <Box sx={{ minWidth: 0, textAlign: "left" }}>
              <Typography sx={{ fontSize: 13, fontWeight: 650 }}>
                All project memory
              </Typography>
              <Typography
                sx={{ color: "text.secondary", fontFamily: mono, fontSize: 9 }}
              >
                Every connected source
              </Typography>
            </Box>
          </Button>
          <Button
            fullWidth
            aria-pressed={selectedSourceId === SETUP_SHARING_ID}
            onClick={() => onSelect(SETUP_SHARING_ID)}
            sx={{
              bgcolor:
                selectedSourceId === SETUP_SHARING_ID
                  ? "rgba(139,92,246,.13)"
                  : "transparent",
              color: "text.primary",
              justifyContent: "flex-start",
              minHeight: 56,
              px: 1.25,
              py: 1,
            }}
          >
            <Box sx={{ color: "primary.light", display: "flex", mr: 1.25 }}>
              <Settings2 aria-hidden size={16} />
            </Box>
            <Box sx={{ minWidth: 0, textAlign: "left" }}>
              <Typography sx={{ fontSize: 13, fontWeight: 650 }}>
                Setup &amp; sharing
              </Typography>
              <Typography
                sx={{ color: "text.secondary", fontFamily: mono, fontSize: 9 }}
              >
                Local files and Git
              </Typography>
            </Box>
          </Button>
          <SourceGroup
            label="Browser conversations"
            sources={browserSources}
            selectedSourceId={selectedSourceId}
            onSelect={onSelect}
          />
          <SourceGroup
            label="Observed sessions"
            sources={sessionSources}
            selectedSourceId={selectedSourceId}
            onSelect={onSelect}
          />
          <SourceGroup
            label="Unscoped sources"
            sources={unscopedSources}
            selectedSourceId={selectedSourceId}
            onSelect={onSelect}
          />
        </>
      ) : (
        <Typography color="text.secondary" sx={{ fontSize: 13 }}>
          Select a project to inspect its sources.
        </Typography>
      )}
    </Box>
  );
}

function messageDetails(unit: ContextUnit) {
  const content = unit.content ?? "";
  const terminalRole = unit.metadata?.conversation_role;
  const human = terminalRole === "user" || /^(User|Human):/i.test(content) || unit.trust_tier === "user";
  const assistant = terminalRole === "assistant" || /^(AI|Assistant):/i.test(content);
  return {
    role: human
      ? "You"
      : assistant
        ? "Assistant"
        : sourceTypeLabel(unit.type || "context"),
    color: human ? "#60a5fa" : assistant ? "#a78bfa" : "#a3a3a3",
    content: terminalRole ? content : content.replace(/^(User|Human|AI|Assistant):\s*/i, ""),
  };
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function taskTests(value: unknown): TaskResultTest[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is TaskResultTest =>
          Boolean(item) && typeof item === "object",
      )
    : [];
}

function MetadataList({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <Box>
      <Typography
        sx={{
          color: "text.secondary",
          fontFamily: mono,
          fontSize: 9,
          textTransform: "uppercase",
        }}
      >
        {label}
      </Typography>
      <Stack component="ul" spacing={0.5} sx={{ mb: 0, mt: 0.75, pl: 2.25 }}>
        {values.map((value) => (
          <Typography
            component="li"
            key={value}
            sx={{ fontSize: 12, overflowWrap: "anywhere" }}
          >
            {value}
          </Typography>
        ))}
      </Stack>
    </Box>
  );
}

function TaskResultDetails({ metadata }: { metadata: ContextMetadata }) {
  const tests = taskTests(metadata.tests);
  const confidence =
    typeof metadata.confidence === "number" &&
    metadata.confidence >= 0 &&
    metadata.confidence <= 1
      ? `${Math.round(metadata.confidence * 100)}%`
      : null;
  const hasDetails =
    metadata.task_name ||
    tests.length > 0 ||
    stringList(metadata.files_touched).length > 0 ||
    stringList(metadata.errors).length > 0 ||
    stringList(metadata.blockers).length > 0 ||
    stringList(metadata.next_steps).length > 0 ||
    confidence;
  if (!hasDetails) return null;

  return (
    <Box sx={{ borderTop: "1px solid", borderColor: "divider", mt: 2, pt: 2 }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        spacing={1}
      >
        <Box>
          <Typography
            sx={{
              color: "primary.light",
              fontFamily: mono,
              fontSize: 9,
              textTransform: "uppercase",
            }}
          >
            Verified task result
          </Typography>
          {typeof metadata.task_name === "string" ? (
            <Typography sx={{ fontSize: 15, fontWeight: 700, mt: 0.5 }}>
              {metadata.task_name}
            </Typography>
          ) : null}
        </Box>
        {confidence ? (
          <Typography
            sx={{ color: "text.secondary", fontFamily: mono, fontSize: 10 }}
          >
            Confidence {confidence}
          </Typography>
        ) : null}
      </Stack>
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", md: "repeat(2,minmax(0,1fr))" },
          mt: 2,
        }}
      >
        <MetadataList
          label="Files touched"
          values={stringList(metadata.files_touched)}
        />
        <MetadataList
          label="Next steps"
          values={stringList(metadata.next_steps)}
        />
        <MetadataList label="Errors" values={stringList(metadata.errors)} />
        <MetadataList label="Blockers" values={stringList(metadata.blockers)} />
      </Box>
      {tests.length > 0 ? (
        <Box sx={{ mt: 2 }}>
          <Typography
            sx={{
              color: "text.secondary",
              fontFamily: mono,
              fontSize: 9,
              textTransform: "uppercase",
            }}
          >
            Tests
          </Typography>
          <Stack spacing={0.75} sx={{ mt: 0.75 }}>
            {tests.map((test, index) => {
              const status = test.status || "not_run";
              const color =
                status === "passed"
                  ? "#43c59e"
                  : status === "failed"
                    ? "#ef6a75"
                    : "#e8b34f";
              return (
                <Box
                  key={`${test.command || "test"}-${index}`}
                  sx={{
                    borderLeft: `2px solid ${color}`,
                    bgcolor: "rgba(255,255,255,.025)",
                    px: 1.25,
                    py: 1,
                  }}
                >
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    justifyContent="space-between"
                    spacing={0.5}
                  >
                    <Typography
                      sx={{
                        fontFamily: mono,
                        fontSize: 11,
                        overflowWrap: "anywhere",
                      }}
                    >
                      {test.command || "Command not recorded"}
                    </Typography>
                    <Typography
                      sx={{
                        color,
                        fontFamily: mono,
                        fontSize: 9,
                        textTransform: "uppercase",
                      }}
                    >
                      {status.replace("_", " ")}
                    </Typography>
                  </Stack>
                  {test.summary ? (
                    <Typography
                      color="text.secondary"
                      sx={{ fontSize: 12, mt: 0.5 }}
                    >
                      {test.summary}
                    </Typography>
                  ) : null}
                </Box>
              );
            })}
          </Stack>
        </Box>
      ) : null}
    </Box>
  );
}

function ContextUnitCard({ unit }: { unit: ContextUnit }) {
  const details = messageDetails(unit);
  const parents = unit.parent_ids ?? [];
  const conversation = unit.metadata?.conversation_role === "user" || unit.metadata?.conversation_role === "assistant";
  return (
    <Card
      component="article"
      sx={{
        borderLeft: `3px solid ${details.color}`,
        containIntrinsicSize: "0 220px",
        contentVisibility: "auto",
        p: conversation ? 1.75 : 2.25,
      }}
    >
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        spacing={0.75}
      >
        <Stack direction="row" alignItems="center" flexWrap="wrap" gap={1}>
          <Typography
            sx={{
              color: details.color,
              fontFamily: mono,
              fontSize: 10,
              fontWeight: 750,
              textTransform: "uppercase",
            }}
          >
            {details.role}
          </Typography>
          <Typography
            sx={{ color: "text.secondary", fontFamily: mono, fontSize: 9 }}
          >
            {sourceTypeLabel(unit.source_type)}
          </Typography>
          {unit.agent_name ? (
            <Typography
              sx={{ color: "text.secondary", fontFamily: mono, fontSize: 9 }}
            >
              {unit.agent_name}
            </Typography>
          ) : null}
        </Stack>
        <Typography
          sx={{
            color: "text.secondary",
            fontFamily: mono,
            fontSize: 9,
            flexShrink: 0,
          }}
        >
          {formatDate(unit.occurred_at || unit.created_at)}
        </Typography>
      </Stack>
      <Typography
        sx={{
          lineHeight: 1.72,
          mt: 1.25,
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
        }}
      >
        {details.content || "No readable summary was recorded."}
      </Typography>
      {unit.type === "task_result" && unit.metadata ? (
        <TaskResultDetails metadata={unit.metadata} />
      ) : null}
      <Box
        component={conversation ? "details" : "div"}
        sx={{ borderTop: "1px solid", borderColor: "divider", mt: 2, pt: 1.5 }}
      >
        {conversation ? (
          <Typography component="summary" sx={{ color: "text.secondary", cursor: "pointer", fontFamily: mono, fontSize: 9 }}>
            Provenance · {unit.metadata?.capture_method || "live"}
          </Typography>
        ) : null}
        <Box
          sx={{
            display: "grid",
            gap: 1,
            gridTemplateColumns: { xs: "1fr", md: "repeat(2,minmax(0,1fr))" },
          }}
        >
          <Box>
            <Typography
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 8,
                textTransform: "uppercase",
              }}
            >
              Unit ID
            </Typography>
            <Typography
              sx={{
                fontFamily: mono,
                fontSize: 9,
                mt: 0.25,
                overflowWrap: "anywhere",
              }}
            >
              {unit.id || "Not recorded"}
            </Typography>
          </Box>
          <Box>
            <Typography
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 8,
                textTransform: "uppercase",
              }}
            >
              Observed session
            </Typography>
            <Typography
              sx={{
                fontFamily: mono,
                fontSize: 9,
                mt: 0.25,
                overflowWrap: "anywhere",
              }}
            >
              {unit.source_session_id || "Unscoped"}
            </Typography>
          </Box>
          <Box>
            <Typography
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 8,
                textTransform: "uppercase",
              }}
            >
              Agent ID
            </Typography>
            <Typography
              sx={{
                fontFamily: mono,
                fontSize: 9,
                mt: 0.25,
                overflowWrap: "anywhere",
              }}
            >
              {unit.agent_id || "Not recorded"}
            </Typography>
          </Box>
          {unit.source_url ? (
            <Box sx={{ gridColumn: { md: "1 / -1" } }}>
              <Typography
                sx={{
                  color: "text.secondary",
                  fontFamily: mono,
                  fontSize: 8,
                  textTransform: "uppercase",
                }}
              >
                Source URL
              </Typography>
              <Typography
                sx={{
                  fontFamily: mono,
                  fontSize: 9,
                  mt: 0.25,
                  overflowWrap: "anywhere",
                }}
              >
                {unit.source_url}
              </Typography>
            </Box>
          ) : null}
          {parents.length > 0 ? (
            <Box sx={{ gridColumn: { md: "1 / -1" } }}>
              <Typography
                sx={{
                  color: "text.secondary",
                  fontFamily: mono,
                  fontSize: 8,
                  textTransform: "uppercase",
                }}
              >
                Parent IDs
              </Typography>
              {parents.map((parent) => (
                <Typography
                  key={parent}
                  sx={{
                    fontFamily: mono,
                    fontSize: 9,
                    mt: 0.25,
                    overflowWrap: "anywhere",
                  }}
                >
                  {parent}
                </Typography>
              ))}
            </Box>
          ) : null}
        </Box>
      </Box>
    </Card>
  );
}

export function SourceExplorer({
  project,
  sources,
  selectedSourceId,
  units,
  loading,
  error,
}: {
  project: Project | null;
  sources: MemorySource[];
  selectedSourceId: string;
  units: ContextUnit[];
  loading: boolean;
  error: string;
}) {
  const selectedSource = sources.find(
    (source) => source.id === selectedSourceId,
  );

  const visibleUnits = useMemo(
    () => {
      const filtered = units.filter((unit) => unitMatchesSource(unit, selectedSource));
      if (selectedSource?.kind === "session" &&
          ["codex_cli", "claude_code", "opencode"].includes(selectedSource.source_type)) {
        return orderTerminalMessages(filtered);
      }
      return filtered;
    },
    [selectedSource, units],
  );
  const observedSessions = sources.filter(
    (source) => source.kind === "session",
  ).length;
  const title = selectedSource?.title || project?.name || "Project memory";
  const eyebrow = selectedSource
    ? selectedSource.kind === "browser"
      ? `${project?.name} / Browser conversation`
      : `${project?.name} / Observed session`
    : `Workspace / ${project?.name ?? "Select a project"}`;
  const description = selectedSource
    ? selectedSource.kind === "browser"
      ? `Captured from ${selectedSource.platform || "a linked browser conversation"}.`
      : `${sourceTypeLabel(selectedSource.source_type)} activity stored as project memory, not live presence.`
    : "Shared memory from every conversation and coding harness connected to this project.";

  const metrics = selectedSource
    ? [
        ["Context units", selectedSource.unit_count],
        [
          "First seen",
          formatDate(
            selectedSource.first_seen_at || selectedSource.linked_at,
            true,
          ),
        ],
        [
          "Last seen",
          formatDate(
            selectedSource.last_seen_at || selectedSource.linked_at,
            true,
          ),
        ],
      ]
    : [
        ["Context units", project?.context_unit_count ?? units.length],
        ["Memory sources", sources.length],
        ["Observed sessions", observedSessions],
      ];

  return (
    <>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "flex-start" }}
        spacing={2}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography
            sx={{
              color: "primary.light",
              fontFamily: mono,
              fontSize: 10,
              textTransform: "uppercase",
            }}
          >
            {eyebrow}
          </Typography>
          <Typography
            component="h1"
            sx={{
              fontSize: { xs: 34, md: 42 },
              fontWeight: 560,
              mt: 0.75,
              overflowWrap: "anywhere",
            }}
          >
            {title}
          </Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            {description}
          </Typography>
          {selectedSource?.source_session_id ? (
            <Typography
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 10,
                mt: 1,
                overflowWrap: "anywhere",
              }}
            >
              {selectedSource.source_session_id}
            </Typography>
          ) : null}
        </Box>
        {selectedSource?.kind === "browser" && selectedSource.source_url ? (
          <Button
            component="a"
            href={selectedSource.source_url}
            target="_blank"
            rel="noopener noreferrer"
            startIcon={<ExternalLink aria-hidden size={16} />}
            variant="outlined"
            sx={{ flexShrink: 0 }}
          >
            Open conversation
          </Button>
        ) : null}
      </Stack>

      <Box
        sx={{
          border: "1px solid",
          borderColor: "divider",
          borderRadius: 2,
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "repeat(3,minmax(0,1fr))" },
          mt: 3,
          overflow: "hidden",
        }}
      >
        {metrics.map(([label, value], index) => (
          <Box
            key={String(label)}
            sx={{
              borderBottom: { xs: index < 2 ? "1px solid" : 0, sm: 0 },
              borderColor: "divider",
              borderRight: { sm: index < 2 ? "1px solid" : 0 },
              p: 2,
            }}
          >
            <Typography
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 9,
                textTransform: "uppercase",
              }}
            >
              {label}
            </Typography>
            <Typography
              sx={{
                fontSize: 19,
                fontWeight: 620,
                mt: 0.5,
                overflowWrap: "anywhere",
              }}
            >
              {value}
            </Typography>
          </Box>
        ))}
      </Box>

      <Box sx={{ mt: 3 }}>
        {loading ? (
          <Stack alignItems="center" sx={{ py: 7 }}>
            <CircularProgress size={28} />
          </Stack>
        ) : error ? (
          <Box
            role="alert"
            sx={{
              border: "1px solid rgba(239,106,117,.45)",
              borderRadius: 1.5,
              color: "#f39aa2",
              p: 2,
            }}
          >
            {error}
          </Box>
        ) : visibleUnits.length === 0 ? (
          <EmptyState title="No captured memory yet">
            {selectedSource
              ? "This source is linked, but it has not captured a context unit yet."
              : "This project has not captured a context unit yet."}
          </EmptyState>
        ) : (
          <Stack spacing={1.25}>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              sx={{ px: 0.25 }}
            >
              <Stack direction="row" alignItems="center" spacing={1}>
                <FileText aria-hidden size={15} />
                <Typography
                  sx={{
                    fontFamily: mono,
                    fontSize: 10,
                    textTransform: "uppercase",
                  }}
                >
                  Memory timeline
                </Typography>
              </Stack>
              <Typography
                sx={{ color: "text.secondary", fontFamily: mono, fontSize: 10 }}
              >
                {visibleUnits.length} shown
              </Typography>
            </Stack>
            {visibleUnits.map((unit, index) => (
              <ContextUnitCard
                key={unit.id ?? `${unit.created_at}-${index}`}
                unit={unit}
              />
            ))}
          </Stack>
        )}
      </Box>
    </>
  );
}
