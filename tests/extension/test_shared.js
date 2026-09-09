const assert = require('node:assert/strict');
const test = require('node:test');

const {
  isLoomApiKey,
  messageIdentity,
  resolveProjectChoice,
} = require('../../extension/shared.js');

const PROJECT_A = 'cae241fd-7c17-4d0f-9529-ea74648b61ac';
const PROJECT_B = '6f4f8594-9237-4609-8378-a092de7604a1';

test('verified project can remain selected while its matching ID is visible', () => {
  assert.equal(resolveProjectChoice(PROJECT_A, PROJECT_A), PROJECT_A);
});

test('selection and a different direct project ID are rejected', () => {
  assert.throws(
    () => resolveProjectChoice(PROJECT_A, PROJECT_B),
    /different projects/i,
  );
});

test('a direct project ID works without a dropdown selection', () => {
  assert.equal(resolveProjectChoice('', `  ${PROJECT_A}  `), PROJECT_A);
});

test('API key validation accepts opaque keys and deployed legacy UUID keys', () => {
  assert.equal(isLoomApiKey(`loom_${'A'.repeat(43)}`), true);
  assert.equal(isLoomApiKey(PROJECT_A), true);
  assert.equal(isLoomApiKey('not-a-key'), false);
});

test('message identity is stable across URL query and fragment changes', () => {
  const message = { index: 2, role: 'assistant', content: 'Same answer' };
  assert.equal(
    messageIdentity('https://claude.ai/chat/abc?foo=1#bar', message),
    messageIdentity('https://claude.ai/chat/abc', message),
  );
});

test('repeated messages at different positions have different identities', () => {
  const first = { index: 2, role: 'user', content: 'Please retry' };
  const second = { index: 4, role: 'user', content: 'Please retry' };
  assert.notEqual(
    messageIdentity('https://claude.ai/chat/abc', first),
    messageIdentity('https://claude.ai/chat/abc', second),
  );
});
