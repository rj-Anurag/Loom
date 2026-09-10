/**
 * Loom Extension — Background Service Worker
 *
 * Handles all API communication with the Loom context server.
 * Messages from content script and popup are routed here.
 */

importScripts('config.js', 'shared.js', 'storage.js');

if (chrome.storage.local.setAccessLevel) {
  chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' }).catch(function () {});
}

// ── API helpers ──────────────────────────────────────────────────────────────

const API = LOOM_CONFIG.LOOM_SERVER_URL;

/**
 * Get authentication headers from stored or default credentials.
 */
async function authHeaders() {
  const account = await Storage.getAccount();
  if (account?.session_token) {
    return { Authorization: `Bearer ${account.session_token}` };
  }
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

async function responseError(resp) {
  const text = await resp.text();
  let detail = text;
  try {
    const data = JSON.parse(text);
    detail = data.detail || JSON.stringify(data);
  } catch (_error) {}
  return new Error(detail || `Loom API ${resp.status}`);
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

  let resp = await fetch(url, {
    method: options.method || 'GET',
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (resp.status === 401 && !options._retried) {
    const match = path.match(/^\/v1\/projects\/([0-9a-f-]{36})(?:\/|$)/i);
    const account = await Storage.getAccount();
    if (match && account?.session_token && options.headers?.Authorization) {
      await Storage.removeProjectCredentials(match[1]);
      const refreshed = await enrollBrowserAgent(match[1], account.session_token);
      headers.Authorization = `Bearer ${refreshed.api_key}`;
      resp = await fetch(url, {
        method: options.method || 'GET',
        headers,
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
    }
  }

  if (!resp.ok) {
    throw await responseError(resp);
  }

  return resp.json();
}

async function enrollBrowserAgent(projectId, apiKey) {
  const resp = await fetch(`${API}/v1/projects/${projectId}/agents`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ kind: 'browser', name: 'Loom Extension' }),
  });
  if (!resp.ok) {
    throw new Error(`Loom API ${resp.status}: ${await resp.text()}`);
  }
  const agent = await resp.json();
  await Storage.setCredentials(agent.agent_id, agent.api_key);
  await Storage.setProjectCredentials(projectId, agent.agent_id, agent.api_key);
  return agent;
}

async function storeAccountIdentity(data) {
  const existing = await Storage.getAccount();
  if (existing?.user?.id && existing.user.id !== data.user.id) {
    await Storage.clearAccount();
  }
  await Storage.setAccount(data.session_token, data.user);
}

async function projectAuthHeaders(projectId) {
  const credentials = await Storage.getProjectCredentials(projectId);
  if (!credentials?.api_key) {
    throw new Error('No browser credential is stored for this project. Reconnect it.');
  }
  return { Authorization: `Bearer ${credentials.api_key}` };
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

  async GET_ACCOUNT() {
    const account = await Storage.getAccount();
    const credentials = await Storage.getCredentials();
    return { account, legacyConnected: Boolean(credentials?.api_key) };
  },

  async GOOGLE_AUTH() {
    if (LOOM_CONFIG.GOOGLE_OAUTH_CLIENT_ID.indexOf('REPLACE_WITH_') === 0) {
      throw new Error('Google sign-in is not configured in this extension build.');
    }
    const authResult = await chrome.identity.getAuthToken({
      interactive: true,
      scopes: ['openid', 'email', 'profile'],
    });
    const accessToken = typeof authResult === 'string' ? authResult : authResult?.token;
    if (!accessToken) throw new Error('Google did not return an access token.');
    const resp = await fetch(`${API}/v1/auth/google/exchange`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_kind: 'extension',
        access_token: accessToken,
      }),
    });
    try {
      if (!resp.ok) throw await responseError(resp);
      const data = await resp.json();
      await storeAccountIdentity(data);
      return data;
    } finally {
      await chrome.identity.removeCachedAuthToken({ token: accessToken }).catch(function () {});
    }
  },

  async LOGOUT() {
    const account = await Storage.getAccount();
    if (account?.session_token) {
      await fetch(`${API}/v1/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${account.session_token}` },
      });
    }
    await Storage.clearAccount();
    return { ok: true };
  },

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

  async GET_PROJECT_CREDENTIALS(msg) {
    const existing = await Storage.getProjectCredentials(msg.projectId);
    if (existing?.api_key) {
      const verification = await fetch(`${API}/v1/projects/${msg.projectId}`, {
        headers: { Authorization: `Bearer ${existing.api_key}` },
      });
      if (verification.ok) return existing;
      await Storage.removeProjectCredentials(msg.projectId);
    }

    const account = await Storage.getAccount();
    if (account?.session_token) {
      return enrollBrowserAgent(msg.projectId, account.session_token);
    }

    const credentials = await Storage.getCredentials();
    if (credentials?.api_key) {
      const resp = await fetch(`${API}/v1/projects/${msg.projectId}`, {
        headers: { Authorization: `Bearer ${credentials.api_key}` },
      });
      if (resp.ok) {
        await Storage.setProjectCredentials(
          msg.projectId,
          credentials.agent_id || '',
          credentials.api_key,
        );
        return credentials;
      }
    }
    throw new Error('Enter this project’s Loom API key before linking.');
  },

  async CONNECT_PROJECT(msg) {
    const resp = await fetch(`${API}/v1/projects/${msg.projectId}`, {
      headers: { Authorization: `Bearer ${msg.apiKey}` },
    });
    if (!resp.ok) {
      throw new Error('Project ID and Loom API key do not match.');
    }
    const project = await resp.json();
    await Storage.setCredentials('', msg.apiKey);
    await Storage.setProjectCredentials(msg.projectId, '', msg.apiKey);
    return project;
  },

  /**
   * LINK_CHAT — Link a chat URL to a project.
   */
  async LINK_CHAT(msg) {
    const data = await api(`/v1/projects/${msg.projectId}/link/chat`, {
      method: 'POST',
      headers: await projectAuthHeaders(msg.projectId),
      body: {
        chat_url: msg.chatUrl,
        title: msg.title || '',
        platform: msg.platform || '',
      },
    });

    // Persist the link locally and save project api_key credentials
    if (data.chat_url) {
      await Storage.setChatLink(
        data.chat_url,
        msg.projectId,
        msg.projectName,
      );
    }

    return data;
  },

  /**
   * GET_AGENT_PRESENCE — Fetch active agents for a project.
   * Called by the popup on an interval while open.
   */
  async GET_AGENT_PRESENCE(msg) {
    const data = await api(`/v1/projects/${msg.projectId}/agents/presence`, {
      headers: await projectAuthHeaders(msg.projectId),
    });
    return { agents: data };
  },

  /**
   * GET_CONFLICTS — Fetch pending conflicts for a project.
   * Called by the popup on an interval while open.
   */
  async GET_CONFLICTS(msg) {
    const data = await api(`/v1/projects/${msg.projectId}/conflicts`, {
      headers: await projectAuthHeaders(msg.projectId),
    });
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
      console.warn('[Loom] Cannot sync — chat not linked to any project:', msg.chatUrl);
      return { synced: 0 };
    }
    let synced = 0;
    let queued = 0;
    for (const message of msg.messages) {
      try {
        await syncMessage(msg.chatUrl, message, linkInfo);
        synced++;
      } catch (err) {
        await Storage.enqueuePendingSync(msg.chatUrl, message);
        queued++;
        console.warn('[Loom] Sync queued for retry:', err.message);
      }
    }
    return { synced: synced, queued: queued };
  },

  async GET_SYNC_STATUS() {
    const queue = await Storage.getPendingSync();
    return { pending: queue.length };
  },
};

// ── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Generate a deterministic UUID for idempotent sync.
 * Uses SHA-256 over a stable message identity, formatted as UUID v4-like.
 * Deterministic: same inputs always produce same UUID.
 */
async function generateClientUuid(chatUrl, index, projectId = '') {
  // Keep the original format as the first attempt so existing captures remain
  // idempotent. The project-scoped v2 format is used only when the legacy key
  // belongs to another project.
  const prefix = projectId ? `v2:${projectId}:` : '';
  const str = `${prefix}${chatUrl}:${index}`;
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

async function syncMessage(chatUrl, message, linkInfo) {
  const headers = linkInfo.apiKey
    ? { Authorization: 'Bearer ' + linkInfo.apiKey }
    : {};
  const normalizedUrl = LoomShared.normalizeChatUrl(chatUrl);
  const identity = LoomShared.messageIdentity(chatUrl, message);

  async function writeWithUuid(clientUuid) {
    return api(`/v1/projects/${linkInfo.projectId}/context`, {
      method: 'POST',
      headers: headers,
      body: {
        client_uuid: clientUuid,
        type: 'message',
        content: `${message.role === 'user' ? 'User' : 'AI'}: ${message.content}`,
        trust_tier: message.role === 'user' ? 'user' : 'agent',
        version: 1,
        source_url: chatUrl,
      },
    });
  }

  const legacyUuid = await generateClientUuid(normalizedUrl, identity);
  try {
    return await writeWithUuid(legacyUuid);
  } catch (err) {
    if (!String(err.message || err).includes('IDEMPOTENCY_KEY_REUSED')) throw err;
    const projectUuid = await generateClientUuid(
      normalizedUrl,
      identity,
      linkInfo.projectId,
    );
    return writeWithUuid(projectUuid);
  }
}

async function flushPendingSync() {
  const queue = await Storage.getPendingSync();
  if (queue.length === 0) return;

  const remaining = [];
  for (const item of queue) {
    const linkInfo = await Storage.getProjectForChat(item.chatUrl);
    if (!linkInfo) {
      remaining.push(item);
      continue;
    }
    try {
      await syncMessage(item.chatUrl, item.message, linkInfo);
    } catch (err) {
      item.attempts = (item.attempts || 0) + 1;
      item.lastError = err.message;
      remaining.push(item);
    }
  }
  await Storage.replacePendingSync(remaining);
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
    flushPendingSync();
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
        headers: await projectAuthHeaders(project.projectId),
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

    const data = await api(`/v1/projects/${project.projectId}/conflicts`, {
      headers: await projectAuthHeaders(project.projectId),
    });
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
