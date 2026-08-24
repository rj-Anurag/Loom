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
  // Only process messages from our own extension components
  if (sender.id !== chrome.runtime.id) {
    sendResponse({ error: 'unauthorized' });
    return;
  }

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

    // Persist the link locally and save project api_key credentials
    if (data.chat_url) {
      if (data.api_key) {
        await Storage.setCredentials(data.api_key, data.api_key);
      }
      await Storage.setChatLink(data.chat_url, msg.projectId, msg.projectName, data.api_key);
    }

    return data;
  },

  /**
   * GET_AGENT_PRESENCE — Fetch active agents for a project.
   * Called by the popup on an interval while open.
   */
  async GET_AGENT_PRESENCE(msg) {
    const data = await api(`/v1/projects/${msg.projectId}/agents/presence`);
    return { agents: data };
  },

  /**
   * GET_CONFLICTS — Fetch pending conflicts for a project.
   * Called by the popup on an interval while open.
   */
  async GET_CONFLICTS(msg) {
    const data = await api(`/v1/projects/${msg.projectId}/conflicts`);
    return { conflicts: data };
  },

  /**
   * SET_CURRENT_PROJECT — Store the project ID for background alarm polling.
   * Called by the popup on link/unlink to keep the background worker in sync.
   */
  async SET_CURRENT_PROJECT(msg) {
    if (msg.projectId) {
      await Storage.setCurrentProject(msg.projectId, msg.projectName);
    } else {
      await Storage.clearCurrentProject();
    }
    return { ok: true };
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
      const clientUuid = await generateClientUuid(msg.chatUrl, message.content);
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

/**
 * Generate a deterministic UUID for Push-to-Loom idempotency.
 * Uses SHA-256 hash of a 'push-to-loom' prefix + pageUrl + normalized content.
 */
async function generatePushUuid(pageUrl, content) {
  const str = 'push-to-loom:' + pageUrl + ':' + content;
  const encoder = new TextEncoder();
  const data = encoder.encode(str);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const bytes = hashArray.slice(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.map(function(b) { return b.toString(16).padStart(2, '0'); }).join('');
  return hex.slice(0,8) + '-' + hex.slice(8,12) + '-' + hex.slice(12,16) + '-' + hex.slice(16,20) + '-' + hex.slice(20,32);
}

// ── Conflict Alarm ────────────────────────────────────────────────────────────

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'LOOM_CONFLICT_POLL') {
    pollConflictsAndUpdateBadge();
  }
});

// ── Context Menu (Push-to-Loom) ──────────────────────────────────────────────

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== LOOM_CONFIG.PUSH_TO_LOOM.MENU_ITEM_ID) return;
  if (!info.selectionText) return;

  const project = await Storage.getCurrentProject();
  if (!project) {
    console.warn('[Loom] Push-to-Loom: No project linked');
    return;
  }

  // Normalize and truncate text
  let content = info.selectionText
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .trim();
  if (content.length > LOOM_CONFIG.PUSH_TO_LOOM.MAX_CONTENT_LENGTH) {
    content = content.slice(0, LOOM_CONFIG.PUSH_TO_LOOM.MAX_CONTENT_LENGTH);
  }

  const clientUuid = await generatePushUuid(info.pageUrl, content);

  try {
    const result = await api(
      '/v1/projects/' + project.projectId + '/context',
      {
        method: 'POST',
        body: {
          client_uuid: clientUuid,
          type: LOOM_CONFIG.PUSH_TO_LOOM.TYPE,
          content: content,
          trust_tier: LOOM_CONFIG.PUSH_TO_LOOM.TRUST_TIER,
          version: LOOM_CONFIG.PUSH_TO_LOOM.VERSION,
          source_url: info.pageUrl,
        },
      }
    );
    console.log('[Loom] Pushed to', project.projectName || project.projectId, '- id:', result.id);
  } catch (err) {
    console.error('[Loom] Push-to-Loom failed:', err.message);
  }
});

/**
 * Fetch pending conflicts for the stored current project and update
 * the extension icon badge with the count. Clears badge if no project
 * is stored or no conflicts exist.
 */
async function pollConflictsAndUpdateBadge() {
  try {
    const project = await Storage.getCurrentProject();
    if (!project) {
      chrome.action.setBadgeText({ text: '' });
      return;
    }

    const data = await api(`/v1/projects/${project.projectId}/conflicts`);
    const conflicts = Array.isArray(data) ? data : [];
    const count = conflicts.length;

    if (count > 0) {
      chrome.action.setBadgeText({ text: String(count) });
    } else {
      chrome.action.setBadgeText({ text: '' });
    }
  } catch (err) {
    // Don't clear badge on transient errors — stale data is better
    // than silently dropping the badge. Log and move on.
    console.warn('[Loom] Conflict poll failed:', err.message);
  }
}

// ── Boot ────────────────────────────────────────────────────────────────────

// Set badge background color once at startup
chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });

// Register conflict polling alarm (only if not already scheduled, to avoid
// resetting the timer on every service worker wakeup).
chrome.alarms.get('LOOM_CONFLICT_POLL', (alarm) => {
  if (!alarm) {
    chrome.alarms.create('LOOM_CONFLICT_POLL', {
      periodInMinutes: LOOM_CONFIG.POLL_INTERVALS.CONFLICT_BG_ALARM_MINUTES,
    });
  }
});

// Also register on install/update to handle fresh installs
chrome.runtime.onInstalled.addListener(() => {
  // Register right-click context menu for Push-to-Loom
  chrome.contextMenus.create({
    id: LOOM_CONFIG.PUSH_TO_LOOM.MENU_ITEM_ID,
    title: LOOM_CONFIG.PUSH_TO_LOOM.TITLE,
    contexts: ['selection'],
  });

  chrome.alarms.create('LOOM_CONFLICT_POLL', {
    periodInMinutes: LOOM_CONFIG.POLL_INTERVALS.CONFLICT_BG_ALARM_MINUTES,
  });
  // Set badge background color once (text is updated per-poll)
  chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
  // Run an immediate poll on install
  setTimeout(pollConflictsAndUpdateBadge, 1000);
});

console.log('[Loom] Background service worker started');
