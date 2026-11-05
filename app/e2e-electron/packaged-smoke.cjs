// Checks a built installer's unpacked app: everything it needs is inside, the bundled uv runs, and a
// first launch opens the setup screen, not a blank window. Run after `electron-builder`.
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron: electron } = require('@playwright/test');

const release = path.join(__dirname, '..', 'release');
const mac = process.arch === 'arm64' ? 'mac-arm64' : 'mac';
const [resources, executable] = {
  win32: [path.join(release, 'win-unpacked', 'resources'), path.join(release, 'win-unpacked', 'Voxwell.exe')],
  darwin: [path.join(release, mac, 'Voxwell.app', 'Contents', 'Resources'), path.join(release, mac, 'Voxwell.app', 'Contents', 'MacOS', 'Voxwell')],
  linux: [path.join(release, 'linux-unpacked', 'resources'), path.join(release, 'linux-unpacked', 'voxwell')],
}[process.platform];

function check(condition, what) {
  if (!condition) throw new Error(`Packaged app: ${what}`);
  console.log(`ok: ${what}`);
}

(async () => {
  for (const file of ['backend/pyproject.toml', 'backend/uv.lock', 'backend/voxwell/main.py', 'uv/LICENSE-MIT']) {
    check(fs.existsSync(path.join(resources, file)), `has ${file}`);
  }
  check(!fs.existsSync(path.join(resources, 'backend', 'tests')), 'leaves the backend tests out');
  check(!fs.existsSync(path.join(resources, 'backend', '.venv')), 'leaves the development packages out');
  const uv = path.join(resources, 'uv', process.platform === 'win32' ? 'uv.exe' : 'uv');
  check(/^uv \d/.test(execFileSync(uv, ['--version']).toString()), 'the bundled uv runs');

  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'voxwell-smoke-'));
  const app = await electron.launch({
    executablePath: executable,
    args: [`--user-data-dir=${userData}`, ...(process.platform === 'linux' ? ['--no-sandbox'] : [])],
    env: { ...process.env, VOXWELL_PORT: '8797' },
  });
  try {
    const page = await app.firstWindow();
    await page.getByRole('heading', { name: /^Setting up Voxwell$|^Setup didn't finish$/ }).waitFor({ timeout: 30000 });
    check(true, 'a first launch opens the setup screen');
  } finally {
    await app.close().catch(() => {});
    fs.rmSync(userData, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
  }
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
