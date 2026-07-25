/**
 * Loom Extension — Configuration
 *
 * Central config for the Loom browser extension.
 * Change LOOM_SERVER_URL to point at your Loom context server.
 */

const LOOM_CONFIG = {
  /** Base URL of the Loom context server (no trailing slash). */
  LOOM_SERVER_URL: 'http://localhost:8000',

  /**
   * Default API key — the agent UUID from the Loom extension setup.
   * The extension tries stored credentials first, then falls back to this.
   * Regenerate by calling GET /v1/extension/setup on the running server.
   */
  DEFAULT_API_KEY: 'a7318f8c-e1d8-4d94-b6be-ab58aa17640e',

  /** Chat platforms the extension recognises. */
  SUPPORTED_PLATFORMS: [
    { hostname: 'claude.ai',      name: 'Claude.ai' },
    { hostname: 'chatgpt.com',    name: 'ChatGPT' },
  ],

  /** How often (ms) to flush queued messages to the Loom API. */
  SYNC_INTERVAL_MS: 5_000,

  /** Max messages to batch in a single sync request. */
  MAX_BATCH_SIZE: 20,

  /** Storage keys. */
  STORAGE_KEYS: {
    CHAT_LINKS: 'loom_chat_links',       // { [chatUrl]: projectId }
    AGENT_CREDENTIALS: 'loom_credentials', // { agent_id, api_key }
  },
};
