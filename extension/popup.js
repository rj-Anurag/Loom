/**
 * Loom Extension — Popup Logic
 *
 * Handles the one-tap linking UI: checks current tab, fetches project list,
 * links chat to selected project, or creates a new project.
 */

(function () {
  'use strict';

  const statusEl = document.getElementById('status');
  const statusText = document.getElementById('status-text');
  const linkSection = document.getElementById('link-section');
  const linkedSection = document.getElementById('linked-section');
  const projectSelect = document.getElementById('project-select');
  const projectIdInput = document.getElementById('project-id-input');
  const linkBtn = document.getElementById('link-btn');
  const errorMsg = document.getElementById('error-msg');
  const linkedProjectName = document.getElementById('linked-project-name');
  const unlinkBtn = document.getElementById('unlink-btn');
  const dashboardBtn = document.getElementById('dashboard-btn');

  let currentTabUrl = '';
  let currentlyLinkedProjectId = null;

  // Activity panel elements
  const toggleActivityBtn = document.getElementById('toggle-activity');
  const activityPanel = document.getElementById('activity-panel');
  const agentsList = document.getElementById('agents-list');
  const agentCountBadge = document.getElementById('agent-count-badge');
  const agentsSectionHeader = document.getElementById('agents-section-header');

  // Polling state
  let agentsPollInterval = null;
  let timeTickerInterval = null;
  let agentsSectionExpanded = true;
  let cachedAgents = [];

  // ── Initialisation ──────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', async () => {
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tab = tabs[0];
      if (!tab || !tab.url) {
        setStatus('No active tab found.', 'error');
        return;
      }

      currentTabUrl = tab.url.split('?')[0];

      if (!isSupportedPlatform(currentTabUrl)) {
        setStatus('Open a Claude.ai or ChatGPT chat to link it.', 'error');
        return;
      }

      // Check if already linked
      const resp = await chrome.runtime.sendMessage({
        type: 'CHECK_LINK',
        chatUrl: currentTabUrl,
      });

      if (resp && resp.linked) {
        currentlyLinkedProjectId = resp.projectId;
        linkedProjectName.textContent = resp.projectName || resp.projectId;
        linkedSection.classList.remove('hidden');
        linkSection.classList.add('hidden');
        setStatus(`Linked to ${resp.projectName || resp.projectId}`, 'linked');
        // Show activity panel and start polling
        showActivityPanel(resp.projectId, resp.projectName);
      } else {
        // Show link UI
        linkedSection.classList.add('hidden');
        linkSection.classList.remove('hidden');
        setStatus('Not linked to any project', 'unlinked');
        await loadProjects();
      }
    } catch (err) {
      setStatus('Could not connect to Loom. Is the server running?', 'error');
      console.error('[Loom] Popup init error:', err);
    }
  });

  // ── Platform detection ──────────────────────────────────────────────────

  function isSupportedPlatform(url) {
    try {
      const hostname = new URL(url).hostname;
      return LOOM_CONFIG.SUPPORTED_PLATFORMS.some(p => hostname === p.hostname);
    } catch {
      return false;
    }
  }

  // ── Status display ──────────────────────────────────────────────────────

  function setStatus(text, type) {
    statusText.textContent = text;
    statusEl.className = 'status ' + (type || '');
  }

  function showError(text) {
    errorMsg.textContent = text;
    errorMsg.classList.remove('hidden');
  }

  function hideError() {
    errorMsg.classList.add('hidden');
  }

  // ── Agent Activity Rendering ──────────────────────────────────────────────

  function renderAgents(agents) {
    cachedAgents = agents || [];
    const count = cachedAgents.length;
    agentCountBadge.textContent = count;

    if (count === 0) {
      agentsList.innerHTML = '<div class="activity-empty">No active agents.</div>';
      return;
    }

    // Whitelist of allowed status values for CSS class safety
    var ALLOWED_STATUSES = { 'online': true, 'idle': true, 'working': true, 'blocked': true, 'offline': true };

    var html = '';
    for (var i = 0; i < agents.length; i++) {
      var agent = agents[i];
      var status = ALLOWED_STATUSES[agent.status] ? agent.status : 'offline';
      var task = agent.task || '';
      var lastHeartbeat = agent.last_heartbeat
        ? relativeTime(agent.last_heartbeat)
        : '\u2014';
      var lastWrite = agent.last_write
        ? relativeTime(agent.last_write)
        : '\u2014';
      var lastWriteType = agent.last_write_type || '';
      var agentLabel = agent.agent_id
        ? agent.agent_id.length > 16
          ? agent.agent_id.slice(0, 16) + '\u2026'
          : agent.agent_id
        : 'Unknown';

      html +=
        '<div class="agent-card status-' + status + '">' +
          '<div class="agent-name">' +
            '<span class="status-dot ' + status + '"></span>' +
            '<span>' + escapeHtml(agentLabel) + '</span>' +
          '</div>' +
          (task ? '<div class="agent-task">' + escapeHtml(task) + '</div>' : '') +
          '<div class="agent-meta">' +
            '<span>' +
              '<span class="label">HB:</span>' +
              '<span class="time" data-timestamp="' + escapeHtml(agent.last_heartbeat || '') + '">' + lastHeartbeat + '</span>' +
            '</span>' +
            (lastWriteType
              ? '<span>' +
                  '<span class="label">Write:</span>' +
                  '<span class="time" data-timestamp="' + escapeHtml(agent.last_write || '') + '">' + lastWrite + '</span>' +
                  '<span class="muted-text">(' + escapeHtml(lastWriteType) + ')</span>' +
                '</span>'
              : '') +
          '</div>' +
        '</div>';
    }
    agentsList.innerHTML = html;
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  /**
   * Convert an ISO 8601 timestamp to a relative time string.
   * Examples: "3s ago", "5m ago", "2h ago", "3d ago"
   */
  function relativeTime(isoString) {
    if (!isoString) return '\u2014';
    const then = new Date(isoString).getTime();
    if (isNaN(then)) return '\u2014';
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

  /**
   * Refresh all displayed relative timestamps without re-fetching.
   */
  function refreshRelativeTimes() {
    document.querySelectorAll('.agent-meta .time[data-timestamp]').forEach(function (el) {
      const ts = el.getAttribute('data-timestamp');
      el.textContent = relativeTime(ts);
    });
  }

  function startPolling() {
    stopPolling();
    fetchAgentPresence();
    agentsPollInterval = setInterval(fetchAgentPresence, LOOM_CONFIG.POLL_INTERVALS.AGENT_PRESENCE_POPUP_MS);
    timeTickerInterval = setInterval(refreshRelativeTimes, 1000);
  }

  function stopPolling() {
    if (agentsPollInterval) { clearInterval(agentsPollInterval); agentsPollInterval = null; }
    if (timeTickerInterval) { clearInterval(timeTickerInterval); timeTickerInterval = null; }
  }

  // ── Activity Panel ─────────────────────────────────────────────────────────

  async function showActivityPanel(projectId, projectName) {
    currentlyLinkedProjectId = projectId;
    activityPanel.classList.remove('hidden');
    toggleActivityBtn.textContent = '\uD83D\uDCCB';
    toggleActivityBtn.title = 'Hide activity panel';

    // Sync current project to background for alarm-based polling
    await chrome.runtime.sendMessage({
      type: 'SET_CURRENT_PROJECT',
      projectId: projectId,
      projectName: projectName,
    });

    // Start all polling intervals
    startPolling();
  }

  // ── Section Toggle ─────────────────────────────────────────────────────────

  agentsSectionHeader.addEventListener('click', function () {
    agentsSectionExpanded = !agentsSectionExpanded;
    const arrow = agentsSectionHeader.querySelector('.section-arrow');
    agentsList.style.display = agentsSectionExpanded ? '' : 'none';
    if (arrow) arrow.classList.toggle('expanded', agentsSectionExpanded);
  });

  // ── Activity Panel Toggle ──────────────────────────────────────────────────

  toggleActivityBtn.addEventListener('click', function () {
    const isHidden = activityPanel.classList.toggle('hidden');
    toggleActivityBtn.textContent = isHidden ? '\uD83D\uDCCA' : '\uD83D\uDCCB';
    toggleActivityBtn.title = isHidden
      ? 'Show agent activity'
      : 'Hide activity panel';
    if (isHidden) {
      stopPolling();
    } else if (currentlyLinkedProjectId) {
      startPolling();
    }
  });

  // ── Dashboard ─────────────────────────────────────────────────────────────────

  dashboardBtn.addEventListener('click', async function () {
    if (!currentlyLinkedProjectId) {
      console.warn('[Loom] No project linked — cannot open dashboard');
      return;
    }
    const creds = await Storage.getCredentials();
    const apiKey = creds ? creds.api_key : LOOM_CONFIG.DEFAULT_API_KEY;
    const path = LOOM_CONFIG.DASHBOARD_BASE_PATH.replace('{project_id}', currentlyLinkedProjectId);
    chrome.tabs.create({ url: LOOM_CONFIG.LOOM_SERVER_URL + path + '#token=' + apiKey });
  });

  // ── Load projects ───────────────────────────────────────────────────────

  async function loadProjects() {
    try {
      const resp = await chrome.runtime.sendMessage({ type: 'GET_PROJECTS' });
      if (resp?.error) {
        setStatus('Server unreachable — create a new project to start', 'error');
      } else {
        const projects = resp?.projects || [];
        projectSelect.innerHTML = '<option value="">— Select a project —</option>';
        projects.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.name;
          projectSelect.appendChild(opt);
        });
      }
    } catch (err) {
      setStatus('Server unreachable — create a new project to start', 'error');
      console.error('[Loom] Load projects error:', err);
    }
  }

  // ── Clear competing inputs on focus ──────────────────────────────────

  projectIdInput.addEventListener('focus', function () {
    projectSelect.value = '';
  });

  projectSelect.addEventListener('change', function () {
    projectIdInput.value = '';
  });

  // ── Local API helper (bypasses background worker to avoid hangs) ──────

  function authHeaders() {
    var apiKey = LOOM_CONFIG.DEFAULT_API_KEY;
    if (apiKey) {
      return { Authorization: 'Bearer ' + apiKey };
    }
    return {};
  }

  async function apiPost(path, body) {
    var url = LOOM_CONFIG.LOOM_SERVER_URL + path;
    var headers = {
      'Content-Type': 'application/json',
    };
    var ah = authHeaders();
    for (var k in ah) { if (ah.hasOwnProperty(k)) { headers[k] = ah[k]; } }

    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 8000);

    try {
      var resp = await fetch(url, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!resp.ok) {
        var text = await resp.text();
        throw new Error('Loom API ' + resp.status + ': ' + text);
      }
      return resp.json();
    } catch (err) {
      clearTimeout(timer);
      throw err;
    }
  }

  // ── Link / Create project ──────────────────────────────────────────────

  linkBtn.addEventListener('click', async () => {
    hideError();
    linkBtn.disabled = true;
    linkBtn.textContent = 'Linking...';

    try {
      let projectId = projectSelect.value;
      const directId = projectIdInput.value.trim();

      // Count how many options were provided
      const hasSelection = !!projectId;
      const hasDirectId = !!directId;
      const provided = [hasSelection, hasDirectId].filter(Boolean).length;

      if (provided === 0) {
        showError('Select a project or enter a project ID.');
        linkBtn.disabled = false;
        linkBtn.textContent = 'Link Chat';
        return;
      }

      if (provided > 1) {
        showError('Use only one option: select from the list or enter a project ID.');
        linkBtn.disabled = false;
        linkBtn.textContent = 'Link Chat';
        return;
      }

      if (hasDirectId) {
        if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(directId)) {
          showError('Project ID must be a valid UUID (e.g. 6f4f8594-9237-4609-8378-a092de7604a1).');
          linkBtn.disabled = false;
          linkBtn.textContent = 'Link Chat';
          return;
        }
        projectId = directId;
      }

      const projectName = projectId;

      // Link chat to project — direct API call (not via background worker)
      const data = await apiPost('/v1/projects/' + projectId + '/link/chat', {
        chat_url: currentTabUrl,
        title: document.title || '',
        platform: new URL(currentTabUrl).hostname,
      });

      // Store link locally
      if (data.chat_url) {
        await Storage.setChatLink(data.chat_url, projectId, projectName);
      }

      // Notify content script
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tabId = tabs[0]?.id;
      if (tabId) {
        await chrome.tabs.sendMessage(tabId, { type: 'LOOM_LINKED', projectName }).catch(function () {});
      }

      // Reload popup to show linked state
      window.location.reload();
    } catch (err) {
      showError(err.message.indexOf('abort') !== -1
        ? 'Server not responding. Is Loom running?'
        : 'Link failed: ' + err.message);
      console.error('[Loom] Link error:', err);
      linkBtn.disabled = false;
      linkBtn.textContent = 'Link Chat';
    }
  });

  // ── Unlink ──────────────────────────────────────────────────────────────

  unlinkBtn.addEventListener('click', async () => {
    if (!currentTabUrl) return;

    stopPolling();

    // Clear current project from background alarm storage
    await chrome.runtime.sendMessage({
      type: 'SET_CURRENT_PROJECT',
      projectId: null,
    });

    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    delete links[currentTabUrl];
    await chrome.storage.local.set({ [key]: links });

    window.location.reload();
  });

})();
