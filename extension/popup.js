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
  const newProjectInput = document.getElementById('new-project-name');
  const linkBtn = document.getElementById('link-btn');
  const errorMsg = document.getElementById('error-msg');
  const linkedProjectName = document.getElementById('linked-project-name');
  const unlinkBtn = document.getElementById('unlink-btn');

  let currentTabUrl = '';
  let currentlyLinkedProjectId = null;

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

  // ── Link / Create project ──────────────────────────────────────────────

  linkBtn.addEventListener('click', async () => {
    hideError();
    linkBtn.disabled = true;
    linkBtn.textContent = 'Linking...';

    try {
      let projectId = projectSelect.value;
      const newName = newProjectInput.value.trim();

      if (projectId && newName) {
        showError('Pick an existing project or create a new one, not both.');
        linkBtn.disabled = false;
        linkBtn.textContent = 'Link Chat';
        return;
      }

      if (newName) {
        // Create project first
        const created = await chrome.runtime.sendMessage({
          type: 'CREATE_PROJECT',
          name: newName,
        });
        if (created && created.id) {
          projectId = created.id;
        } else {
          showError('Failed to create project.');
          linkBtn.disabled = false;
          linkBtn.textContent = 'Link Chat';
          return;
        }
      }

      if (!projectId) {
        showError('Select or create a project first.');
        linkBtn.disabled = false;
        linkBtn.textContent = 'Link Chat';
        return;
      }

      // Get project name from selected option or new name
      const projectName = newName || projectSelect.options[projectSelect.selectedIndex]?.text || projectId;

      // Link chat to project
      const result = await chrome.runtime.sendMessage({
        type: 'LINK_CHAT',
        chatUrl: currentTabUrl,
        projectId,
        projectName,
        title: document.title || '',
        platform: new URL(currentTabUrl).hostname,
      });

      if (result && result.id) {
        // Notify content script
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        const tabId = tabs[0]?.id;
        if (tabId) {
          await chrome.tabs.sendMessage(tabId, { type: 'LOOM_LINKED', projectName }).catch(() => {});
        }

        // Reload popup to show linked state
        window.location.reload();
      } else {
        showError('Link failed. Check Loom server.');
        linkBtn.disabled = false;
        linkBtn.textContent = 'Link Chat';
      }
    } catch (err) {
      showError('Error linking chat.');
      console.error('[Loom] Link error:', err);
      linkBtn.disabled = false;
      linkBtn.textContent = 'Link Chat';
    }
  });

  // ── Unlink ──────────────────────────────────────────────────────────────

  unlinkBtn.addEventListener('click', async () => {
    if (!currentTabUrl) return;

    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    delete links[currentTabUrl];
    await chrome.storage.local.set({ [key]: links });

    window.location.reload();
  });

})();
