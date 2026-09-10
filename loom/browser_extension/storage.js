/**
 * Loom Extension — Chrome Storage Helpers
 *
 * Thin wrappers around chrome.storage.local for reading / writing
 * chat-link mappings and agent credentials.
 */

function normalizeChatUrl(url) {
  return LoomShared.normalizeChatUrl(url);
}

const Storage = {
  /**
   * Normalize a URL for consistent storage lookup.
   * @param {string} url
   * @returns {string}
   */
  normalizeUrl(url) {
    return normalizeChatUrl(url);
  },

  /**
   * Get project info linked to a chat URL.
   * @param {string} chatUrl
   * @returns {Promise<{projectId: string, projectName: string, apiKey?: string}|null>}
   */
  async getProjectForChat(chatUrl) {
    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    const norm = normalizeChatUrl(chatUrl);
    const entry = links[norm] || links[chatUrl] || links[norm + '/'];
    if (!entry) return null;
    // Support both legacy (string) and new (object) formats
    if (typeof entry === 'string') {
      return { projectId: entry, projectName: entry };
    }
    return entry;
  },

  /**
   * Store a chat URL → { projectId, projectName } mapping.
   * @param {string} chatUrl
   * @param {string} projectId
   * @param {string} [projectName]
   */
  async setChatLink(chatUrl, projectId, projectName) {
    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    const norm = normalizeChatUrl(chatUrl);
    const val = { projectId, projectName: projectName || projectId };
    links[norm] = val;
    if (chatUrl !== norm) links[chatUrl] = val;
    await chrome.storage.local.set({ [key]: links });
  },

  /**
   * Check if a chat URL is already linked to a project.
   * @param {string} chatUrl
   * @returns {Promise<boolean>}
   */
  async isLinked(chatUrl) {
    const pid = await this.getProjectForChat(chatUrl);
    return pid !== null;
  },

  /**
   * Get stored agent credentials.
   * @returns {Promise<{agent_id: string, api_key: string}|null>}
   */
  async getCredentials() {
    const key = LOOM_CONFIG.STORAGE_KEYS.AGENT_CREDENTIALS;
    const result = await chrome.storage.local.get(key);
    return result[key] || null;
  },

  /**
   * Store agent credentials (returned when creating a project).
   * @param {string} agentId
   * @param {string} apiKey
   */
  async setCredentials(agentId, apiKey) {
    const key = LOOM_CONFIG.STORAGE_KEYS.AGENT_CREDENTIALS;
    await chrome.storage.local.set({
      [key]: { agent_id: agentId, api_key: apiKey },
    });
  },

  async getProjectCredentials(projectId) {
    const key = LOOM_CONFIG.STORAGE_KEYS.PROJECT_CREDENTIALS;
    const result = await chrome.storage.local.get(key);
    return (result[key] || {})[projectId] || null;
  },

  async setProjectCredentials(projectId, agentId, apiKey) {
    const key = LOOM_CONFIG.STORAGE_KEYS.PROJECT_CREDENTIALS;
    const result = await chrome.storage.local.get(key);
    const credentials = result[key] || {};
    credentials[projectId] = { agent_id: agentId, api_key: apiKey };
    await chrome.storage.local.set({ [key]: credentials });
  },

  async removeProjectCredentials(projectId) {
    const key = LOOM_CONFIG.STORAGE_KEYS.PROJECT_CREDENTIALS;
    const result = await chrome.storage.local.get(key);
    const credentials = result[key] || {};
    delete credentials[projectId];
    await chrome.storage.local.set({ [key]: credentials });
  },

  async getAccount() {
    const key = LOOM_CONFIG.STORAGE_KEYS.ACCOUNT_SESSION;
    const result = await chrome.storage.local.get(key);
    return result[key] || null;
  },

  async setAccount(sessionToken, user) {
    const key = LOOM_CONFIG.STORAGE_KEYS.ACCOUNT_SESSION;
    await chrome.storage.local.set({
      [key]: { session_token: sessionToken, user: user },
    });
  },

  async clearAccount() {
    await chrome.storage.local.remove([
      LOOM_CONFIG.STORAGE_KEYS.ACCOUNT_SESSION,
      LOOM_CONFIG.STORAGE_KEYS.AGENT_CREDENTIALS,
      LOOM_CONFIG.STORAGE_KEYS.PROJECT_CREDENTIALS,
      LOOM_CONFIG.STORAGE_KEYS.CURRENT_PROJECT,
      LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS,
      LOOM_CONFIG.STORAGE_KEYS.PENDING_SYNC,
    ]);
  },

  async getPendingSync() {
    const key = LOOM_CONFIG.STORAGE_KEYS.PENDING_SYNC;
    const result = await chrome.storage.local.get(key);
    return result[key] || [];
  },

  async enqueuePendingSync(chatUrl, message) {
    const key = LOOM_CONFIG.STORAGE_KEYS.PENDING_SYNC;
    const queue = await this.getPendingSync();
    const identity = LoomShared.messageIdentity(chatUrl, message);
    const alreadyQueued = queue.some(function(item) {
      return item.identity === identity;
    });
    if (!alreadyQueued) {
      queue.push({
        identity: identity,
        chatUrl: normalizeChatUrl(chatUrl),
        message: message,
        queuedAt: new Date().toISOString(),
        attempts: 0,
      });
      await chrome.storage.local.set({ [key]: queue });
    }
  },

  async replacePendingSync(queue) {
    const key = LOOM_CONFIG.STORAGE_KEYS.PENDING_SYNC;
    await chrome.storage.local.set({ [key]: queue });
  },

  async removeChatLink(chatUrl) {
    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    const normalized = normalizeChatUrl(chatUrl);
    delete links[normalized];
    delete links[chatUrl];
    delete links[normalized + '/'];
    await chrome.storage.local.set({ [key]: links });
  },

  /**
   * Clear stored credentials.
   */
  async clearCredentials() {
    const key = LOOM_CONFIG.STORAGE_KEYS.AGENT_CREDENTIALS;
    await chrome.storage.local.remove(key);
  },

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
};
