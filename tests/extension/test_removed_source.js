const assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../../extension');
const chatUrl = 'https://claude.ai/chat/removed';
const otherUrl = 'https://claude.ai/chat/kept';
const projectId = '6ae9b8ef-64ac-46e2-bffc-fe58aeecde0b';

test('a removed browser chat is unlinked and its retry queue is cleared', async () => {
  const data = {
    loom_chat_links: {
      [chatUrl]: { projectId, projectName: 'Test' },
      [otherUrl]: { projectId, projectName: 'Test' },
    },
    loom_project_credentials: { [projectId]: { agent_id: 'agent', api_key: 'key' } },
    loom_pending_sync: [
      { chatUrl, message: { role: 'user', content: 'removed', index: 1 } },
      { chatUrl: otherUrl, message: { role: 'user', content: 'kept', index: 1 } },
    ],
  };
  let listener;
  let requests = 0;
  const chrome = {
    storage: { local: {
      async get(key) { return { [key]: data[key] }; },
      async set(values) { Object.assign(data, values); },
    } },
    runtime: {
      id: 'extension-id',
      onMessage: { addListener(callback) { listener = callback; } },
      onInstalled: { addListener() {} },
    },
    alarms: { get(_name, callback) { callback({}); }, onAlarm: { addListener() {} } },
    contextMenus: { onClicked: { addListener() {} } },
    action: { setBadgeBackgroundColor() {} },
  };
  const context = vm.createContext({
    chrome, crypto: webcrypto, TextEncoder, URL, Response,
    console: { log() {}, info() {} },
    async fetch() {
      requests += 1;
      return new Response(JSON.stringify({ detail: 'SOURCE_REMOVED' }), {
        status: 400, headers: { 'Content-Type': 'application/json' },
      });
    },
  });
  context.importScripts = (...names) => {
    for (const name of names) {
      vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context);
    }
  };
  vm.runInContext(fs.readFileSync(path.join(root, 'background.js'), 'utf8'), context);

  function send(message) {
    return new Promise((resolve) => listener(message, { id: chrome.runtime.id }, resolve));
  }
  const first = await send({
    type: 'SYNC_MESSAGES', chatUrl,
    messages: [{ role: 'user', content: 'removed', index: 1 }],
  });
  assert.equal(first.removed, true);
  assert.equal(data.loom_chat_links[chatUrl], undefined);
  assert.deepEqual(data.loom_pending_sync.map(item => item.chatUrl), [otherUrl]);

  const second = await send({
    type: 'SYNC_MESSAGES', chatUrl,
    messages: [{ role: 'user', content: 'future', index: 2 }],
  });
  assert.equal(second.synced, 0);
  assert.equal(requests, 1);
});
