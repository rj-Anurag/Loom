/**
 * Loom Extension — Configuration
 *
 * Central config for the Loom browser extension.
 * Change LOOM_SERVER_URL to point at your Loom context server.
 */

const LOOM_CONFIG = {
  /** Base URL of the Loom context server (no trailing slash). */
  LOOM_SERVER_URL: 'http://localhost:8000',

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
