---
title: "Phase 2.5a — Agent Activity Sidebar + Conflict Badge Execution Plan"
description: "Extension-side changes to add a live agent activity panel and conflict badge. All backend endpoints already exist — this is purely an extension upgrade."
status: planned
dependencies: ["phase-2/04-live-presence.md", "phase-1/11-browser-extension-core.md"]
---

# Phase 2.5a — Agent Activity Sidebar + Conflict Badge

## Overview

Upgrade the Loom browser extension from one-tap linking to a bidirectional bridge awareness layer — the extension now shows *what's happening on the server side* without leaving the browser.

**What this is NOT:** This is not the full bidirectional bridge (WebSocket, push-to-loom, dashboard). That's Phase 2.5b/c. This is purely the "read from server" half: agent presence + conflict visibility.

### Existing Backend Endpoints (already built, ready to consume)

| Endpoint | Response Fields |
|---|---|
| `GET /v1/projects/{project_id}/agents/presence` | `agent_id`, `status`, `task`, `last_heartbeat`, `last_write`, `last_write_type` |
| `GET /v1/projects/{project_id}/conflicts` | `id`, `context_unit_id`, `conflict_type`, `resolution`, `created_at`, `branch_id` |

### What Gets Built

1. **Collapsible activity panel** in the popup — shows live agent presence, status, and recent writes
2. **Conflict badge** on the extension icon — count of pending conflicts, updated via background alarm
3. **Conflict list** inside the activity panel — type, age, and count

---

## Prerequisites

| # | Item | Check |
|---|---|---|
| P0 | Extension loads without errors (existing Phase 1.11 code) | ✅ Verified |
| P1 | Backend `/v1/projects/{project_id}/agents/presence` endpoint exists | ✅ User-confirmed |
| P2 | Backend `/v1/projects/{project_id}/conflicts` endpoint exists | ✅ User-confirmed |
| P3 | `chrome.alarms` API available (MV3) | ✅ Standard MV3 API |

---

## Subtask Index

| ID | Name | Est. Time | Depends On |
|---|---|---|---|
| **A** | **Config & Permissions** | | |
| A1 | Add `alarms` permission to manifest.json | 2 min | — |
| A2 | Add polling constants and storage key to config.js | 5 min | — |
| **B** | **Storage Layer** | | |
| B1 | Add `getCurrentProject` / `setCurrentProject` / `clearCurrentProject` to storage.js | 8 min | A2 |
| **C** | **Background Service Worker** | | |
| C1 | Add `GET_AGENT_PRESENCE` and `GET_CONFLICTS` message handlers | 10 min | B1 |
| C2 | Add `SET_CURRENT_PROJECT` message handler | 5 min | B1 |
| C3 | Add `chrome.alarms`-based conflict polling with badge updates | 15 min | A1, B1 |
| **D** | **Popup — HTML** | | |
| D1 | Add activity panel HTML structure to popup.html | 10 min | — |
| D2 | Add CSS styles for agent cards, conflict items, status dots, relative timestamps | 15 min | — |
| **E** | **Popup — JS** | | |
| E1 | Add agent presence polling (5s interval) and render logic | 20 min | C1, D1, D2 |
| E2 | Add conflict polling (30s interval) and render logic | 15 min | C1, D1, D2 |
| E3 | Add panel collapse/expand toggle, relative-time ticker (1s interval), cleanup | 10 min | E1, E2 |
| **F** | **Integration** | | |
| F1 | Wire current-project storage into link/unlink flow | 8 min | B1, C2 |
| **G** | **Verify** | | |
| G1 | Load extension, verify no console errors, test all flows | 15 min | All above |

**Total estimated time: ~2 hours**

---

## Dependency Graph

```
A1 ──┐
     ├──→ C3
A2 ──┼──→ B1 ──→ C1 ──→ E1 ──→ E3
     │        └──→ C2 ──→ F1      │
     │              │              │
     └──→ D1 ──────→ E2 ──────────┤
          │                       │
          D2 ─────────────────────┤
                                 │
                          G1 ←───┘
```

---

## A1 — Add `alarms` permission to manifest.json

### File
- **MODIFY** `extension/manifest.json`

### Change

Add `"alarms"` to the `permissions` array:

