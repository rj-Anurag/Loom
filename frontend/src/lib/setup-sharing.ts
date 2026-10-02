export const SETUP_SHARING_ID = "setup-sharing";

export function isSetupSharingSelected(selectedSourceId: string): boolean {
  return selectedSourceId === SETUP_SHARING_ID;
}

export const repositoryFiles = [
  {
    path: ".loom/project.json",
    purpose:
      "Binds this repository to a Loom project. It contains project identity, not a credential.",
  },
  {
    path: ".codex/hooks.json",
    purpose: "Captures Codex conversation turns through project hooks.",
  },
  {
    path: ".mcp.json",
    purpose:
      "Registers Loom as a project MCP server for Claude Code. Codex does not need this file.",
  },
  {
    path: ".claude/settings.json",
    purpose: "Captures Claude Code conversation turns through project hooks.",
  },
  {
    path: "opencode.json",
    purpose: "Registers the Loom MCP server with OpenCode.",
  },
  {
    path: ".opencode/plugins/loom.js",
    purpose: "Captures OpenCode conversation turns.",
  },
] as const;

export function reconnectCommand(projectId: string): string {
  return `loom login\nloom switch ${projectId} --install all`;
}
