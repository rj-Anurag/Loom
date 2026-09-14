(function () {
  'use strict';

  try {

  let chatUrl = LoomShared.normalizeChatUrl(window.location.href);
  let acceptedMessages = new Set();
  let pendingMessages = new Set();
  let elementStates = new WeakMap();
  let observer = null;
  let pollInterval = null;
  let flushTimer = null;
  let linkedProjectId = null;
  let backfilledProjectId = null;
  let backfillPromise = null;
  let contentScriptActive = true;

  function errorMessage(error) {
    if (!error) return 'Unknown error';
    return error.message || String(error);
  }

  function extensionContextAvailable() {
    try {
      return contentScriptActive && !!(chrome.runtime && chrome.runtime.id);
    } catch (error) {
      return false;
    }
  }

  function deactivateContentScript() {
    if (!contentScriptActive) return;
    contentScriptActive = false;
    stopObserver();
    window.removeEventListener('popstate', updateChatUrl);
    window.removeEventListener('hashchange', updateChatUrl);
    console.info('[Loom] Content script stopped because the extension was reloaded');
  }

  function reportHandledIssue(message, error) {
    console.info(message, errorMessage(error));
  }

  function resetCaptureState() {
    acceptedMessages = new Set();
    pendingMessages = new Set();
    elementStates = new WeakMap();
    document.querySelectorAll('[data-loom-synced], [data-loom-pending]').forEach(function (el) {
      delete el.dataset.loomSynced;
      delete el.dataset.loomPending;
    });
  }

  // ── URL Change Tracking ──────────────────────────────────────────────────

  function updateChatUrl() {
    if (!contentScriptActive) return;
    const newUrl = LoomShared.normalizeChatUrl(window.location.href);
    if (newUrl !== chatUrl) {
      console.log('[Loom] URL changed:', chatUrl, '→', newUrl);
      chatUrl = newUrl;
      resetCaptureState();
      linkedProjectId = null;
      backfilledProjectId = null;
      stopObserver();
      // Re-check link for the new URL
      checkLink();
    }
  }

  function trackUrlChanges() {
    try {
      window.addEventListener('popstate', updateChatUrl);
      window.addEventListener('hashchange', updateChatUrl);
    } catch (e) { reportHandledIssue('[Loom] Could not add event listeners:', e); }
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
    } catch (e) { reportHandledIssue('[Loom] Could not override history:', e); }
  }

  // ── Message Collection ──────────────────────────────────────────────────

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

  function platformAdapter() {
    var hostname = window.location.hostname;
    if (hostname === 'chatgpt.com') {
      return { name: 'ChatGPT', selectors: ['[data-message-author-role]'] };
    }
    if (hostname === 'claude.ai') {
      return {
        name: 'Claude',
        selectors: [
          '[data-message-author-role]',
          '[data-testid="user-message"], [data-testid="assistant-message"]',
          '.font-user-message, .font-claude-message, .font-claude-response',
        ],
      };
    }
    if (hostname === 'chat.deepseek.com') {
      return {
        name: 'DeepSeek',
        selectors: [
          '[data-message-author-role]',
          '[data-role="user"], [data-role="assistant"]',
        ],
      };
    }
    return {
      name: 'Perplexity',
      selectors: [
        '[data-message-author-role]',
        '[data-testid="user-query"], [data-testid="answer"]',
      ],
    };
  }

  function findMessageElements() {
    var adapter = platformAdapter();
    // Claude can mix old and new message markup in the same conversation.
    // Taking only the first selector with a match captures the newest turn but
    // silently misses historical turns rendered with an older component.
    var selector = adapter.selectors.join(', ');
    var matches = Array.from(document.querySelectorAll(selector));
    if (matches.length > 0) {
      return matches.filter(function (candidate) {
        var candidateText = (candidate.textContent || '').replace(/\s+/g, ' ').trim();
        return !matches.some(function (other) {
          if (other === candidate || !candidate.contains(other)) return false;
          var otherText = (other.textContent || '').replace(/\s+/g, ' ').trim();
          return candidateText === otherText;
        });
      });
    }
    var root = document.querySelector('main') || document.querySelector('[role="main"]');
    return root ? Array.from(root.querySelectorAll('article[data-testid*="turn"]')) : [];
  }

  function inferRole(el, position) {
    var rawRole = (
      el.getAttribute('data-message-author-role') ||
      el.getAttribute('data-role') ||
      el.getAttribute('aria-label') ||
      el.getAttribute('data-testid') ||
      ''
    ).toLowerCase();
    var classList = typeof el.className === 'string' ? el.className.toLowerCase() : '';
    var markers = rawRole + ' ' + classList;
    if (/assistant|claude|answer|ai-message/.test(markers)) return 'assistant';
    if (/user|human|query|prompt/.test(markers)) return 'user';
    return position % 2 === 0 ? 'user' : 'assistant';
  }

  function collectNewMessages() {
    const records = [];

    var rawElements = findMessageElements();
    for (var position = 0; position < rawElements.length; position++) {
      const el = rawElements[position];
      const text = (el.innerText || el.textContent || '').trim();
      if (text.length < 2) continue;

      var role = inferRole(el, position);
      var content = cleanContent(text);
      if (content.length < 2) continue;

      var message = { role: role, content: content, index: position };
      var identity = LoomShared.messageIdentity(chatUrl, message);
      var elementState = elementStates.get(el);
      if (
        (elementState && elementState.identity === identity) ||
        acceptedMessages.has(identity) ||
        pendingMessages.has(identity)
      ) {
        continue;
      }

      el.dataset.loomPending = 'true';
      elementStates.set(el, { identity: identity, status: 'pending' });
      pendingMessages.add(identity);
      records.push({ el: el, identity: identity, message: message });
    }

    if (records.length > 0) {
      console.log('[Loom] Collected', records.length, platformAdapter().name, 'message(s)');
    }
    return records;
  }

  // ── Sync ────────────────────────────────────────────────────────────────

  function sendBackgroundMessage(message) {
    return new Promise(function (resolve) {
      try {
        if (!extensionContextAvailable()) {
          deactivateContentScript();
          resolve({ error: 'Extension context is unavailable.', contextInvalidated: true });
          return;
        }
        chrome.runtime.sendMessage(message, function (response) {
          try {
            const lastError = chrome.runtime.lastError;
            if (lastError) {
              var message = lastError.message || 'Background message failed.';
              var invalidated = !extensionContextAvailable() || /extension context (?:is )?invalidated/i.test(message);
              if (invalidated) deactivateContentScript();
              resolve({ error: message, contextInvalidated: invalidated });
              return;
            }
            resolve(response || {});
          } catch (error) {
            deactivateContentScript();
            resolve({ error: errorMessage(error), contextInvalidated: true });
          }
        });
      } catch (err) {
        var invalidated = !extensionContextAvailable() || /extension context (?:is )?invalidated/i.test(errorMessage(err));
        if (invalidated) deactivateContentScript();
        resolve({ error: errorMessage(err), contextInvalidated: invalidated });
      }
    });
  }

  function releaseRecords(records) {
    if (!Array.isArray(records)) return;
    records.forEach(function (record) {
      if (!record || !record.identity) return;
      pendingMessages.delete(record.identity);
      var el = record.el;
      if (!el || typeof el !== 'object') return;
      var state = elementStates.get(el);
      if (state && state.identity === record.identity && state.status === 'pending') {
        if (el.dataset) delete el.dataset.loomPending;
        elementStates.delete(el);
      }
    });
  }

  function acceptRecords(records) {
    if (!Array.isArray(records)) return;
    records.forEach(function (record) {
      if (!record || !record.identity) return;
      pendingMessages.delete(record.identity);
      acceptedMessages.add(record.identity);
      var el = record.el;
      if (!el || typeof el !== 'object') return;
      if (el.dataset) {
        delete el.dataset.loomPending;
        el.dataset.loomSynced = 'true';
      }
      elementStates.set(el, { identity: record.identity, status: 'synced' });
    });
  }

  function submitRecords(records, label) {
    if (records.length === 0) return Promise.resolve(0);
    return sendBackgroundMessage({
      type: 'SYNC_MESSAGES',
      chatUrl,
      messages: records.map(function (record) { return record.message; }),
    }).then(resp => {
      if (resp?.error) {
        releaseRecords(records);
        if (!resp.contextInvalidated) {
          reportHandledIssue('[Loom] History sync deferred:', resp.error);
        }
        return 0;
      }
      var accepted = (resp?.synced || 0) + (resp?.queued || 0);
      if (accepted !== records.length) {
        releaseRecords(records);
        console.info('[Loom] History sync was not accepted; it will be retried');
        return 0;
      }
      acceptRecords(records);
      console.log('[Loom] Accepted', accepted, label || 'message(s)');
      return accepted;
    }).catch(err => {
      releaseRecords(records);
      reportHandledIssue('[Loom] Sync failed:', err);
      return 0;
    });
  }

  function flushMessages() {
    if (!contentScriptActive) return Promise.resolve(0);
    if (LoomShared.normalizeChatUrl(window.location.href) !== chatUrl) {
      updateChatUrl();
      return Promise.resolve(0);
    }
    return submitRecords(collectNewMessages(), 'message(s)');
  }

  function findConversationScroller() {
    var messages = findMessageElements();
    var node = messages.length > 0 ? messages[0].parentElement : null;
    while (node && node !== document.body) {
      var style = window.getComputedStyle(node);
      if (
        /(auto|scroll)/.test(style.overflowY) &&
        node.scrollHeight > node.clientHeight + 20
      ) {
        return node;
      }
      node = node.parentElement;
    }
    return document.scrollingElement || document.documentElement;
  }

  function wait(milliseconds) {
    return new Promise(function (resolve) { setTimeout(resolve, milliseconds); });
  }

  async function backfillConversationHistory(projectId) {
    if (!contentScriptActive || !projectId || backfilledProjectId === projectId) return;
    if (backfillPromise) return backfillPromise;

    backfillPromise = (async function () {
      var scroller = findConversationScroller();
      if (!scroller) return;
      var originalBottomOffset = scroller.scrollHeight - scroller.scrollTop;
      var previousHeight = -1;
      var previousCount = -1;
      var stablePasses = 0;

      // Some chat UIs materialize older turns only as the conversation is
      // scrolled upward. Keep requesting the top until both DOM count and
      // scroll height remain unchanged for three passes.
      for (var pass = 0; pass < 40 && stablePasses < 3; pass++) {
        if (!contentScriptActive) return;
        scroller.scrollTop = 0;
        scroller.dispatchEvent(new Event('scroll', { bubbles: true }));
        await wait(400);

        var currentHeight = scroller.scrollHeight;
        var currentCount = findMessageElements().length;
        if (currentHeight === previousHeight && currentCount === previousCount) {
          stablePasses++;
        } else {
          stablePasses = 0;
          previousHeight = currentHeight;
          previousCount = currentCount;
        }
      }

      resetCaptureState();
      var accepted = await flushMessages();
      backfilledProjectId = projectId;
      scroller.scrollTop = Math.max(0, scroller.scrollHeight - originalBottomOffset);
      console.log('[Loom] Historical backfill completed:', accepted, 'message(s) accepted');
    })().finally(function () {
      backfillPromise = null;
    });

    return backfillPromise;
  }

  function activateLinkedConversation(projectId) {
    if (!contentScriptActive || !projectId) return;
    if (linkedProjectId !== projectId) {
      resetCaptureState();
      backfilledProjectId = null;
      linkedProjectId = projectId;
    }
    stopObserver();
    backfillConversationHistory(projectId)
      .catch(function (err) {
        reportHandledIssue('[Loom] Historical backfill failed:', err);
      })
      .finally(function () {
        if (contentScriptActive && linkedProjectId === projectId) startObserver();
      });
  }

  // ── Observer + Polling ──────────────────────────────────────────────────

  function scheduleFlush(delay) {
    if (!contentScriptActive) return;
    if (flushTimer) clearTimeout(flushTimer);
    flushTimer = setTimeout(function () {
      flushTimer = null;
      flushMessages().catch(function (err) {
        reportHandledIssue('[Loom] Scheduled sync failed:', err);
      });
    }, delay || 750);
  }

  function startObserver() {
    if (!contentScriptActive || !document.body) return;
    if (observer) {
      scheduleFlush(100);
      return;
    }

    observer = new MutationObserver(function () { scheduleFlush(750); });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    // Poll every 5s as a fallback
    pollInterval = setInterval(function () {
      flushMessages().catch(function (err) {
        reportHandledIssue('[Loom] Polling sync failed:', err);
      });
    }, 5000);

    // Immediately sync any messages already rendered
    scheduleFlush(100);
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
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
  }

  // ── Link Check ──────────────────────────────────────────────────────────

  async function checkLink() {
    if (!contentScriptActive) return;
    try {
      const response = await sendBackgroundMessage({
        type: 'CHECK_LINK',
        chatUrl,
      });
      if (response?.error) {
        if (!response.contextInvalidated) {
          reportHandledIssue('[Loom] Failed to check link:', response.error);
        }
        return;
      }
      if (response && response.linked) {
        console.log('[Loom] Chat linked to project:', response.projectId);
        activateLinkedConversation(response.projectId);
      } else {
        stopObserver();
        console.log('[Loom] Chat not linked — prompting user');
      }
    } catch (err) {
      reportHandledIssue('[Loom] Failed to check link:', err);
    }
  }

  // ── Banner Cleanup ──────────────────────────────────────────────────────

  function dismissLinkBanner() {
    const banner = document.getElementById('loom-link-banner');
    if (banner) banner.remove();
  }

  // ── Listen for background messages ──────────────────────────────────────

  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (!contentScriptActive || !msg || typeof msg.type !== 'string') return false;
    if (msg.type === 'LOOM_LINKED') {
      console.log('[Loom] Received LOOM_LINKED:', msg.projectName);
      dismissLinkBanner();
      activateLinkedConversation(msg.projectId);
      sendResponse({ ok: true });
    }
    if (msg.type === 'LOOM_URL_CHANGED') {
      updateChatUrl();
      sendResponse({ ok: true });
    }
    if (msg.type === 'RESCAN') {
      resetCaptureState();
      backfilledProjectId = null;
      if (linkedProjectId) {
        activateLinkedConversation(linkedProjectId);
      } else {
        checkLink();
      }
      sendResponse({ ok: true });
    }
    return false;
  });

  // ── Console Debug Hooks ─────────────────────────────────────────────────

  window.__loom_rescan = function () {
    console.log('[Loom] Manual rescan triggered');
    resetCaptureState();
    var records = collectNewMessages();
    console.log('[Loom] Manual rescan found', records.length, 'message(s)');
    submitRecords(records, 'manually rescanned message(s)');
    return records.map(function (record) { return record.message; });
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
      acceptedMessagesCount: acceptedMessages.size,
      pendingMessagesCount: pendingMessages.size,
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
