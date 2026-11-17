// Run with: node --test electron/
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { paste, pasteCommand } = require('./paste.cjs');

/** Stands in for execFile: records the call and finishes with `err`, so no keys are pressed. */
function fakeRun(err = null) {
  const calls = [];
  const run = (file, args, options, done) => {
    calls.push({ file, args, options });
    setImmediate(() => done(err));
  };
  return { run, calls };
}

const failure = (code) => Object.assign(new Error('failed'), { code });

test('each OS gets its own paste tool', () => {
  const win = pasteCommand('win32', {});
  assert.equal(win.file, 'powershell.exe');
  assert.match(win.args.at(-1), /SendKeys\('\^v'\)/);
  const mac = pasteCommand('darwin', {});
  assert.equal(mac.file, 'osascript');
  assert.match(mac.args.at(-1), /keystroke "v" using command down/);
  assert.deepEqual(pasteCommand('linux', { WAYLAND_DISPLAY: 'wayland-0', DISPLAY: ':0' }), { file: 'wtype', args: ['-M', 'ctrl', 'v', '-m', 'ctrl'] });
  assert.deepEqual(pasteCommand('linux', { DISPLAY: ':0' }), { file: 'xdotool', args: ['key', '--clearmodifiers', 'ctrl+v'] });
  assert.equal(pasteCommand('linux', {}), null);
});

test('a working tool pastes, hidden and with a time limit', async () => {
  const fake = fakeRun();
  assert.deepEqual(await paste({ platform: 'win32', env: {}, run: fake.run }), { pasted: true });
  assert.equal(fake.calls.length, 1);
  assert.equal(fake.calls[0].file, 'powershell.exe');
  assert.equal(fake.calls[0].options.windowsHide, true);
  assert.ok(fake.calls[0].options.timeout > 0);
});

test('a missing tool falls back to the clipboard and says what to install', async () => {
  const fake = fakeRun(failure('ENOENT'));
  assert.deepEqual(await paste({ platform: 'linux', env: { DISPLAY: ':0' }, run: fake.run }), { pasted: false, reason: 'Install xdotool to paste in place.' });
});

test('macOS without Accessibility access says so', async () => {
  const fake = fakeRun(failure(1));
  const result = await paste({ platform: 'darwin', env: {}, run: fake.run });
  assert.equal(result.pasted, false);
  assert.match(result.reason, /Accessibility/);
});

test('other failures and a desktop with no display fall back without running anything odd', async () => {
  const fake = fakeRun(failure(1));
  assert.deepEqual(await paste({ platform: 'win32', env: {}, run: fake.run }), { pasted: false, reason: "Couldn't paste in place." });
  const none = fakeRun();
  const result = await paste({ platform: 'linux', env: {}, run: none.run });
  assert.equal(result.pasted, false);
  assert.ok(result.reason);
  assert.equal(none.calls.length, 0);
});
