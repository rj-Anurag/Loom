(function () {
  'use strict';

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
    window.addEventListener('popstate', updateChatUrl);
    window.addEventListener('hashchange', updateChatUrl);
    // Override history methods to catch SPA navigations
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
  }

  // ── Message Collection ──────────────────────────────────────────────────

  function collectNewMessages() {
    // Try multiple selector strategies for different Claude.ai DOM versions
    let root = document.querySelector('main') || document.querySelector('[role="main"]');
    if (!root) root = document.body;

    let articles = root.querySelectorAll([
      'article[data-testid="chat-message"]',
      'div[data-testid="message"]',
      '[data-message-author-role]',
      'div[role="article"]',
      'article',
    ].join(','));

    // Filter to only elements that look like chat messages (have substantial text)
    const validArticles = [];
    for (const article of articles) {
      const text = article.textContent.trim();
      if (text.length > 15) {
        validArticles.push(article);
      }
    }

    const newMessages = [];
    for (const article of validArticles) {
      if (article.dataset.loomSynced) continue;
      article.dataset.loomSynced = 'true';

      const role = article.getAttribute('data-role')
        || article.getAttribute('data-message-author-role')
        || 'user';

      let content = '';
      const contentSelectors = '.prose p, .whitespace-pre-wrap, .markdown p, [data-message-content]';
      const textEl = article.querySelector(contentSelectors);
      if (textEl) {
        content = textEl.textContent.trim();
      } else {
        content = article.textContent.trim();
      }

      if (content && content.length > 10) {
        newMessages.push({ role, content, index: messageIndex++ });
      }
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

    banner.innerHTML = [
      '<span style="font-size:18px;">✅</span>',
      '<span style="flex:1;">',
      '<strong>Linked</strong> to <strong>' + projectName + '</strong>',
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
      stopObserver();
      startObserver();
      sendResponse({ ok: true });
    }
    if (msg.type === 'LOOM_URL_CHANGED') {
      updateChatUrl();
      sendResponse({ ok: true });
    }
  });

  // ── Boot ────────────────────────────────────────────────────────────────

  trackUrlChanges();
  // Short delay to let the page's SPA router settle
  setTimeout(checkLink, 1500);

})();
