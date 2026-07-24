/**
 * Loom Extension — Content Script (Claude.ai)
 *
 * Detects Claude.ai chat pages, observes the DOM for new messages,
 * and communicates with the background service worker.
 */

(function () {
  'use strict';

  let chatUrl = window.location.href.split('?')[0];
  let messageIndex = 0;
  let knownMessages = new Set();

  // ── Initialisation ───────────────────────────────────────────────────────

  /**
   * Check with the background worker whether this chat is linked.
   */
  async function checkLink() {
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'CHECK_LINK',
        chatUrl,
      });
      if (response && response.linked) {
        console.log('[Loom] Chat linked to project:', response.projectId);
        startObserver();
      } else {
        console.log('[Loom] Chat not linked — prompting user');
        showLinkPrompt();
      }
    } catch (err) {
      console.warn('[Loom] Failed to check link:', err);
    }
  }

  // ── Link Prompt Banner ───────────────────────────────────────────────────

  function showLinkPrompt() {
    // Avoid duplicate banners
    if (document.getElementById('loom-link-banner')) return;

    const banner = document.createElement('div');
    banner.id = 'loom-link-banner';
    banner.style.cssText = `
      position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
      background: #1a1a2e; color: #e0e0e0;
      padding: 12px 20px; font-family: system-ui, sans-serif;
      display: flex; align-items: center; gap: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.3);
    `;

    banner.innerHTML = `
      <span style="font-size:18px;">🔗</span>
      <span style="flex:1;"><strong>Loom</strong> — Link this chat to a project?</span>
      <button id="loom-link-yes" style="
        background:#4f46e5; color:white; border:none; border-radius:6px;
        padding:6px 16px; cursor:pointer; font-size:13px;
      ">Link</button>
      <button id="loom-link-later" style="
        background:transparent; color:#999; border:1px solid #444;
        border-radius:6px; padding:6px 16px; cursor:pointer; font-size:13px;
      ">Not now</button>
    `;

    document.body.prepend(banner);

    document.getElementById('loom-link-yes').addEventListener('click', async () => {
      banner.remove();
      await openPopup();
    });

    document.getElementById('loom-link-later').addEventListener('click', () => {
      banner.remove();
    });
  }

  /**
   * Open the extension popup programmatically (via background).
   */
  async function openPopup() {
    try {
      await chrome.runtime.sendMessage({ type: 'OPEN_POPUP' });
    } catch (err) {
      console.warn('[Loom] Could not open popup:', err);
    }
  }

  // ── DOM Observer ─────────────────────────────────────────────────────────

  let observer = null;

  function startObserver() {
    if (observer) return;

    // Claude.ai chat messages are in article[data-testid="chat-message"]
    observer = new MutationObserver(() => {
      const articles = document.querySelectorAll(
        'article[data-testid="chat-message"]'
      );
      const newMessages = [];
      for (const article of articles) {
        // Use a data attribute to track already-seen messages
        if (article.dataset.loomSynced) continue;
        article.dataset.loomSynced = 'true';

        const role = article.getAttribute('data-role') || 'user';
        const textEl = article.querySelector('.prose p, .whitespace-pre-wrap');
        const content = textEl ? textEl.textContent.trim() : '';

        if (content) {
          newMessages.push({ role, content, index: messageIndex++ });
        }
      }

      if (newMessages.length > 0) {
        chrome.runtime.sendMessage({
          type: 'SYNC_MESSAGES',
          chatUrl,
          messages: newMessages,
        }).catch(() => {});
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  // ── Listen for background messages ───────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'LOOM_LINKED') {
      showLinkPrompt(); // will check again and update
      sendResponse({ ok: true });
    }
  });

  // ── Boot ─────────────────────────────────────────────────────────────────

  // Short delay to let the page's SPA router settle
  setTimeout(checkLink, 1500);

})();