```json
"permissions": [
  "storage",
  "scripting",
  "alarms"
]
```

### Acceptance
- [ ] Extension loads without "permission missing" error
- [ ] `chrome.alarms.create()` is callable from background.js

---

## A2 — Add polling constants and storage key to config.js

### File
- **MODIFY** `extension/config.js`

### Changes

Add two new sections inside `LOOM_CONFIG`:

```javascript
/** Polling intervals for real-time data. */
POLL_INTERVALS: {
  /** How often the popup polls agent presence (ms). */
  AGENT_PRESENCE_POPUP_MS: 5_000,
  /** How often the popup polls conflict list (ms). */
  CONFLICT_POPUP_MS: 30_000,
  /** How often the background alarm fires for conflict polling (minutes). */
  CONFLICT_BG_ALARM_MINUTES: 1,
},

/** Add to existing STORAGE_KEYS object. */
STORAGE_KEYS: {
  CHAT_LINKS: 'loom_chat_links',
  AGENT_CREDENTIALS: 'loom_credentials',
  /** Project ID to use for background polling. Updated by popup on link/unlink. */
  CURRENT_PROJECT: 'loom_current_project',
},
```

### Full modified file after change

```javascript
const LOOM_CONFIG = {
  LOOM_SERVER_URL: 'http://localhost:8000',
  DEFAULT_API_KEY: 'a7318f8c-e1d8-4d94-b6be-ab58aa17640e',

  SUPPORTED_PLATFORMS: [
    { hostname: 'claude.ai',   name: 'Claude.ai' },
    { hostname: 'chatgpt.com', name: 'ChatGPT' },
  ],

  SYNC_INTERVAL_MS: 5_000,
  MAX_BATCH_SIZE: 20,

  POLL_INTERVALS: {
    AGENT_PRESENCE_POPUP_MS: 5_000,
    CONFLICT_POPUP_MS: 30_000,
    CONFLICT_BG_ALARM_MINUTES: 1,
  },

  STORAGE_KEYS: {
    CHAT_LINKS: 'loom_chat_links',
    AGENT_CREDENTIALS: 'loom_credentials',
    CURRENT_PROJECT: 'loom_current_project',
  },
};
```

### Acceptance
- [ ] `LOOM_CONFIG.POLL_INTERVALS` is accessible and contains all three keys
- [ ] `LOOM_CONFIG.STORAGE_KEYS.CURRENT_PROJECT` equals `'loom_current_project'`

---

## B1 — Add current-project storage methods to storage.js

### File
- **MODIFY** `extension/storage.js`

### Changes

Add three new methods to the `Storage` object:

```javascript
/**
 * Get the last active project (used by background alarm for conflict polling).
 * @returns {Promise<{projectId: string, projectName: string}|null>}
 */
async getCurrentProject() {
  const key = LOOM_CONFIG.STORAGE_KEYS.CURRENT_PROJECT;
  const result = await chrome.storage.local.get(key);
  return result[key] || null;
},

/**
 * Store the last active project.
 * @param {string} projectId
 * @param {string} [projectName]
 */
async setCurrentProject(projectId, projectName) {
  const key = LOOM_CONFIG.STORAGE_KEYS.CURRENT_PROJECT;
  await chrome.storage.local.set({
    [key]: { projectId, projectName: projectName || projectId },
  });
},

/**
 * Clear the stored current project (on unlink).
 */
async clearCurrentProject() {
  const key = LOOM_CONFIG.STORAGE_KEYS.CURRENT_PROJECT;
  await chrome.storage.local.remove(key);
},
```

### Acceptance
- [ ] `Storage.getCurrentProject()` returns `null` when no project stored
- [ ] `Storage.setCurrentProject('proj-1', 'My Project')` stores the object
- [ ] `Storage.getCurrentProject()` returns the stored object after set
- [ ] `Storage.clearCurrentProject()` removes the stored object
- [ ] `getCurrentProject()` returns `null` after clear

---

## C1 — Add `GET_AGENT_PRESENCE` and `GET_CONFLICTS` message handlers

### File
- **MODIFY** `extension/background.js`

### Changes

Register two new message handlers in the `MESSAGE_HANDLERS` object, after the existing `LINK_CHAT` handler:

