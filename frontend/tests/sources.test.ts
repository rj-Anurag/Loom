import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMemorySources,
  normalizeSourceUrl,
  orderTerminalMessages,
  unitMatchesSource,
  unitSearchText,
} from "../src/lib/sources.ts";

test("preserves linked browser chats without captured units", () => {
  const [source] = buildMemorySources(
    [
      {
        chat_url: "https://chatgpt.com/c/example/",
        title: "Planning chat",
        platform: "chatgpt.com",
      },
    ],
    [],
  );

  assert.equal(source.kind, "browser");
  assert.equal(source.title, "Planning chat");
  assert.equal(source.unit_count, 0);
  assert.equal(source.source_url, "https://chatgpt.com/c/example");
});

test("keeps harness sessions separate and groups their units", () => {
  const sources = buildMemorySources(
    [],
    [
      {
        id: "one",
        source_type: "opencode",
        source_session_id: "session-a",
        agent_id: "agent-1",
        agent_name: "OpenCode",
        created_at: "2026-10-01T10:00:00Z",
      },
      {
        id: "two",
        source_type: "opencode",
        source_session_id: "session-a",
        agent_id: "agent-1",
        agent_name: "OpenCode",
        created_at: "2026-10-01T11:00:00Z",
      },
      {
        id: "three",
        source_type: "opencode",
        source_session_id: "session-b",
        agent_id: "agent-1",
        agent_name: "OpenCode",
        created_at: "2026-10-01T12:00:00Z",
      },
    ],
  );

  assert.equal(sources.length, 2);
  assert.equal(
    sources.find((source) => source.source_session_id === "session-a")
      ?.unit_count,
    2,
  );
  assert.equal(
    sources.find((source) => source.source_session_id === "session-b")
      ?.unit_count,
    1,
  );
});

test("matches normalized browser URLs and exact harness provenance", () => {
  const browserUnit = {
    source_type: "browser_chat",
    source_url: "https://ChatGPT.com/c/example/#turn",
  };
  const [browserSource] = buildMemorySources(
    [{ chat_url: "https://chatgpt.com/c/example", title: "Chat" }],
    [browserUnit],
  );
  assert.equal(
    normalizeSourceUrl(browserUnit.source_url),
    "https://chatgpt.com/c/example",
  );
  assert.equal(unitMatchesSource(browserUnit, browserSource), true);

  const harnessUnit = {
    source_type: "codex_cli",
    source_session_id: "session-1",
    agent_id: "agent-1",
  };
  const [harnessSource] = buildMemorySources([], [harnessUnit]);
  assert.equal(unitMatchesSource(harnessUnit, harnessSource), true);
  assert.equal(
    unitMatchesSource(
      { ...harnessUnit, source_session_id: "session-2" },
      harnessSource,
    ),
    false,
  );
});

test("search text includes structured task-result metadata", () => {
  const searchText = unitSearchText({
    type: "task_result",
    agent_name: "Codex",
    metadata: {
      task_name: "Source explorer",
      files_touched: ["frontend/src/lib/sources.ts"],
      blockers: ["Preview OAuth"],
    },
  });

  assert.match(searchText, /source explorer/);
  assert.match(searchText, /sources\.ts/);
  assert.match(searchText, /preview oauth/);
});

test("terminal session uses its captured title and groups conversation turns", () => {
  const units = [
    { source_type: "codex_cli", source_session_id: "native", agent_id: "agent",
      content: "Please keep Unicode café", metadata: { conversation_role: "user" as const,
        session_title: "Memory discussion" }, created_at: "2026-10-02T10:00:00Z" },
    { source_type: "codex_cli", source_session_id: "native", agent_id: "agent",
      content: "Understood", metadata: { conversation_role: "assistant" as const },
      created_at: "2026-10-02T10:01:00Z" },
  ];
  const [source] = buildMemorySources([], units);
  assert.equal(source.title, "Memory discussion");
  assert.equal(source.unit_count, 2);
  assert.ok(units.every((unit) => unitMatchesSource(unit, source)));
});

test("terminal turns sort by occurrence and sequence", () => {
  const ordered = orderTerminalMessages([
    { id: "assistant", occurred_at: "2026-10-02T10:01:00Z", metadata: { message_sequence: 1 } },
    { id: "user", occurred_at: "2026-10-02T10:00:00Z", metadata: { message_sequence: 0 } },
    { id: "second", occurred_at: "2026-10-02T10:01:00Z", metadata: { message_sequence: 2 } },
  ]);
  assert.deepEqual(ordered.map((unit) => unit.id), ["user", "assistant", "second"]);
});

test("harness title takes precedence over the first prompt", () => {
  const [source] = buildMemorySources([], [
    { source_type: "opencode", source_session_id: "native", agent_id: "agent",
      content: "Later question", metadata: { conversation_role: "user" },
      occurred_at: "2026-10-02T10:02:00Z" },
    { source_type: "opencode", source_session_id: "native", agent_id: "agent",
      content: "First question", metadata: { conversation_role: "user" },
      occurred_at: "2026-10-02T10:00:00Z" },
    { source_type: "opencode", source_session_id: "native", agent_id: "agent",
      metadata: { conversation_role: "assistant", session_title: "Native title" },
      occurred_at: "2026-10-02T10:01:00Z" },
  ]);
  assert.equal(source.title, "Native title");
});
