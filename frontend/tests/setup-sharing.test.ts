import assert from "node:assert/strict";
import test from "node:test";

import { ALL_SOURCES_ID } from "../src/lib/sources.ts";
import {
  isSetupSharingSelected,
  reconnectCommand,
  repositoryFiles,
  SETUP_SHARING_ID,
} from "../src/lib/setup-sharing.ts";

test("reconnect command targets the selected project", () => {
  assert.equal(
    reconnectCommand("project-123"),
    "loom login\nloom switch project-123 --install all",
  );
});

test("repository guide covers each generated integration file", () => {
  assert.deepEqual(
    repositoryFiles.map((file) => file.path),
    [
      ".loom/project.json",
      ".codex/hooks.json",
      ".mcp.json",
      ".claude/settings.json",
      "opencode.json",
      ".opencode/plugins/loom.js",
    ],
  );
  assert.match(repositoryFiles[2].purpose, /Codex does not need/);
});

test("setup selection returns to memory for any source", () => {
  assert.equal(isSetupSharingSelected(SETUP_SHARING_ID), true);
  assert.equal(isSetupSharingSelected(ALL_SOURCES_ID), false);
  assert.equal(isSetupSharingSelected("session:codex_cli:one"), false);
});