```javascript
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
```

### Placement

Add these after `LINK_CHAT` (line ~130) and before `SYNC_MESSAGES` (line ~136) in the `MESSAGE_HANDLERS` object.

### Acceptance
- [ ] Sending `{ type: 'GET_AGENT_PRESENCE', projectId: 'x' }` returns `{ agents: [...] }`
- [ ] Sending `{ type: 'GET_CONFLICTS', projectId: 'x' }` returns `{ conflicts: [...] }`
- [ ] API errors propagate as `{ error: "..." }` (existing error handling in the router)

---

## C2 — Add `SET_CURRENT_PROJECT` message handler

### File
- **MODIFY** `extension/background.js`

### Change

Add to `MESSAGE_HANDLERS`, after `GET_CONFLICTS`:

```javascript
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
```

### Acceptance
- [ ] `SET_CURRENT_PROJECT` with `projectId` stores it via `Storage.setCurrentProject`
- [ ] `SET_CURRENT_PROJECT` with `projectId: null` clears it
- [ ] Returns `{ ok: true }`

---

## C3 — Add alarm-based conflict polling with badge updates

### File
- **MODIFY** `extension/background.js`

### Changes — Add three blocks:

#### 3a. Top-level alarm listener (after `MESSAGE_HANDLERS` definition)

```javascript
// ── Conflict Alarm ──────────────────────────────────────────────────────────

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'LOOM_CONFLICT_POLL') {
    pollConflictsAndUpdateBadge();
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
      chrome.action.setBadgeBackgroundColor({ color: '#ef4444' }); // red
    } else {
      chrome.action.setBadgeText({ text: '' });
    }
  } catch (err) {
    // Don't clear badge on transient errors — stale data is better
    // than silently dropping the badge. Log and move on.
    console.warn('[Loom] Conflict poll failed:', err.message);
  }
}
```

#### 3b. Alarm registration (before the boot log)

Replace the existing boot section at the bottom of the file:

```javascript
// ── Boot ────────────────────────────────────────────────────────────────────

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
  chrome.alarms.create('LOOM_CONFLICT_POLL', {
    periodInMinutes: LOOM_CONFIG.POLL_INTERVALS.CONFLICT_BG_ALARM_MINUTES,
  });
  // Run an immediate poll on install
  setTimeout(pollConflictsAndUpdateBadge, 1000);
});

console.log('[Loom] Background service worker started');
```

### Acceptance
- [ ] Alarm `LOOM_CONFLICT_POLL` is created with `periodInMinutes: 1`
- [ ] On alarm fire, if `CURRENT_PROJECT` is set, conflicts are fetched
- [ ] Badge shows count when conflicts > 0
- [ ] Badge is cleared when conflicts = 0
- [ ] Badge is cleared when no project is stored
- [ ] No badge update on API error (stale badge preserved)
- [ ] `chrome.alarms.get` check prevents timer reset on every wakeup

---

## D1 — Add activity panel HTML to popup.html

### File
- **MODIFY** `extension/popup.html`

### Changes

#### 1. Add toggle button to the title area

Replace the existing `<h1>` line:

```html
<h1>
  <span>🔗 Loom Bridge</span>
  <button id="toggle-activity" class="icon-btn" title="Show agent activity &amp; conflicts">📊</button>
</h1>
```

#### 2. Add activity panel below the existing sections (after `</div>` of `linked-section`)

```html
<!-- ── Activity & Conflicts Panel ─────────────────────────────────────── -->
<div id="activity-panel" class="activity-panel hidden">

  <!-- Agent Activity -->
  <div class="activity-section">
    <div class="activity-section-header" id="agents-section-header">
      <span class="section-arrow">▶</span>
      <span>Agent Activity</span>
      <span class="section-badge" id="agent-count-badge">0</span>
    </div>
    <div class="activity-section-body" id="agents-list">
      <div class="activity-empty">No project linked — agent activity available after linking.</div>
    </div>
  </div>

  <!-- Conflicts -->
  <div class="activity-section">
    <div class="activity-section-header" id="conflicts-section-header">
      <span class="section-arrow">▶</span>
      <span>Conflicts</span>
      <span class="section-badge conflict-badge" id="conflict-count-badge">0</span>
    </div>
    <div class="activity-section-body" id="conflicts-list">
      <div class="activity-empty">No pending conflicts.</div>
    </div>
  </div>

</div>
```

