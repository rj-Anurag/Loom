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
  const projectKeyInput = document.getElementById('project-key-input');
  const projectNameInput = document.getElementById('project-name-input');
  const connectProjectBtn = document.getElementById('connect-project-btn');
  const createProjectBtn = document.getElementById('create-project-btn');
  const linkBtn = document.getElementById('link-btn');
  const errorMsg = document.getElementById('error-msg');
  const linkedProjectName = document.getElementById('linked-project-name');
  const unlinkBtn = document.getElementById('unlink-btn');
  const dashboardBtn = document.getElementById('dashboard-btn');
  const syncStatus = document.getElementById('sync-status');
  const accountSection = document.getElementById('account-section');
  const accountBar = document.getElementById('account-bar');
  const accountName = document.getElementById('account-name');
  const accountEmail = document.getElementById('account-email');
  const accountPassword = document.getElementById('account-password');
  const accountDisplayName = document.getElementById('account-display-name');
  const accountError = document.getElementById('account-error');
  const signupBtn = document.getElementById('signup-btn');
  const loginBtn = document.getElementById('login-btn');
  const logoutBtn = document.getElementById('logout-btn');

  let currentTabUrl = '';
  let currentTabTitle = '';
  let currentlyLinkedProjectId = null;

  // Activity panel elements
  const toggleActivityBtn = document.getElementById('toggle-activity');
  const activityPanel = document.getElementById('activity-panel');
  const agentsList = document.getElementById('agents-list');
  const agentCountBadge = document.getElementById('agent-count-badge');
  const agentsSectionHeader = document.getElementById('agents-section-header');
  const conflictsList = document.getElementById('conflicts-list');
  const conflictCountBadge = document.getElementById('conflict-count-badge');
  const conflictsSectionHeader = document.getElementById('conflicts-section-header');

  // Polling state
  let agentsPollInterval = null;
  let timeTickerInterval = null;
  let agentsSectionExpanded = true;
  let conflictsSectionExpanded = true;
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
      currentTabTitle = tab.title || '';

      if (!isSupportedPlatform(currentTabUrl)) {
        setStatus('Open a supported AI conversation to link it.', 'error');
        return;
      }

      const accountState = await chrome.runtime.sendMessage({ type: 'GET_ACCOUNT' });
      if (accountState?.account) {
        showSignedInAccount(accountState.account.user);
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
        refreshSyncStatus();
      } else {
        linkedSection.classList.add('hidden');
        if (accountState?.account || accountState?.legacyConnected) {
          linkSection.classList.remove('hidden');
          setStatus('Not linked to any project', 'unlinked');
          await loadProjects();
        } else {
          accountSection.classList.remove('hidden');
          linkSection.classList.add('hidden');
          setStatus('Create an account to start', 'unlinked');
        }
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

  function showAccountError(text) {
    const labels = {
      EMAIL_ALREADY_REGISTERED: 'This email already has an account. Choose Log in.',
      INVALID_CREDENTIALS: 'Email or password is incorrect.',
      INVALID_EMAIL: 'Enter a valid email address.',
      TOO_MANY_ATTEMPTS: 'Too many attempts. Wait a few minutes and try again.',
    };
    accountError.textContent = labels[text] || text;
    accountError.classList.remove('hidden');
  }

  function showSignedInAccount(user) {
    accountSection.classList.add('hidden');
    accountBar.classList.remove('hidden');
    accountName.textContent = user?.display_name || user?.email || 'Loom user';
  }

  async function finishAccountAuth(result) {
    if (result?.error) throw new Error(result.error);
    accountPassword.value = '';
    accountError.classList.add('hidden');
    showSignedInAccount(result.user);
    linkSection.classList.remove('hidden');
    await loadProjects();
    const projectId = result.project_id || (result.projects?.length === 1 ? result.projects[0].id : '');
    if (projectId) projectSelect.value = projectId;
    setStatus('Account connected. Select a project.', 'unlinked');
  }

  signupBtn.addEventListener('click', async function () {
    const email = accountEmail.value.trim();
    const password = accountPassword.value;
    if (!email || password.length < 8) {
      showAccountError('Enter a valid email and a password with at least 8 characters.');
      return;
    }
    signupBtn.disabled = true;
    signupBtn.textContent = 'Creating…';
    try {
      await finishAccountAuth(await chrome.runtime.sendMessage({
        type: 'SIGNUP',
        email: email,
        password: password,
        displayName: accountDisplayName.value.trim(),
      }));
    } catch (err) {
      showAccountError(err.message);
    } finally {
      signupBtn.disabled = false;
      signupBtn.textContent = 'Sign up';
    }
  });

  loginBtn.addEventListener('click', async function () {
    const email = accountEmail.value.trim();
    const password = accountPassword.value;
    if (!email || !password) {
      showAccountError('Enter your email and password.');
      return;
    }
    loginBtn.disabled = true;
    loginBtn.textContent = 'Logging in…';
    try {
      await finishAccountAuth(await chrome.runtime.sendMessage({
        type: 'LOGIN', email: email, password: password,
      }));
    } catch (err) {
      showAccountError(err.message);
    } finally {
      loginBtn.disabled = false;
      loginBtn.textContent = 'Log in';
    }
  });

  logoutBtn.addEventListener('click', async function () {
    await chrome.runtime.sendMessage({ type: 'LOGOUT' });
    window.location.reload();
  });

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

  async function fetchConflicts() {
    if (!currentlyLinkedProjectId) return;
    try {
      const resp = await chrome.runtime.sendMessage({
        type: 'GET_CONFLICTS',
        projectId: currentlyLinkedProjectId,
      });
      const conflicts = resp?.error ? [] : (resp?.conflicts || []);
      conflictCountBadge.textContent = conflicts.length;
      if (conflicts.length === 0) {
        conflictsList.innerHTML = '<div class="activity-empty">No pending conflicts.</div>';
        return;
      }
      conflictsList.innerHTML = conflicts.map(function(conflict) {
        return '<div class="conflict-item">' +
          '<div class="conflict-type">' + escapeHtml(conflict.conflict_type || 'Conflict') + '</div>' +
          '<div class="conflict-meta">' + escapeHtml(relativeTime(conflict.created_at)) + '</div>' +
          '</div>';
      }).join('');
    } catch (err) {
      console.warn('[Loom] Conflict poll failed:', err.message);
    }
  }

  async function refreshSyncStatus() {
    if (!syncStatus) return;
    const resp = await chrome.runtime.sendMessage({ type: 'GET_SYNC_STATUS' });
    const pending = resp?.pending || 0;
    syncStatus.textContent = pending > 0
      ? pending + ' message' + (pending === 1 ? '' : 's') + ' queued for retry'
      : 'All captured messages are synced';
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
    fetchConflicts();
    refreshSyncStatus();
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

  conflictsSectionHeader.addEventListener('click', function () {
    conflictsSectionExpanded = !conflictsSectionExpanded;
    const arrow = conflictsSectionHeader.querySelector('.section-arrow');
    conflictsList.style.display = conflictsSectionExpanded ? '' : 'none';
    if (arrow) arrow.classList.toggle('expanded', conflictsSectionExpanded);
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
    const projectCredentials = await Storage.getProjectCredentials(currentlyLinkedProjectId);
    const creds = await Storage.getCredentials();
    const apiKey = projectCredentials?.api_key || (creds ? creds.api_key : LOOM_CONFIG.DEFAULT_API_KEY);
    if (!apiKey) {
      showError('Project credential is missing. Log in and reconnect this conversation.');
      return;
    }
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
    projectKeyInput.value = '';
  });

  connectProjectBtn.addEventListener('click', async function () {
    hideError();
    const projectId = projectIdInput.value.trim();
    const apiKey = projectKeyInput.value.trim();
    if (!isProjectId(projectId) || !LoomShared.isLoomApiKey(apiKey)) {
      showError('Enter a valid project UUID and Loom API key.');
      return;
    }
    connectProjectBtn.disabled = true;
    connectProjectBtn.textContent = 'Verifying…';
    try {
      const project = await chrome.runtime.sendMessage({
        type: 'CONNECT_PROJECT',
        projectId: projectId,
        apiKey: apiKey,
      });
      if (project?.error) throw new Error(project.error);
      await loadProjects();
      projectSelect.value = projectId;
      projectIdInput.value = '';
      projectKeyInput.value = '';
      setStatus('Access verified for ' + (project.name || projectId), 'unlinked');
    } catch (err) {
      showError(err.message);
    } finally {
      connectProjectBtn.disabled = false;
      connectProjectBtn.textContent = 'Verify access';
    }
  });

  createProjectBtn.addEventListener('click', async function () {
    hideError();
    const name = projectNameInput.value.trim();
    if (!name) {
      showError('Enter a project name.');
      return;
    }
    createProjectBtn.disabled = true;
    createProjectBtn.textContent = 'Creating…';
    try {
      const project = await chrome.runtime.sendMessage({ type: 'CREATE_PROJECT', name: name });
      if (project?.error) throw new Error(project.error);
      await loadProjects();
      projectSelect.value = project.id;
      projectNameInput.value = '';
      setStatus('Project created. Link this conversation when ready.', 'unlinked');
    } catch (err) {
      showError(err.message);
    } finally {
      createProjectBtn.disabled = false;
      createProjectBtn.textContent = 'Create project';
    }
  });

  function isProjectId(value) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  }

  // ── Local API helper (bypasses background worker to avoid hangs) ──────

  async function authHeaders() {
    var creds = await Storage.getCredentials();
    var apiKey = creds ? creds.api_key : LOOM_CONFIG.DEFAULT_API_KEY;
    if (apiKey) {
      return { Authorization: 'Bearer ' + apiKey };
    }
    return {};
  }

  async function apiPost(path, body, apiKeyOverride) {
    var url = LOOM_CONFIG.LOOM_SERVER_URL + path;
    var headers = {
      'Content-Type': 'application/json',
    };
    var ah = apiKeyOverride
      ? { Authorization: 'Bearer ' + apiKeyOverride }
      : await authHeaders();
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

  async function startConversationSync(tabId, projectId, projectName) {
    const message = {
      type: 'LOOM_LINKED',
      projectId: projectId,
      projectName: projectName,
    };
    try {
      await chrome.tabs.sendMessage(tabId, message);
      return;
    } catch (firstError) {
      // A tab that was already open when Loom was installed has no declared
      // content script yet. Inject both shared helpers and the scanner, then
      // explicitly request the initial history scan.
      await chrome.scripting.executeScript({
        target: { tabId: tabId },
        files: ['shared.js', 'content.js'],
      });
      await chrome.tabs.sendMessage(tabId, message);
    }
  }

  linkBtn.addEventListener('click', async () => {
    hideError();
    linkBtn.disabled = true;
    linkBtn.textContent = 'Linking...';

    try {
      let projectId = projectSelect.value;
      const directId = projectIdInput.value.trim();

      projectId = LoomShared.resolveProjectChoice(projectId, directId);
      const hasSelection = projectSelect.value === projectId;
      const hasDirectId = !hasSelection && !!directId;

      if (hasDirectId) {
        if (!isProjectId(directId)) {
          showError('Project ID must be a valid UUID (e.g. 6f4f8594-9237-4609-8378-a092de7604a1).');
          linkBtn.disabled = false;
          linkBtn.textContent = 'Link conversation';
          return;
        }
        projectId = directId;
        const directKey = projectKeyInput.value.trim();
        if (directKey) {
          const connected = await chrome.runtime.sendMessage({
            type: 'CONNECT_PROJECT',
            projectId: projectId,
            apiKey: directKey,
          });
          if (connected?.error) throw new Error(connected.error);
        }
      }

      const selected = projectSelect.options[projectSelect.selectedIndex];
      const projectName = hasSelection && selected ? selected.textContent : projectId;

      const projectCredentials = await chrome.runtime.sendMessage({
        type: 'GET_PROJECT_CREDENTIALS',
        projectId: projectId,
      });
      if (projectCredentials?.error || !projectCredentials?.api_key) {
        throw new Error(projectCredentials?.error || 'Could not obtain project credentials');
      }

      // Link chat to project — direct API call (not via background worker)
      const data = await apiPost('/v1/projects/' + projectId + '/link/chat', {
        chat_url: currentTabUrl,
        title: currentTabTitle,
        platform: new URL(currentTabUrl).hostname,
      }, projectCredentials.api_key);

      // Store link locally
      if (data.chat_url) {
        await Storage.setChatLink(
          data.chat_url,
          projectId,
          projectName,
          projectCredentials.api_key,
        );
      }

      // Notify content script
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tabId = tabs[0]?.id;
      if (tabId) {
        await startConversationSync(tabId, projectId, projectName);
      }

      // Reload popup to show linked state
      window.location.reload();
    } catch (err) {
      showError(err.message.indexOf('abort') !== -1
        ? 'Server not responding. Is Loom running?'
        : 'Link failed: ' + err.message);
      console.error('[Loom] Link error:', err);
      linkBtn.disabled = false;
      linkBtn.textContent = 'Link conversation';
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

    await Storage.removeChatLink(currentTabUrl);

    window.location.reload();
  });

})();
