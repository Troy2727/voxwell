// Run with: node --test electron/
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { afterEach, beforeEach, test } = require('node:test');
const { closeAction, loadPrefs, savePrefs } = require('./background.cjs');

let root;
beforeEach(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'voxwell-background-')); });
afterEach(() => fs.rmSync(root, { recursive: true, force: true }));

test('closing hides the window only when the setting is on, a tray exists and the app is not quitting', () => {
  for (const enabled of [true, false]) {
    for (const trayAvailable of [true, false]) {
      for (const quitting of [true, false]) {
        const want = enabled && trayAvailable && !quitting ? 'hide' : 'close';
        assert.equal(closeAction({ enabled, trayAvailable, quitting }), want, JSON.stringify({ enabled, trayAvailable, quitting }));
      }
    }
  }
});

test('a missing, broken or non-boolean preference counts as off', () => {
  const file = path.join(root, 'preferences.json');
  assert.deepEqual(loadPrefs(file), { runInBackground: false });
  for (const text of ['{not json', 'null', '{"runInBackground":"true"}', '{"runInBackground":1}', '{}']) {
    fs.writeFileSync(file, text);
    assert.deepEqual(loadPrefs(file), { runInBackground: false }, text);
  }
});

test('a saved preference reads back', () => {
  const file = path.join(root, 'preferences.json');
  savePrefs(file, { runInBackground: true });
  assert.deepEqual(loadPrefs(file), { runInBackground: true });
  savePrefs(file, { runInBackground: false });
  assert.deepEqual(loadPrefs(file), { runInBackground: false });
});

test('saving to a folder that does not exist throws, so the window never confirms an unsaved value', () => {
  assert.throws(() => savePrefs(path.join(root, 'missing', 'preferences.json'), { runInBackground: true }));
});