#### 3. Load `storage.js` in the popup (needed for `Storage.getCurrentProject`)

Add before the `popup.js` script tag:

```html
<script src="config.js"></script>
<script src="storage.js"></script>
<script src="popup.js"></script>
```

### Full `<body>` structure after changes

```
body
├── h1 (title + toggle button)
├── div#status (existing)
├── div#link-section (existing, hidden when linked)
├── div#linked-section (existing, hidden when unlinked)
├── div#activity-panel (NEW, hidden by default, shown when linked)
└── scripts (config.js, storage.js NEW, popup.js)
```

### Acceptance
- [ ] Toggle button renders next to the title
- [ ] Activity panel is present in DOM but hidden by default
- [ ] Panel contains Agent Activity and Conflicts sections
- [ ] Section headers have arrow indicators and count badges
- [ ] `storage.js` is loaded before `popup.js`

---

## D2 — Add CSS styles for activity panel

### File
- **MODIFY** `extension/popup.html` (add styles inside existing `<style>` block)

### Changes

Append these styles before the closing `</style>` tag:

```css
/* ── Title Row ────────────────────────────────────────────── */
h1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
}
h1 span:first-child {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── Icon Button ──────────────────────────────────────────── */
.icon-btn {
  background: transparent;
  border: 1px solid #444;
  color: #e0e0e0;
  border-radius: 6px;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.icon-btn:hover {
  background: #0f3460;
}

/* ── Activity Panel ───────────────────────────────────────── */
.activity-panel {
  margin-top: 12px;
  border-top: 1px solid #333;
  padding-top: 8px;
}

.activity-section {
  margin-bottom: 8px;
}

.activity-section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: #16213e;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  user-select: none;
}
.activity-section-header:hover {
  background: #1a2744;
}

.section-arrow {
  font-size: 10px;
  color: #888;
  transition: transform 0.15s ease;
  width: 12px;
  text-align: center;
}
.section-arrow.expanded {
  transform: rotate(90deg);
}

.section-badge {
  margin-left: auto;
  background: #333;
  color: #ccc;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  min-width: 18px;
  text-align: center;
}
.section-badge.conflict-badge {
  background: #7f1d1d;
  color: #fca5a5;
}

.activity-section-body {
  padding: 6px 0 6px 8px;
  font-size: 12px;
}

.activity-empty {
  color: #666;
  font-style: italic;
  padding: 8px 4px;
}

/* ── Agent Card ───────────────────────────────────────────── */
.agent-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 8px;
  margin-bottom: 4px;
  background: #16213e;
  border-radius: 6px;
  border-left: 3px solid #666;
}
.agent-card.status-online  { border-left-color: #22c55e; }
.agent-card.status-idle    { border-left-color: #f59e0b; }
.agent-card.status-working { border-left-color: #3b82f6; }
.agent-card.status-blocked { border-left-color: #ef4444; }

.agent-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 12px;
  color: #e0e0e0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.online  { background: #22c55e; box-shadow: 0 0 4px #22c55e66; }
.status-dot.idle    { background: #f59e0b; }
.status-dot.working { background: #3b82f6; box-shadow: 0 0 4px #3b82f666; }
.status-dot.blocked { background: #ef4444; }
.status-dot.offline { background: #555; }

.agent-task {
  color: #aaa;
  font-size: 11px;
  margin-left: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-meta {
  display: flex;
  gap: 12px;
  margin-left: 14px;
  font-size: 10px;
  color: #777;
}
.agent-meta span {
  display: flex;
  align-items: center;
  gap: 3px;
}
.agent-meta .label {
  color: #555;
}
.agent-meta .time {
  color: #999;
}

/* ── Conflict Item ────────────────────────────────────────── */
.conflict-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  margin-bottom: 4px;
  background: #1a1a2e;
  border-radius: 6px;
  border: 1px solid #333;
  border-left: 3px solid #ef4444;
  font-size: 11px;
}
.conflict-item .conflict-type {
  font-weight: 600;
  color: #fca5a5;
}
.conflict-item .conflict-meta {
  color: #777;
  font-size: 10px;
  display: flex;
  gap: 8px;
}
```

