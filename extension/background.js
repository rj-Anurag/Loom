/**
 * Loom Extension — Background Service Worker
 *
 * Handles all API communication with the Loom context server.
 * Messages from content script and popup are routed here.
 */

importScripts('config.js', 'storage.js');

// ── API helpers ──────────────────────────────────────────────────────────────

const API = LOOM_CONFIG.LOOM_SERVER_URL;

/**
 * Get authentication headers from stored or default credentials.
 */
async function authHeaders() {
  const creds = await Storage.getCredentials();
  if (creds) {
    return { Authorization: `Bearer ${creds.api_key}` };
  }
  // Fall back to the default API key from config
  if (LOOM_CONFIG.DEFAULT_API_KEY) {
    return { Authorization: `Bearer ${LOOM_CONFIG.DEFAULT_API_KEY}` };
  }
  return {};
}

/**
 * Make a JSON request to the Loom API.
 */
async function api(path, options = {}) {
  const url = `${API}${path}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(await authHeaders()),
    ...(options.headers || {}),
  };

  const resp = await fetch(url, {
    method: options.method || 'GET',
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Loom API ${resp.status}: ${text}`);
  }

  return resp.json();
}

// ── Message Router ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handler = MESSAGE_HANDLERS[msg.type];
  if (handler) {
    handler(msg, sender)
      .then(sendResponse)
      .catch(err => {
        console.error(`[Loom] Error handling ${msg.type}:`, err);
        sendResponse({ error: err.message });
      });
    return true; // keep channel open for async response
  }
});

const MESSAGE_HANDLERS = {

  /**
   * CHECK_LINK — Is this chat URL already linked?
   */
  async CHECK_LINK(msg) {
    const linkInfo = await Storage.getProjectForChat(msg.chatUrl);
    if (linkInfo) {
      return {
        linked: true,
        projectId: linkInfo.projectId,
        projectName: linkInfo.projectName,
      };
    }
    return { linked: false };
  },

  /**
   * GET_PROJECTS — Fetch list of projects for the popup dropdown.
   */
  async GET_PROJECTS() {
    const data = await api('/v1/projects');
    return { projects: data };
  },

  /**
   * CREATE_PROJECT — Create a new project (returns browser agent credentials).
   */
  async CREATE_PROJECT(msg) {
    const data = await api('/v1/projects', {
      method: 'POST',
      body: { name: msg.name },
    });

    // Store the returned browser agent credentials
    if (data.agent_id && data.api_key) {
      await Storage.setCredentials(data.agent_id, data.api_key);
    }

    return data;
  },

  /**
   * LINK_CHAT — Link a chat URL to a project.
   */
  async LINK_CHAT(msg) {
    const data = await api(`/v1/projects/${msg.projectId}/link/chat`, {
      method: 'POST',
      body: {
        chat_url: msg.chatUrl,
        title: msg.title || '',
        platform: msg.platform || '',
      },
    });

    // Persist the link locally
    if (data.chat_url) {
      await Storage.setChatLink(data.chat_url, msg.projectId, msg.projectName);
    }

    return data;
  },

  /**
   * SYNC_MESSAGES — Sync captured chat messages as context units.
   * Called by the content script when new DOM messages are detected.
   */
  async SYNC_MESSAGES(msg) {
    const linkInfo = await Storage.getProjectForChat(msg.chatUrl);
    if (!linkInfo) {
      console.warn('[Loom] Cannot sync — chat not linked to any project');
      return { synced: 0 };
    }
    const projectId = linkInfo.projectId;

    const results = [];
    for (const message of msg.messages) {
      const clientUuid = await generateClientUuid(msg.chatUrl, message.index);
      const content = `${message.role === 'user' ? 'User' : 'AI'}: ${message.content}`;

      try {
        const data = await api(`/v1/projects/${projectId}/context`, {
          method: 'POST',
          body: {
            client_uuid: clientUuid,
            type: 'message',
            content,
            trust_tier: 'user',
            version: 1,
          },
        });
        results.push(data);
      } catch (err) {
        console.warn('[Loom] Sync message failed:', err);
      }
    }

    return { synced: results.length };
  },
};

// ── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Generate a deterministic UUID for idempotent sync.
 * Uses SHA-256 hash of chatUrl + index, formatted as UUID v4-like.
 * Deterministic: same inputs always produce same UUID.
 */
async function generateClientUuid(chatUrl, index) {
  const str = `${chatUrl}:${index}`;
  const encoder = new TextEncoder();
  const data = encoder.encode(str);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  // Take first 16 bytes and format as UUID v4
  const bytes = hashArray.slice(0, 16);
  // Set version 4 bits (4xxx)
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  // Set variant bits (10xx)
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.map(b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20,32)}`;
}

// ── Boot ────────────────────────────────────────────────────────────────────

console.log('[Loom] Background service worker started');
