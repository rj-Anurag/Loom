/**
 * Loom Extension — Chrome Storage Helpers
 *
 * Thin wrappers around chrome.storage.local for reading / writing
 * chat-link mappings and agent credentials.
 */

const Storage = {
  /**
   * Get project info linked to a chat URL.
   * @param {string} chatUrl
   * @returns {Promise<{projectId: string, projectName: string}|null>}
   */
  async getProjectForChat(chatUrl) {
    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    const entry = links[chatUrl];
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
    links[chatUrl] = { projectId, projectName: projectName || projectId };
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

  /**
   * Clear stored credentials.
   */
  async clearCredentials() {
    const key = LOOM_CONFIG.STORAGE_KEYS.AGENT_CREDENTIALS;
    await chrome.storage.local.remove(key);
  },
};
