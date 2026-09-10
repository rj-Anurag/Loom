/**
 * Loom Extension — Configuration
 *
 * Central config for the Loom browser extension.
 * Change LOOM_SERVER_URL to point at your Loom context server.
 */

const LOOM_CONFIG = {
  /** Base URL of the Loom context server (no trailing slash). */
  LOOM_SERVER_URL: 'https://loom-api-zzy0.onrender.com',

  /** Optional development override. Leave empty in distributed builds. */
  // Never commit a bearer credential to the extension bundle. The background
  // worker bootstraps a development credential when none has been stored.
  DEFAULT_API_KEY: '',

  /** Chat platforms the extension recognises. */
  SUPPORTED_PLATFORMS: [
    { hostname: 'claude.ai', name: 'Claude' },
    { hostname: 'chatgpt.com', name: 'ChatGPT' },
    { hostname: 'chat.deepseek.com', name: 'DeepSeek' },
    { hostname: 'www.perplexity.ai', name: 'Perplexity' },
  ],

  /** How often (ms) to flush queued messages to the Loom API. */
  SYNC_INTERVAL_MS: 5_000,

  /** Max messages to batch in a single sync request. */
  MAX_BATCH_SIZE: 20,

  /** Polling intervals for real-time data. */
  POLL_INTERVALS: {
    /** How often the popup polls agent presence (ms). */
    AGENT_PRESENCE_POPUP_MS: 5_000,
    /** How often the popup polls conflict list (ms). */
    CONFLICT_POPUP_MS: 30_000,
    /** How often the background alarm fires for conflict polling (minutes). */
    CONFLICT_BG_ALARM_MINUTES: 1,
  },

  /** Context menu (right-click) configuration for Push-to-Loom. */
  PUSH_TO_LOOM: {
    MENU_ITEM_ID: 'loom-push-to-loom',
    TITLE: 'Send to Loom as context',
    /** Max content length matching the API limit. */
    MAX_CONTENT_LENGTH: 100000,
    /** Context unit type for pushed content. */
    TYPE: 'decision',
    /** Trust tier for user-initiated pushes. */
    TRUST_TIER: 'user',
    /** Starting version for new root context units. */
    VERSION: 1,
  },

  /** Base path for the project dashboard (served by Loom server). */
  DASHBOARD_BASE_PATH: '/v1/projects/{project_id}/dashboard',

  /** Storage keys. */
  STORAGE_KEYS: {
    CHAT_LINKS: 'loom_chat_links',       // { [chatUrl]: { projectId, apiKey, ... } }
    AGENT_CREDENTIALS: 'loom_credentials', // { agent_id, api_key }
    PROJECT_CREDENTIALS: 'loom_project_credentials', // { [projectId]: { agent_id, api_key } }
    ACCOUNT_SESSION: 'loom_account_session', // { session_token, user }
    PENDING_SYNC: 'loom_pending_sync', // [{ chatUrl, message, queuedAt, attempts }]
    /** Project ID to use for background polling. Updated by popup on link/unlink. */
    CURRENT_PROJECT: 'loom_current_project',
  },
};
