"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import {
  ArrowDownUp,
  Bot,
  ExternalLink,
  FileText,
  Globe2,
  Layers3,
  Search,
  TerminalSquare,
  X,
} from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { formatDate } from "@/lib/api";
import {
  ALL_SOURCES_ID,
  sourceTypeLabel,
  unitMatchesSource,
  unitSearchText,
} from "@/lib/sources";
import type {
  ContextMetadata,
  ContextUnit,
  MemorySource,
  Project,
  TaskResultTest,
} from "@/lib/types";

const mono = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
const DATE_WINDOWS: Record<string, number> = {
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
};

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
  const human = /^(User|Human):/i.test(content) || unit.trust_tier === "user";
  const assistant = /^(AI|Assistant):/i.test(content);
  return {
    role: human
      ? "You"
      : assistant
        ? "Assistant"
        : sourceTypeLabel(unit.type || "context"),
    color: human ? "#60a5fa" : assistant ? "#a78bfa" : "#a3a3a3",
    content: content.replace(/^(User|Human|AI|Assistant):\s*/i, ""),
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
  return (
    <Card
      component="article"
      sx={{
        borderLeft: `3px solid ${details.color}`,
        containIntrinsicSize: "0 220px",
        contentVisibility: "auto",
        p: 2.25,
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
          {formatDate(unit.created_at)}
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
        sx={{ borderTop: "1px solid", borderColor: "divider", mt: 2, pt: 1.5 }}
      >
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
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase());
  const [unitType, setUnitType] = useState("all");
  const [agent, setAgent] = useState("all");
  const [dateWindow, setDateWindow] = useState("all");
  const [ascending, setAscending] = useState(false);
  const [filterClock] = useState(() => Date.now());
  const selectedSource = sources.find(
    (source) => source.id === selectedSourceId,
  );

  const unitTypes = useMemo(
    () =>
      [
        ...new Set(
          units
            .map((unit) => unit.type)
            .filter((value): value is string => Boolean(value)),
        ),
      ].toSorted(),
    [units],
  );
  const agents = useMemo(() => {
    const unique = new Map<string, string>();
    for (const unit of units) {
      const key = unit.agent_id || unit.agent_name;
      if (key)
        unique.set(key, unit.agent_name || unit.agent_id || "Unknown agent");
    }
    return [...unique.entries()].toSorted((left, right) =>
      left[1].localeCompare(right[1]),
    );
  }, [units]);

  const visibleUnits = useMemo(() => {
    const cutoff = DATE_WINDOWS[dateWindow]
      ? filterClock - DATE_WINDOWS[dateWindow]
      : null;
    const filtered = units.filter((unit) => {
      if (!unitMatchesSource(unit, selectedSource)) return false;
      if (unitType !== "all" && unit.type !== unitType) return false;
      if (agent !== "all" && (unit.agent_id || unit.agent_name) !== agent)
        return false;
      if (
        cutoff &&
        (!unit.created_at || new Date(unit.created_at).getTime() < cutoff)
      )
        return false;
      return !deferredQuery || unitSearchText(unit).includes(deferredQuery);
    });
    return ascending ? filtered.toReversed() : filtered;
  }, [
    agent,
    ascending,
    dateWindow,
    deferredQuery,
    filterClock,
    selectedSource,
    unitType,
    units,
  ]);

  const filtered = Boolean(
    query || unitType !== "all" || agent !== "all" || dateWindow !== "all",
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

  const clearFilters = () => {
    setQuery("");
    setUnitType("all");
    setAgent("all");
    setDateWindow("all");
  };

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

      <Box
        aria-label="Memory filters"
        sx={{
          display: "grid",
          gap: 1.25,
          gridTemplateColumns: {
            xs: "1fr",
            md: "minmax(240px,1fr) repeat(3,minmax(130px,.35fr)) auto",
          },
          my: 3,
        }}
      >
        <TextField
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search project memory"
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <Search aria-hidden size={17} />
                </InputAdornment>
              ),
            },
          }}
        />
        <TextField
          select
          label="Type"
          value={unitType}
          onChange={(event) => setUnitType(event.target.value)}
        >
          <MenuItem value="all">All types</MenuItem>
          {unitTypes.map((type) => (
            <MenuItem key={type} value={type}>
              {sourceTypeLabel(type)}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Agent"
          value={agent}
          onChange={(event) => setAgent(event.target.value)}
        >
          <MenuItem value="all">All agents</MenuItem>
          {agents.map(([key, name]) => (
            <MenuItem key={key} value={key}>
              {name}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Date"
          value={dateWindow}
          onChange={(event) => setDateWindow(event.target.value)}
        >
          <MenuItem value="all">Any time</MenuItem>
          <MenuItem value="24h">Last 24 hours</MenuItem>
          <MenuItem value="7d">Last 7 days</MenuItem>
          <MenuItem value="30d">Last 30 days</MenuItem>
        </TextField>
        <Stack direction="row" spacing={0.5} alignItems="center">
          {filtered ? (
            <Tooltip title="Clear filters">
              <IconButton
                aria-label="Clear memory filters"
                onClick={clearFilters}
              >
                <X size={18} />
              </IconButton>
            </Tooltip>
          ) : null}
          <Tooltip
            title={ascending ? "Show newest first" : "Show oldest first"}
          >
            <IconButton
              aria-label={ascending ? "Show newest first" : "Show oldest first"}
              onClick={() => setAscending((value) => !value)}
            >
              <ArrowDownUp size={18} />
            </IconButton>
          </Tooltip>
        </Stack>
      </Box>

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
        <EmptyState
          title={
            selectedSource?.unit_count === 0 && !filtered
              ? "No captured memory yet"
              : "No matching memory"
          }
        >
          {selectedSource?.unit_count === 0 && !filtered
            ? "This source is linked, but it has not captured a context unit yet."
            : "Choose another source or clear one of the filters."}
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
    </>
  );
}
