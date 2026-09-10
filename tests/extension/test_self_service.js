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
  assert.doesNotMatch(worker, /fetch\(`\$\{API\}\/v1\/extension\/setup/);
});

test('source and packaged extension stay identical for public onboarding files', () => {
  for (const name of ['background.js', 'popup.js', 'popup.html', 'storage.js', 'config.js', 'manifest.json']) {
    const source = fs.readFileSync(path.join(root, 'extension', name));
    const packaged = fs.readFileSync(path.join(root, 'loom/browser_extension', name));
    assert.deepEqual(source, packaged, `${name} differs from packaged copy`);
  }
});