### Acceptance
- [ ] Agent cards show colored left border based on status
- [ ] Status dots are colored correctly per status
- [ ] Section arrows rotate when expanded
- [ ] Conflict items have red left border
- [ ] Conflict badge has red background
- [ ] Empty state text is italic and gray
- [ ] Panel fits within 320px width without overflow

---

## E1 — Add agent presence polling and render logic to popup.js

### File
- **MODIFY** `extension/popup.js`

### Changes

#### 1. Add element references at the top (after existing `const` declarations)

```javascript
// Activity panel elements
const toggleActivityBtn = document.getElementById('toggle-activity');
const activityPanel = document.getElementById('activity-panel');
const agentsList = document.getElementById('agents-list');
const agentCountBadge = document.getElementById('agent-count-badge');
const agentsSectionHeader = document.getElementById('agents-section-header');
const conflictsList = document.getElementById('conflicts-list');
const conflictCountBadge = document.getElementById('conflict-count-badge');
const conflictsSectionHeader = document.getElementById('conflicts-section-header');
```

#### 2. Add state variables (after existing `let` declarations)

```javascript
let agentsPollInterval = null;
let conflictsPollInterval = null;
let timeTickerInterval = null;
let agentsSectionExpanded = true;
let conflictsSectionExpanded = true;
let cachedAgents = [];
let cachedConflicts = [];
```

#### 3. After the existing `setStatus` / `showError` / `hideError` helpers, add render helpers

```javascript
// ── Agent Activity Rendering ──────────────────────────────────────────────

function renderAgents(agents) {
  cachedAgents = agents || [];
  const count = cachedAgents.length;
  agentCountBadge.textContent = count;

  if (count === 0) {
    agentsList.innerHTML = '<div class="activity-empty">No active agents.</div>';
    return;
  }

  let html = '';
  for (const agent of agents) {
    const status = agent.status || 'offline';
    const task = agent.task || '';
    const lastHeartbeat = agent.last_heartbeat
      ? relativeTime(agent.last_heartbeat)
      : '—';
    const lastWrite = agent.last_write
      ? relativeTime(agent.last_write)
      : '—';
    const lastWriteType = agent.last_write_type || '';
    const agentLabel = agent.agent_id
      ? agent.agent_id.length > 16
        ? agent.agent_id.slice(0, 16) + '…'
        : agent.agent_id
      : 'Unknown';

    html += `
      <div class="agent-card status-${status}">
        <div class="agent-name">
          <span class="status-dot ${status}"></span>
          <span>${escapeHtml(agentLabel)}</span>
        </div>
        ${task ? `<div class="agent-task">${escapeHtml(task)}</div>` : ''}
        <div class="agent-meta">
          <span>
            <span class="label">HB:</span>
            <span class="time" data-timestamp="${agent.last_heartbeat || ''}">${lastHeartbeat}</span>
          </span>
          ${lastWriteType ? `
          <span>
            <span class="label">Write:</span>
            <span class="time" data-timestamp="${agent.last_write || ''}">${lastWrite}</span>
            <span style="color:#888;">(${escapeHtml(lastWriteType)})</span>
          </span>
          ` : ''}
        </div>
      </div>`;
  }
  agentsList.innerHTML = html;
}

// ── Conflict Rendering ────────────────────────────────────────────────────

function renderConflicts(conflicts) {
  cachedConflicts = conflicts || [];
  const count = cachedConflicts.length;
  conflictCountBadge.textContent = count;

  if (count === 0) {
    conflictsList.innerHTML = '<div class="activity-empty">No pending conflicts.</div>';
    return;
  }

  let html = '';
  for (const conflict of conflicts) {
    const created = conflict.created_at
      ? relativeTime(conflict.created_at)
      : '—';
    const type = conflict.conflict_type || 'unknown';

    html += `
      <div class="conflict-item">
        <div class="conflict-type">⚠️ ${escapeHtml(type)}</div>
        <div class="conflict-meta">
          <span>Created: ${created}</span>
          ${conflict.context_unit_id
            ? `<span style="color:#555;">ID: ${escapeHtml(conflict.context_unit_id.slice(0, 8))}…</span>`
            : ''}
        </div>
      </div>`;
  }
  conflictsList.innerHTML = html;
}
```

