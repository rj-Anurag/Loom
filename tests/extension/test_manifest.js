const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../..');
const manifest = JSON.parse(
  fs.readFileSync(path.join(root, 'extension/manifest.json'), 'utf8'),
);

test('content scanner loads shared identity helpers first', () => {
  assert.deepEqual(manifest.content_scripts[0].js, ['shared.js', 'content.js']);
});

test('extension can inject its scanner into an already-open conversation', () => {
  assert.ok(manifest.permissions.includes('scripting'));
  const popup = fs.readFileSync(path.join(root, 'extension/popup.html'), 'utf8');
  assert.ok(popup.indexOf('shared.js') < popup.indexOf('popup.js'));
});
