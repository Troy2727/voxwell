// Run with: node --test electron/
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { afterEach, beforeEach, test } = require('node:test');
const { enginePaths, install, isReady, SetupError } = require('./backend-setup.cjs');

let root;
let paths;

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'voxwell-setup-'));
  const resourcesPath = path.join(root, 'resources');
  fs.mkdirSync(path.join(resourcesPath, 'backend', 'voxwell'), { recursive: true });
  fs.writeFileSync(path.join(resourcesPath, 'backend', 'pyproject.toml'), 'name = "voxwell"');
  fs.writeFileSync(path.join(resourcesPath, 'backend', 'voxwell', 'main.py'), 'print("hi")');
  paths = enginePaths({ resourcesPath, userData: path.join(root, 'user data'), version: '1.2.3', platform: 'win32' });
});

afterEach(() => fs.rmSync(root, { recursive: true, force: true }));

/** Stands in for spawning uv: reports `lines`, then exits with `code`. */
function fakeUv({ code = 0, lines = [] } = {}) {
  const calls = [];
  const start = (command, args, options) => {
    calls.push({ command, args, options });
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    setImmediate(() => {
      for (const line of lines) child.stderr.emit('data', `${line}\n`);
      child.emit('close', code);
    });
    return child;
  };
  return { start, calls };
}

test('paths use the bundled uv and keep everything in the user data folder', () => {
  assert.equal(paths.uv, path.join(root, 'resources', 'uv', 'uv.exe'));
  assert.equal(enginePaths({ resourcesPath: 'r', userData: 'u', version: '1', platform: 'darwin' }).uv, path.join('r', 'uv', 'uv'));
  for (const folder of [paths.project, paths.env.UV_PROJECT_ENVIRONMENT, paths.env.UV_PYTHON_INSTALL_DIR]) {
    assert.ok(folder.startsWith(path.join(root, 'user data')), folder);
  }
});

test('a good install copies the backend, runs uv there with the locked versions, and is remembered', async () => {
  const uv = fakeUv({ lines: ['Downloading torch (2.4GiB)', 'Installed 180 packages'] });
  const seen = [];
  assert.equal(isReady(paths), false);
  await install(paths, { start: uv.start, onLine: (l) => seen.push(l), minFree: 0 });
  assert.equal(isReady(paths), true);
  assert.deepEqual(uv.calls[0].args, ['sync', '--frozen', '--no-dev']);
  assert.equal(uv.calls[0].command, paths.uv);
  assert.equal(uv.calls[0].options.cwd, paths.project);
  assert.equal(uv.calls[0].options.env.UV_SYSTEM_CERTS, '1');
  assert.equal(uv.calls[0].options.windowsHide, true);
  assert.ok(fs.existsSync(path.join(paths.project, 'voxwell', 'main.py')));
  assert.deepEqual(seen, ['Downloading torch (2.4GiB)', 'Installed 180 packages']);
});

test('a failed install says why, is not remembered, and can run again', async () => {
  await assert.rejects(install(paths, { start: fakeUv({ code: 1, lines: ['error: connection reset'] }).start, minFree: 0 }), (e) => {
    assert.ok(e instanceof SetupError);
    assert.match(e.message, /internet connection/);
    assert.match(e.message, /connection reset/);
    return true;
  });
  assert.equal(isReady(paths), false);
  await install(paths, { start: fakeUv().start, minFree: 0 });
  assert.equal(isReady(paths), true);
});

test('uv that can not start is reported, not left hanging', async () => {
  const start = () => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    setImmediate(() => child.emit('error', new Error('ENOENT')));
    return child;
  };
  await assert.rejects(install(paths, { start, minFree: 0 }), /could not start: ENOENT/);
});

test('too little disk space stops before anything downloads', async () => {
  const uv = fakeUv();
  await assert.rejects(install(paths, { start: uv.start, minFree: Number.MAX_SAFE_INTEGER }), /free disk space/);
  assert.equal(uv.calls.length, 0);
});

test('an update needs no free-space check, and removes the old version once the new one works', async () => {
  const older = path.join(paths.home, 'backend-1.0.0');
  fs.mkdirSync(older, { recursive: true });
  fs.mkdirSync(paths.env.UV_PROJECT_ENVIRONMENT, { recursive: true });
  await install(paths, { start: fakeUv().start, minFree: Number.MAX_SAFE_INTEGER });
  assert.equal(fs.existsSync(older), false);
  assert.equal(fs.existsSync(paths.env.UV_PROJECT_ENVIRONMENT), true, 'the packages are kept');
  assert.equal(isReady(paths), true);
});

test('a failed update keeps the old version', async () => {
  const older = path.join(paths.home, 'backend-1.0.0');
  fs.mkdirSync(older, { recursive: true });
  await assert.rejects(install(paths, { start: fakeUv({ code: 1 }).start, minFree: 0 }));
  assert.equal(fs.existsSync(older), true);
});
