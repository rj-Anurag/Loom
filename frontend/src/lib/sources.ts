import type { Chat, ContextUnit, MemorySource } from "@/lib/types";

const SOURCE_LABELS: Record<string, string> = {
  browser_chat: "Browser conversation",
  claude_code: "Claude Code",
  codex_cli: "Codex",
  dashboard: "Dashboard",
  manual_cli: "Manual CLI",
  mcp_agent: "MCP agent",
  opencode: "OpenCode",
};

export const ALL_SOURCES_ID = "all";

export function sourceTypeLabel(sourceType?: string): string {
  if (!sourceType) return "Unknown source";
  return (
    SOURCE_LABELS[sourceType] ??
    sourceType
      .split("_")
      .filter(Boolean)
      .map((part) => part[0]?.toUpperCase() + part.slice(1))
      .join(" ")
  );
}

export function normalizeSourceUrl(value?: string): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    url.hash = "";
    url.protocol = url.protocol.toLowerCase();
    url.hostname = url.hostname.toLowerCase();
    url.pathname = url.pathname.replace(/\/+$/, "") || "/";
    return url.toString();
  } catch {
    return value.replace(/\/+$/, "");
  }
}

function browserSourceId(url: string): string {
  return `browser:${url}`;
}

function harnessSourceId(unit: ContextUnit): string {
  return [
    unit.source_session_id ? "session" : "unscoped",
    unit.source_type || "unknown",
    unit.source_session_id || "none",
    unit.agent_id || "unknown-agent",
  ].join(":");
}

function earlier(left?: string, right?: string): string | undefined {
  if (!left) return right;
  if (!right) return left;
  return left < right ? left : right;
}

function later(left?: string, right?: string): string | undefined {
  if (!left) return right;
  if (!right) return left;
  return left > right ? left : right;
}

function platformName(chat: Chat): string {
  if (chat.platform) return chat.platform.replace(/^www\./, "");
  try {
    return new URL(chat.chat_url).hostname.replace(/^www\./, "");
  } catch {
    return "Conversation";
  }
}

function terminalTitle(unit: ContextUnit, sourceType: string): string {
  if (typeof unit.metadata?.session_title === "string" && unit.metadata.session_title.trim()) {
    return unit.metadata.session_title;
  }
  if (unit.metadata?.conversation_role === "user" && unit.content?.trim()) {
    return unit.content.trim().split("\n", 1)[0].slice(0, 80);
  }
  return `${sourceTypeLabel(sourceType)} session`;
}

export function buildMemorySources(
  chats: Chat[],
  units: ContextUnit[],
): MemorySource[] {
  const sources = new Map<string, MemorySource>();

  for (const chat of chats) {
    const sourceUrl = normalizeSourceUrl(chat.chat_url) ?? chat.chat_url;
    sources.set(browserSourceId(sourceUrl), {
      id: browserSourceId(sourceUrl),
      kind: "browser",
      title: chat.title || "Untitled conversation",
      subtitle: platformName(chat),
      source_type: "browser_chat",
      source_url: sourceUrl,
      platform: platformName(chat),
      linked_at: chat.linked_at,
      unit_count: 0,
    });
  }

  for (const unit of units.toSorted((left, right) =>
    (left.occurred_at || left.created_at || "").localeCompare(
      right.occurred_at || right.created_at || "",
    ))) {
    const browser =
      unit.source_type === "browser_chat" || Boolean(unit.source_url);
    const normalizedUrl = normalizeSourceUrl(unit.source_url);
    const id =
      browser && normalizedUrl
        ? browserSourceId(normalizedUrl)
        : harnessSourceId(unit);
    const existing = sources.get(id);

    if (existing) {
      existing.unit_count += 1;
      existing.first_seen_at = earlier(existing.first_seen_at, unit.occurred_at || unit.created_at);
      existing.last_seen_at = later(existing.last_seen_at, unit.occurred_at || unit.created_at);
      existing.agent_id ??= unit.agent_id;
      existing.agent_name ??= unit.agent_name;
      if (existing.kind === "session") {
        if (typeof unit.metadata?.session_title === "string" && unit.metadata.session_title.trim()) {
          existing.title = unit.metadata.session_title;
        } else if (unit.metadata?.conversation_role === "user" && existing.title.endsWith(" session")) {
          existing.title = terminalTitle(unit, existing.source_type);
        }
      }
      continue;
    }

    const sourceType = browser
      ? "browser_chat"
      : unit.source_type || "mcp_agent";
    const agent = unit.agent_name || "Unknown agent";
    sources.set(id, {
      id,
      kind: browser
        ? "browser"
        : unit.source_session_id
          ? "session"
          : "unscoped",
      title: browser
        ? "Unlinked browser conversation"
        : unit.source_session_id
          ? terminalTitle(unit, sourceType)
          : `Unscoped ${sourceTypeLabel(sourceType)}`,
      subtitle: browser
        ? normalizedUrl || "Browser source"
        : `${agent} · ${unit.source_session_id || "No session ID"}`,
      source_type: sourceType,
      source_session_id: unit.source_session_id,
      source_url: normalizedUrl,
      agent_id: unit.agent_id,
      agent_name: unit.agent_name,
      unit_count: 1,
      first_seen_at: unit.occurred_at || unit.created_at,
      last_seen_at: unit.occurred_at || unit.created_at,
    });
  }

  return [...sources.values()].toSorted((left, right) => {
    if (left.kind === "browser" && right.kind !== "browser") return -1;
    if (left.kind !== "browser" && right.kind === "browser") return 1;
    return (right.last_seen_at || right.linked_at || "").localeCompare(
      left.last_seen_at || left.linked_at || "",
    );
  });
}

export function unitMatchesSource(
  unit: ContextUnit,
  source: MemorySource | undefined,
): boolean {
  if (!source) return true;
  if (source.kind === "browser") {
    return normalizeSourceUrl(unit.source_url) === source.source_url;
  }
  return (
    (unit.source_type || "mcp_agent") === source.source_type &&
    (unit.source_session_id || undefined) === source.source_session_id &&
    (unit.agent_id || undefined) === source.agent_id
  );
}

export function orderTerminalMessages(units: ContextUnit[]): ContextUnit[] {
  return units.toSorted((left, right) =>
    (left.occurred_at || left.created_at || "").localeCompare(
      right.occurred_at || right.created_at || "",
    ) || (left.metadata?.message_sequence ?? 0) - (right.metadata?.message_sequence ?? 0));
}

export function unitSearchText(unit: ContextUnit): string {
  const metadata = unit.metadata ?? {};
  const metadataText = [
    metadata.task_name,
    ...(Array.isArray(metadata.files_touched) ? metadata.files_touched : []),
    ...(Array.isArray(metadata.errors) ? metadata.errors : []),
    ...(Array.isArray(metadata.blockers) ? metadata.blockers : []),
    ...(Array.isArray(metadata.next_steps) ? metadata.next_steps : []),
  ]
    .filter((value): value is string => typeof value === "string")
    .join(" ");
  return [
    unit.content,
    unit.type,
    unit.source_type,
    unit.source_session_id,
    unit.agent_name,
    metadataText,
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
}
