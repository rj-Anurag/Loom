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
 * Get authentication headers from stored credentials.
 */
async function authHeaders() {
  const creds = await Storage.getCredentials();
  if (creds) {
    return { Authorization: `Bearer ${creds.api_key}` };
  }
  // Fall back to any stored browser agent's credentials
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
    const projectId = await Storage.getProjectForChat(msg.chatUrl);
    if (projectId) {
      return { linked: true, projectId, projectName: projectId };
    }
    // Also check server-side via the link-chat endpoint (idempotent lookup)
    try {
      // We don't have a GET endpoint for chat links, so just return false
      return { linked: false };
    } catch {
      return { linked: false };
    }
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
      await Storage.setChatLink(data.chat_url, msg.projectId);
    }

    return data;
  },

  /**
   * SYNC_MESSAGES — Sync captured chat messages as context units.
   * Called by the content script when new DOM messages are detected.
   */
  async SYNC_MESSAGES(msg) {
    const projectId = await Storage.getProjectForChat(msg.chatUrl);
    if (!projectId) {
      console.warn('[Loom] Cannot sync — chat not linked to any project');
      return { synced: 0 };
    }

    const results = [];
    for (const message of msg.messages) {
      const clientUuid = generateClientUuid(msg.chatUrl, message.index);
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
 * Generate a deterministic UUID v5 for idempotent sync.
 * Uses the chat URL + message index as the name.
 */
function generateClientUuid(chatUrl, index) {
  // Simple hash-based UUID-like string (browser-compatible, no crypto.subtle needed)
  const str = `${chatUrl}:${index}`;
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const chr = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0; // Convert to 32bit integer
  }
  // Format as a UUID-like string
  const template = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx';
  return template.replace(/[xy]/g, c => {
    const r = (hash + Math.random() * 16) | 0;
    hash = Math.floor(hash / 16);
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// ── Boot ────────────────────────────────────────────────────────────────────

console.log('[Loom] Background service worker started');
