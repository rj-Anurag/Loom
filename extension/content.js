(function () {
  'use strict';

  try {

  let chatUrl = window.location.href.split('?')[0];
  let messageIndex = 0;
  let knownMessages = new Set();
  let observer = null;
  let pollInterval = null;

  // ── URL Change Tracking ──────────────────────────────────────────────────

  function updateChatUrl() {
    const newUrl = window.location.href.split('?')[0];
    if (newUrl !== chatUrl) {
      console.log('[Loom] URL changed:', chatUrl, '→', newUrl);
      chatUrl = newUrl;
      messageIndex = 0;
      knownMessages = new Set();
      // Re-check link for the new URL
      checkLink();
    }
  }

  function trackUrlChanges() {
    try {
      window.addEventListener('popstate', updateChatUrl);
      window.addEventListener('hashchange', updateChatUrl);
    } catch (e) { console.warn('[Loom] Could not add event listeners:', e); }
    try {
      const origPushState = history.pushState;
      history.pushState = function () {
        origPushState.apply(this, arguments);
        updateChatUrl();
      };
      const origReplaceState = history.replaceState;
      history.replaceState = function () {
        origReplaceState.apply(this, arguments);
        updateChatUrl();
      };
    } catch (e) { console.warn('[Loom] Could not override history:', e); }
  }

  // ── Message Collection ──────────────────────────────────────────────────

  function contentKey(text) {
    return text.slice(0, 120).replace(/\s+/g, ' ');
  }

  // ── Noise filter ──────────────────────────────────────────────────────
  var _NOISE_PATTERNS = [
    /^Use the up and down arrow keys to move between messages\.\s*/,
    /^You can use the up and down arrow keys to move between messages\.\s*/,
    /^\s*Press\s+\S+\s+for\s/i,
    /^Search(\s|$)/,
    /^New Chat(\s|$)/i,
    /^Settings(\s|$)/i,
    /^Log out(\s|$)/i,
  ];

  function cleanContent(text) {
    for (var n = 0; n < _NOISE_PATTERNS.length; n++) {
      text = text.replace(_NOISE_PATTERNS[n], '');
    }
    return text.trim();
  }

  // ── Role validation ────────────────────────────────────────────────────
  // Any conversation MUST alternate: user → assistant → user → assistant → ...
  // If data-message-author-role gives wrong values, we detect non-alternation
  // and recalculate by position (which is always reliable).
  function validateRoles(elements) {
    if (elements.length < 2) return;
    for (var i = 1; i < elements.length; i++) {
      if (elements[i].role === elements[i - 1].role) {
        console.warn('[Loom] Role alternation broken at', i, '- recalculating all roles by position');
        for (var j = 0; j < elements.length; j++) {
          elements[j].role = (j % 2 === 0) ? 'user' : 'assistant';
        }
        return;
      }
    }
  }

  function collectNewMessages() {
    const newMessages = [];

    // Strategy 1: per-message containers via data attribute (cleanest)
    var rawElements = document.querySelectorAll('[data-message-author-role]');
    var strategy1Found = rawElements.length > 0;

    // Build an array with validated roles
    var collected = [];
    for (const el of rawElements) {
      if (el.dataset.loomSynced) continue;
      const text = el.textContent.trim();
      if (text.length < 20) { el.dataset.loomSynced = 'true'; continue; }
      el.dataset.loomSynced = 'true';

      var rawRole = el.getAttribute('data-message-author-role') || '';
      var role = 'user';
      if (rawRole === 'assistant' || rawRole === 'AI') {
        role = 'assistant';
      } else if (rawRole === 'user' || rawRole === 'User') {
        role = 'user';
      } else {
        // Unexpected or empty role — will be set by position later
        role = null;
      }

      let content = '';
      const paragraphs = el.querySelectorAll('p');
      if (paragraphs.length > 0) {
        content = Array.from(paragraphs).map(function (p) { return p.textContent.trim(); }).filter(Boolean).join('\n');
      } else {
        content = text;
      }
      content = cleanContent(content);
      if (content.length > 10 && !knownMessages.has(contentKey(content))) {
        knownMessages.add(contentKey(content));
        collected.push({ el: el, role: role, content: content, index: messageIndex++ });
      }
    }

    // If strategy 1 found elements, validate and fix roles
    if (strategy1Found) {
      if (collected.length > 0) {
        // Step 1: Assign positions for any null roles
        for (var si = 0; si < collected.length; si++) {
          if (collected[si].role === null) {
            collected[si].role = (si % 2 === 0) ? 'user' : 'assistant';
          }
        }
        // Step 2: Validate alternation — if broken, recalculate ALL by position
        validateRoles(collected);
        console.log('[Loom] Collected', collected.length, 'new message(s) via strategy 1');
      }
      for (var mi = 0; mi < collected.length; mi++) {
        newMessages.push({ role: collected[mi].role, content: collected[mi].content, index: collected[mi].index });
      }
      return newMessages;
    }

    // Strategy 2: elements with multiple <p> children (likely message containers)
    var root = document.querySelector('main') || document.querySelector('[role="main"]') || document.body;
    var candidates = root.querySelectorAll('div, article, section');
    for (var ci = 0; ci < candidates.length; ci++) {
      var el = candidates[ci];
      if (el.dataset.loomSynced) continue;
      var ps = el.querySelectorAll(':scope > p');
      if (ps.length === 0) ps = el.querySelectorAll('p');
      if (ps.length === 0) continue;
      var combined = '';
      for (var pi = 0; pi < ps.length; pi++) {
        combined += ps[pi].textContent.trim() + ' ';
      }
      combined = cleanContent(combined);
      if (combined.length < 20) continue;
      if (knownMessages.has(contentKey(combined))) continue;
      el.dataset.loomSynced = 'true';
      var role = (newMessages.length % 2 === 0) ? 'user' : 'assistant';
      knownMessages.add(contentKey(combined));
      newMessages.push({ role: role, content: combined, index: messageIndex++ });
    }
    if (newMessages.length > 0) return newMessages;

    // Strategy 3: grab every substantial <p> tag anywhere on the page
    var allPs = document.querySelectorAll('p');
    var collected = [];
    for (var pi = 0; pi < allPs.length; pi++) {
      var text = allPs[pi].textContent.trim();
      if (text.length < 30) continue;
      if (knownMessages.has(contentKey(text))) continue;
      knownMessages.add(contentKey(text));
      collected.push(text);
    }
    for (var i = 0; i < collected.length; i++) {
      var cleaned = cleanContent(collected[i]);
      if (cleaned.length < 20) continue;
      var role = (i % 2 === 0) ? 'user' : 'assistant';
      newMessages.push({ role: role, content: cleaned, index: messageIndex++ });
    }

    if (newMessages.length > 0) {
      console.log('[Loom] Collected', newMessages.length, 'new message(s)');
    }
    return newMessages;
  }

  // ── Sync ────────────────────────────────────────────────────────────────

  function flushMessages() {
    const batch = collectNewMessages();
    if (batch.length > 0) {
      chrome.runtime.sendMessage({
        type: 'SYNC_MESSAGES',
        chatUrl,
        messages: batch,
      }).then(resp => {
        console.log('[Loom] Synced', resp.synced, 'messages');
      }).catch(err => {
        console.warn('[Loom] Sync failed:', err.message);
      });
    }
  }

  function syncExistingMessages() {
    const batch = collectNewMessages();
    if (batch.length > 0) {
      chrome.runtime.sendMessage({
        type: 'SYNC_MESSAGES',
        chatUrl,
        messages: batch,
      }).then(resp => {
        console.log('[Loom] Synced', resp.synced, 'existing message(s)');
      }).catch(err => {
        console.warn('[Loom] Sync failed:', err.message);
      });
    }
  }

  // ── Observer + Polling ──────────────────────────────────────────────────

  function startObserver() {
    if (observer) {
      syncExistingMessages();
      return;
    }

    observer = new MutationObserver(flushMessages);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    // Poll every 5s as a fallback
    pollInterval = setInterval(flushMessages, 5000);

    // Immediately sync any messages already rendered
    flushMessages();
    console.log('[Loom] Observer + polling started');
  }

  function stopObserver() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  // ── Link Check ──────────────────────────────────────────────────────────

  async function checkLink() {
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'CHECK_LINK',
        chatUrl,
      });
      if (response && response.linked) {
        console.log('[Loom] Chat linked to project:', response.projectId);
        document.querySelectorAll('[data-loom-synced]').forEach(function (el) { delete el.dataset.loomSynced; });
        stopObserver();
        startObserver();
      } else {
        console.log('[Loom] Chat not linked — prompting user');
      }
    } catch (err) {
      console.warn('[Loom] Failed to check link:', err.message);
    }
  }

  // ── Link Prompt Banner ──────────────────────────────────────────────────

  function showLinkPrompt() {
    if (document.getElementById('loom-link-banner')) return;

    const banner = document.createElement('div');
    banner.id = 'loom-link-banner';
    banner.style.cssText = [
      'position: fixed; top: 0; left: 0; right: 0; z-index: 99999;',
      'background: #1a1a2e; color: #e0e0e0;',
      'padding: 12px 20px; font-family: system-ui, sans-serif;',
      'display: flex; align-items: center; gap: 12px;',
      'box-shadow: 0 2px 12px rgba(0,0,0,0.3);',
    ].join(' ');

    banner.innerHTML = [
      '<span style="font-size:18px;">🔗</span>',
      '<span style="flex:1;">',
      '<strong>Loom</strong> — Click the Loom icon',
      '<span style="background:#4f46e5;padding:1px 6px;border-radius:4px;font-size:11px;">⋮</span>',
      'in the toolbar to link this chat to a project',
      '</span>',
      '<button id="loom-link-later" style="',
      'background:transparent; color:#999; border:1px solid #444;',
      'border-radius:6px; padding:6px 16px; cursor:pointer; font-size:13px;',
      'white-space:nowrap;">Dismiss</button>',
    ].join('');

    document.body.prepend(banner);
    document.getElementById('loom-link-later').addEventListener('click', () => {
      banner.remove();
    });
  }

  // ── Confirmation Banner ─────────────────────────────────────────────────

  function showLinkedConfirmation(projectName) {
    const oldBanner = document.getElementById('loom-link-banner');
    if (oldBanner) oldBanner.remove();

    const banner = document.createElement('div');
    banner.id = 'loom-link-banner';
    banner.style.cssText = [
      'position: fixed; top: 0; left: 0; right: 0; z-index: 99999;',
      'background: #064e3b; color: #a7f3d0;',
      'padding: 12px 20px; font-family: system-ui, sans-serif;',
      'display: flex; align-items: center; gap: 12px;',
      'box-shadow: 0 2px 12px rgba(0,0,0,0.3);',
    ].join(' ');

    // escapeHtml is not available in content script scope, so sanitize manually
    var safeName = String(projectName).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    banner.innerHTML = [
      '<span style="font-size:18px;">✅</span>',
      '<span style="flex:1;">',
      '<strong>Linked</strong> to <strong>' + safeName + '</strong>',
      '</span>',
    ].join('');

    document.body.prepend(banner);
    setTimeout(function () { banner.remove(); }, 3000);
  }

  // ── Listen for background messages ──────────────────────────────────────

  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (msg.type === 'LOOM_LINKED') {
      console.log('[Loom] Received LOOM_LINKED:', msg.projectName);
      showLinkedConfirmation(msg.projectName || 'project');
      document.querySelectorAll('[data-loom-synced]').forEach(function (el) { delete el.dataset.loomSynced; });
      stopObserver();
      startObserver();
      sendResponse({ ok: true });
    }
    if (msg.type === 'LOOM_URL_CHANGED') {
      updateChatUrl();
      sendResponse({ ok: true });
    }
    if (msg.type === 'RESCAN') {
      document.querySelectorAll('[data-loom-synced]').forEach(function (el) { delete el.dataset.loomSynced; });
      flushMessages();
      sendResponse({ ok: true });
    }
  });

  // ── Console Debug Hooks ─────────────────────────────────────────────────

  window.__loom_rescan = function () {
    console.log('[Loom] Manual rescan triggered');
    document.querySelectorAll('[data-loom-synced]').forEach(function (el) { delete el.dataset.loomSynced; });
    var msgs = collectNewMessages();
    console.log('[Loom] Manual rescan found', msgs.length, 'message(s):', msgs.map(function (m) { return m.role + ': ' + m.content.slice(0, 60); }));
    if (msgs.length > 0) {
      chrome.runtime.sendMessage({ type: 'SYNC_MESSAGES', chatUrl: window.location.href.split('?')[0], messages: msgs })
        .then(function (r) { console.log('[Loom] Manual sync result:', r); })
        .catch(function (e) { console.warn('[Loom] Manual sync failed:', e); });
    }
    return msgs;
  };

  window.__loom_debug = function () {
    var msgs = document.querySelectorAll('[data-message-author-role]');
    var elements = [];
    for (var i = 0; i < msgs.length; i++) {
      var el = msgs[i];
      elements.push({
        role: el.getAttribute('data-message-author-role'),
        first80: el.textContent.trim().slice(0, 80).replace(/\s+/g, ' '),
        synced: !!el.dataset.loomSynced,
      });
    }
    var info = {
      url: window.location.href,
      chatUrl: chatUrl,
      msgCount: msgs.length,
      roles: elements,
      hasMain: !!document.querySelector('main'),
      hasMainP: document.querySelectorAll('main p').length,
      hasBodyP: document.querySelectorAll('p').length,
      knownMessagesCount: knownMessages.size,
      contentScriptLoaded: true,
    };
    console.log('[Loom] Debug info:', info);
    return info;
  };

  // ── Boot ────────────────────────────────────────────────────────────────

  // Confirm content script is alive
  console.log('[Loom] Content script loaded on', window.location.hostname);

  trackUrlChanges();
  // Short delay to let the page's SPA router settle
  setTimeout(checkLink, 1500);

  } catch (e) {
    console.error('[Loom] Boot error:', e);
  }

})();