#### 4. Add helper functions

```javascript
// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * Convert an ISO 8601 timestamp to a relative time string.
 * Examples: "3s ago", "5m ago", "2h ago", "3d ago"
 */
function relativeTime(isoString) {
  if (!isoString) return '—';
  const then = new Date(isoString).getTime();
  if (isNaN(then)) return '—';
  const now = Date.now();
  const diffMs = now - then;
  if (diffMs < 0) return 'just now';
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return seconds + 's ago';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + 'm ago';
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + 'h ago';
  const days = Math.floor(hours / 24);
  return days + 'd ago';
}

/**
 * Minimal HTML entity escape.
 */
function escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
```

#### 5. Add polling functions

```javascript
// ── Polling ────────────────────────────────────────────────────────────────

async function fetchAgentPresence() {
  if (!currentlyLinkedProjectId) return;
  try {
    const resp = await chrome.runtime.sendMessage({
      type: 'GET_AGENT_PRESENCE',
      projectId: currentlyLinkedProjectId,
    });
    if (!resp?.error) {
      renderAgents(resp?.agents || []);
    }
  } catch (err) {
    console.warn('[Loom] Agent presence poll failed:', err.message);
  }
}

async function fetchConflicts() {
  if (!currentlyLinkedProjectId) return;
  try {
    const resp = await chrome.runtime.sendMessage({
      type: 'GET_CONFLICTS',
      projectId: currentlyLinkedProjectId,
    });
    if (!resp?.error) {
      renderConflicts(resp?.conflicts || []);
    }
  } catch (err) {
    console.warn('[Loom] Conflict poll failed:', err.message);
  }
}

/**
 * Refresh all displayed relative timestamps without re-fetching.
 */
function refreshRelativeTimes() {
  // Update agent heartbeat/write timestamps
  document.querySelectorAll('.agent-meta .time[data-timestamp]').forEach(el => {
    const ts = el.getAttribute('data-timestamp');
    el.textContent = relativeTime(ts);
  });
  // Update conflict created times
  // Conflicts use inline text, so we re-render to keep it simple
  // (this is cheap because we use cached data)
  if (cachedConflicts.length > 0) {
    renderConflicts(cachedConflicts);
  }
}

function startPolling() {
  stopPolling();
  fetchAgentPresence();
  fetchConflicts();
  agentsPollInterval = setInterval(fetchAgentPresence, LOOM_CONFIG.POLL_INTERVALS.AGENT_PRESENCE_POPUP_MS);
  conflictsPollInterval = setInterval(fetchConflicts, LOOM_CONFIG.POLL_INTERVALS.CONFLICT_POPUP_MS);
  timeTickerInterval = setInterval(refreshRelativeTimes, 1000);
}

function stopPolling() {
  if (agentsPollInterval) { clearInterval(agentsPollInterval); agentsPollInterval = null; }
  if (conflictsPollInterval) { clearInterval(conflictsPollInterval); conflictsPollInterval = null; }
  if (timeTickerInterval) { clearInterval(timeTickerInterval); timeTickerInterval = null; }
}
```

#### 6. Add section toggle handlers

```javascript
// ── Section Toggle ─────────────────────────────────────────────────────────

agentsSectionHeader.addEventListener('click', () => {
  agentsSectionExpanded = !agentsSectionExpanded;
  const arrow = agentsSectionHeader.querySelector('.section-arrow');
  const body = agentsList;
  body.style.display = agentsSectionExpanded ? '' : 'none';
  arrow.classList.toggle('expanded', agentsSectionExpanded);
});

conflictsSectionHeader.addEventListener('click', () => {
  conflictsSectionExpanded = !conflictsSectionExpanded;
  const arrow = conflictsSectionHeader.querySelector('.section-arrow');
  const body = conflictsList;
  body.style.display = conflictsSectionExpanded ? '' : 'none';
  arrow.classList.toggle('expanded', conflictsSectionExpanded);
});
```

---

## E2 — Add conflict polling (reuses functions from E1)

