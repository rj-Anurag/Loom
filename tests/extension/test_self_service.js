const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../..');

test('extension exposes account onboarding and automatic credential handlers', () => {
  const popup = fs.readFileSync(path.join(root, 'extension/popup.html'), 'utf8');
  const worker = fs.readFileSync(path.join(root, 'extension/background.js'), 'utf8');

  assert.match(popup, /id="signup-btn"/);
  assert.match(popup, /id="login-btn"/);
  assert.match(worker, /async SIGNUP/);
  assert.match(worker, /async LOGIN/);
  assert.match(worker, /client_kind: 'extension'/);
  assert.doesNotMatch(worker, /fetch\(`\$\{API\}\/v1\/extension\/setup/);
});

test('source and packaged extension stay identical for public onboarding files', () => {
  for (const name of ['background.js', 'popup.js', 'popup.html', 'storage.js', 'config.js']) {
    const source = fs.readFileSync(path.join(root, 'extension', name));
    const packaged = fs.readFileSync(path.join(root, 'loom/browser_extension', name));
    assert.deepEqual(source, packaged, `${name} differs from packaged copy`);
  }
});
