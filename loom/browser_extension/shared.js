/** Shared, dependency-free helpers used by the popup, content script, and worker. */
(function (root, factory) {
  const helpers = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = helpers;
  }
  root.LoomShared = helpers;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function normalizeChatUrl(url) {
    if (!url) return '';
    try {
      const parsed = new URL(url);
      return (parsed.origin + parsed.pathname).replace(/\/$/, '');
    } catch (error) {
      return String(url).split('?')[0].split('#')[0].replace(/\/$/, '');
    }
  }

  function resolveProjectChoice(selectedProjectId, directProjectId) {
    const selected = String(selectedProjectId || '').trim();
    const direct = String(directProjectId || '').trim();
    if (!selected && !direct) {
      throw new Error('Select a project or enter a project ID.');
    }
    if (selected && direct && selected !== direct) {
      throw new Error('The selected project and entered project ID refer to different projects.');
    }
    return selected || direct;
  }

  function isLoomApiKey(value) {
    const candidate = String(value || '').trim();
    const opaqueKey = /^loom_[A-Za-z0-9_-]{32,}$/.test(candidate);
    const legacyUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(candidate);
    return opaqueKey || legacyUuid;
  }

  function messageIdentity(chatUrl, message) {
    const index = Number.isInteger(message.index) ? message.index : 0;
    return [
      normalizeChatUrl(chatUrl),
      index,
      String(message.role || ''),
      String(message.content || '').replace(/\s+/g, ' ').trim(),
    ].join(':');
  }

  return {
    isLoomApiKey,
    messageIdentity,
    normalizeChatUrl,
    resolveProjectChoice,
  };
});