This subtask is merged into E1 — the `fetchConflicts` and `renderConflicts` functions are defined in E1 along with the polling infrastructure. No separate file changes needed.

---

## E3 — Add panel toggle, relative-time ticker, cleanup

### File
- **MODIFY** `extension/popup.js`

### Changes — Add toggle handler and wire everything together

#### 1. Panel toggle handler

```javascript
// ── Activity Panel Toggle ──────────────────────────────────────────────────

toggleActivityBtn.addEventListener('click', () => {
  const isHidden = activityPanel.classList.toggle('hidden');
  toggleActivityBtn.textContent = isHidden ? '📊' : '📋';
  toggleActivityBtn.title = isHidden
    ? 'Show agent activity & conflicts'
    : 'Hide activity panel';
});
```

#### 2. Wire into existing flow

In the `DOMContentLoaded` handler, after a link is confirmed (the `resp.linked === true` branch), add:

```javascript
// Show activity panel and start polling
showActivityPanel(resp.projectId, resp.projectName);
```

And add this function:

```javascript
async function showActivityPanel(projectId, projectName) {
  currentlyLinkedProjectId = projectId;
  activityPanel.classList.remove('hidden');
  toggleActivityBtn.textContent = '📋';
  toggleActivityBtn.title = 'Hide activity panel';

  // Sync current project to background for alarm-based polling
  await chrome.runtime.sendMessage({
    type: 'SET_CURRENT_PROJECT',
    projectId,
    projectName,
  });

  // Start all polling intervals
  startPolling();
}
```

#### 3. Cleanup on unlink

In the `unlinkBtn` click handler, before `window.location.reload()`:

```javascript
stopPolling();
await chrome.runtime.sendMessage({
  type: 'SET_CURRENT_PROJECT',
  projectId: null,
});
```

### Acceptance
- [ ] Toggle button shows/hides the activity panel
- [ ] Button icon changes between 📊 and 📋
- [ ] Polling starts when panel becomes visible (linked state)
- [ ] Polling stops on unlink
- [ ] Relative timestamps update every second
- [ ] No intervals leak when popup closes (browser handles this, but `stopPolling` is wired)

---

## F1 — Wire current-project storage into link/unlink flow

### File
- **MODIFY** `extension/popup.js`

### Changes

#### 1. In the `linkBtn` click handler (after linking succeeds)

After this block (around line 172-178):
```javascript
if (result && result.id) {
```

Add the `SET_CURRENT_PROJECT` call after the content script notification:

```javascript
// Store as current project for background alarm polling
await chrome.runtime.sendMessage({
  type: 'SET_CURRENT_PROJECT',
  projectId,
  projectName,
});
```

#### 2. In the `unlinkBtn` click handler

Already covered in E3 — add the `SET_CURRENT_PROJECT null` call and `stopPolling()` before reload.

