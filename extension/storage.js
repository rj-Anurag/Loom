/**
 * Loom Extension — Chrome Storage Helpers
 *
 * Thin wrappers around chrome.storage.local for reading / writing
 * chat-link mappings and agent credentials.
 */

const Storage = {
  /**
   * Get the project ID linked to a chat URL.
   * @param {string} chatUrl
   * @returns {Promise<string|null>}
   */
  async getProjectForChat(chatUrl) {
    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    return links[chatUrl] || null;
  },

  /**
   * Store a chat URL → project_id mapping.
   * @param {string} chatUrl
   * @param {string} projectId
   */
  async setChatLink(chatUrl, projectId) {
    const key = LOOM_CONFIG.STORAGE_KEYS.CHAT_LINKS;
    const result = await chrome.storage.local.get(key);
    const links = result[key] || {};
    links[chatUrl] = projectId;
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
