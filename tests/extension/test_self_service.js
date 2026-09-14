const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../..');

test('extension uses Google auth and never creates projects', () => {
  const popup = fs.readFileSync(path.join(root, 'extension/popup.html'), 'utf8');
  const worker = fs.readFileSync(path.join(root, 'extension/background.js'), 'utf8');

  assert.match(popup, /id="google-auth-btn"/);
  assert.match(popup, /Continue with Google/);
  assert.match(popup, /loom init &quot;My Project&quot;/);
  assert.doesNotMatch(popup, /id="signup-btn"/);
  assert.doesNotMatch(popup, /id="create-project-btn"/);
  assert.match(worker, /async GOOGLE_AUTH/);
  assert.doesNotMatch(worker, /async SIGNUP/);
  assert.doesNotMatch(worker, /async CREATE_PROJECT/);
  assert.match(worker, /client_kind: 'extension'/);
  assert.match(worker, /CREATE_DASHBOARD_SESSION/);
  assert.doesNotMatch(worker, /fetch\(`\$\{API\}\/v1\/extension\/setup/);
});

test('source and packaged extension stay identical for public onboarding files', () => {
  for (const name of ['background.js', 'content.js', 'popup.js', 'popup.html', 'shared.js', 'storage.js', 'config.js', 'manifest.json']) {
    const source = fs.readFileSync(path.join(root, 'extension', name));
    const packaged = fs.readFileSync(path.join(root, 'loom/browser_extension', name));
    assert.deepEqual(source, packaged, `${name} differs from packaged copy`);
  }
});

test('chat sync authenticates with the linked project credential', () => {
  const worker = fs.readFileSync(path.join(root, 'extension/background.js'), 'utf8');

  assert.match(
    worker,
    /async function syncMessage[\s\S]*?await projectAuthHeaders\(linkInfo\.projectId\)/,
  );
  assert.doesNotMatch(worker, /linkInfo\.apiKey/);
});

test('open dashboard button opens the user workspace dashboard', () => {
  const config = fs.readFileSync(path.join(root, 'extension/config.js'), 'utf8');
  const popup = fs.readFileSync(path.join(root, 'extension/popup.js'), 'utf8');

  assert.match(config, /DASHBOARD_PATH: '\/v1\/dashboard'/);
  assert.doesNotMatch(config, /DASHBOARD_BASE_PATH/);
  assert.match(popup, /CREATE_DASHBOARD_SESSION/);
  assert.match(popup, /LOOM_CONFIG\.LOOM_SERVER_URL \+ launch\.path/);
  assert.doesNotMatch(popup, /Storage\.getAccount\(\)/);
  assert.doesNotMatch(popup, /#session=/);
  assert.doesNotMatch(popup, /#token=/);
});

test('content sync cleanup tolerates stale records', () => {
  const content = fs.readFileSync(path.join(root, 'extension/content.js'), 'utf8');

  assert.match(content, /function releaseRecords\(records\) \{\s+if \(!Array\.isArray\(records\)\) return;/);
  assert.match(content, /if \(!record \|\| !record\.identity\) return;/);
  assert.match(content, /if \(!el \|\| typeof el !== 'object'\) return;/);
  assert.match(content, /if \(el\.dataset\) delete el\.dataset\.loomPending;/);
});

test('content script shuts down cleanly when an extension reload invalidates its context', () => {
  const content = fs.readFileSync(path.join(root, 'extension/content.js'), 'utf8');

  assert.match(content, /function extensionContextAvailable\(\)/);
  assert.match(content, /function deactivateContentScript\(\)/);
  assert.match(content, /stopObserver\(\);\s+window\.removeEventListener\('popstate'/);
  assert.match(content, /contextInvalidated: true/);
  assert.match(content, /if \(!contentScriptActive\) return Promise\.resolve\(0\);/);
  assert.match(content, /if \(contentScriptActive && linkedProjectId === projectId\) startObserver\(\);/);
  assert.doesNotMatch(content, /console\.warn/);
});

test('content message listener ignores malformed messages and rescans only linked chats', () => {
  const content = fs.readFileSync(path.join(root, 'extension/content.js'), 'utf8');

  assert.match(content, /if \(!contentScriptActive \|\| !msg \|\| typeof msg\.type !== 'string'\) return false;/);
  assert.match(content, /if \(linkedProjectId\) \{\s+activateLinkedConversation\(linkedProjectId\);\s+\} else \{\s+checkLink\(\);/);
});

test('content script does not cover chat pages with link banners', () => {
  const content = fs.readFileSync(path.join(root, 'extension/content.js'), 'utf8');

  assert.match(content, /function dismissLinkBanner\(\)/);
  assert.doesNotMatch(content, /function showLinkPrompt/);
  assert.doesNotMatch(content, /function showLinkedConfirmation/);
  assert.doesNotMatch(content, /document\.body\.prepend\(banner\)/);
  assert.doesNotMatch(content, /position: fixed; top: 0/);
  assert.doesNotMatch(content, /#064e3b/);
});

test('background router always responds to extension messages', () => {
  const worker = fs.readFileSync(path.join(root, 'extension/background.js'), 'utf8');

  assert.match(worker, /if \(!msg \|\| !msg\.type\)/);
  assert.match(worker, /Unsupported message type/);
  assert.match(worker, /return false;/);
});