### Acceptance
- [ ] After linking a chat, background worker stores the project
- [ ] After unlinking, background worker clears the stored project
- [ `Storage.getCurrentProject()` returns correct value after each action

---

## G1 — Verify

### Procedure

1. **Load extension** in Chrome via `chrome://extensions` → Load unpacked → select `extension/`
2. **Check console** — open service worker console, look for `[Loom] Background service worker started`
3. **Verify alarm** — run `chrome.alarms.getAll()` in service worker console → should see `LOOM_CONFLICT_POLL`
4. **Open popup** on a supported chat page (Claude.ai):
   - Verify popup renders with toggle button
   - Link a project → verify activity panel appears
   - Verify agent presence data renders (status dots, tasks, timestamps)
   - Verify conflict count badge on icon
   - Verify conflict list in popup
5. **Wait 60s** — verify badge updates via background alarm (check service worker console logs)
6. **Unlink** — verify panel hides, polling stops, badge clears
7. **Test without server** — stop the Loom server, verify graceful degradation (error states, no crashes)

### Acceptance Checklist

- [ ] Extension loads without manifest or runtime errors
- [ ] Alarm `LOOM_CONFLICT_POLL` is registered
- [ ] No new permissions requested beyond `alarms`
- [ ] Popup shows activity panel when a project is linked
- [ ] Agent list shows agent_id, status dot, task, heartbeat, last write
- [ ] Relative timestamps refresh every second
- [ ] Conflict list shows count, type, created time
- [ ] Extension badge shows conflict count (red background)
- [ ] Badge clears when no conflicts
- [ ] Badge clears when no project linked
- [ ] Polling stops cleanly on unlink
- [ ] All existing functionality (link, unlink, sync) still works
- [ ] No console errors on any code path

---

## Risks and Edge Cases

| Risk | Impact | Mitigation |
|---|---|---|
| **Presence endpoint returns different fields than expected** | Agent cards may show blank fields or "—" for missing data | Render logic handles missing fields gracefully via `|| '—'` and conditional sections |
| **Conflict endpoint returns 0 items vs error** | Badge shows 0 vs gets cleared | Only clear badge on explicit 0 count; errors preserve stale badge |
| **Service worker killed before alarm fires** | Badge not updated for up to 60s | This is expected MV3 behavior — next alarm wake fixes it |
| **Multiple projects linked simultaneously** | Background alarm only polls the "last active" project | `SET_CURRENT_PROJECT` updates on every popup open & link → the most relevant project is used |
| **Rapid popup open/close cycles** | Multiple polling intervals for same popup | `stopPolling()` is called at the start of `startPolling()` to prevent duplicates |
| **Relative time with clock skew** | "just now" or negative times | `diffMs < 0` returns `"just now"` — not a real problem for browser-to-server sync |
| **Long agent IDs overflow 320px popup** | Text overflow or horizontal scroll | Agent IDs truncated to 16 chars with `…`; `word-break` not needed with truncation |
| **`chrome.alarms.create` called on every wakeup** | Alarm timer constantly reset | `chrome.alarms.get` check prevents creation if alarm already exists; `onInstalled` only fires once |

---

## File Change Summary

| File | Action | Nature of Changes |
|---|---|---|
| `extension/manifest.json` | **MODIFY** | Add `"alarms"` to permissions array |
| `extension/config.js` | **MODIFY** | Add `POLL_INTERVALS` object, add `CURRENT_PROJECT` to `STORAGE_KEYS` |
| `extension/storage.js` | **MODIFY** | Add `getCurrentProject()`, `setCurrentProject()`, `clearCurrentProject()` methods |
| `extension/background.js` | **MODIFY** | Add 3 message handlers (`GET_AGENT_PRESENCE`, `GET_CONFLICTS`, `SET_CURRENT_PROJECT`), add alarm listener + `pollConflictsAndUpdateBadge()`, update boot section with alarm registration |
| `extension/popup.html` | **MODIFY** | Add toggle button in title, add activity panel HTML, add `storage.js` script tag, add ~150 lines of CSS |
| `extension/popup.js` | **MODIFY** | Add agent rendering, conflict rendering, polling intervals, relative time helpers, section toggle, panel toggle, link/unlink wiring |

No new files created. All changes are surgical modifications to existing files.

---

## Execution Order

```
A1 ─── A2 ─── B1 ─── C1 ───┐
                            ├──→ E1 ─── E3 ─── G1
C2 ─── C3 ─────────────────┤         │
                            │         │
D1 ─── D2 ─────────────────┤         │
                            │         │
F1 ────────────────────────┘         │
                                     │
G1 ←─────────────────────────────────┘
```

### Suggested execution sequence:
1. **A1** — `manifest.json` (trivial, unblocks C3)
2. **A2** — `config.js` (trivial, unblocks B1)
3. **B1** — `storage.js` (unblocks C1, C2)
4. **C1** — Add `GET_AGENT_PRESENCE` + `GET_CONFLICTS` handlers to `background.js`
5. **C2** — Add `SET_CURRENT_PROJECT` handler to `background.js`
6. **C3** — Add alarm listener + badge logic + boot registration to `background.js`
7. **D1** — Add HTML structure to `popup.html`
8. **D2** — Add CSS to `popup.html`
9. **E1** — Add agent rendering + conflict rendering + polling + helpers to `popup.js`
10. **E3** — Add panel toggle + section toggle + polling wiring to `popup.js`
11. **F1** — Wire current-project storage into existing link/unlink handlers
12. **G1** — Manual verification in Chrome
