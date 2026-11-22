// Run in background, driven in the built Electron app on this OS: fake backend, fake microphone.
// With the setting saved on, closing the window hides it, the backend and dictation keep working,
// a second launch brings it back, and quitting still quits.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron } = require('@playwright/test');

const APP = path.join(__dirname, '..');
const OUT = path.join(APP, 'overlay-smoke'); // CI uploads this folder when the desktop job fails
fs.mkdirSync(OUT, { recursive: true });
const PORT = '18765';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = {};
const note = {};
const check = (name, ok, detail) => {
  checks[name] = Boolean(ok);
  if (detail !== undefined) note[name] = detail;
};
const healthy = () => fetch(`http://127.0.0.1:${PORT}/api/health`).then((r) => r.ok, () => false);

async function main() {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'voxwell-background-'));
  fs.writeFileSync(path.join(userData, 'preferences.json'), JSON.stringify({ runInBackground: true }));
  const app = await _electron.launch({
    cwd: APP,
    args: ['.', `--user-data-dir=${userData}`, ...(process.platform === 'linux' ? ['--no-sandbox'] : []), '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${path.join(APP, 'e2e', 'fixtures', 'mic.wav')}`],
    env: { ...process.env, VOXWELL_PORT: PORT, VOXWELL_DEV: '', PATH: `${path.join(__dirname, 'bin')}${path.delimiter}${process.env.PATH}` },
  });
  const closed = new Promise((r) => app.process().once('exit', r));
  const page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(async () => { try { return (await fetch(`${window.voxwell.backendUrl}/api/health`)).ok; } catch { return false; } }, null, { timeout: 60000, polling: 500 });
  await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 30000 });
  check('Home shows the setting on', await page.getByRole('checkbox', { name: 'Run in background' }).isChecked({ timeout: 10000 }));

  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => !w.webContents.getURL().includes('overlay.html')).close());
  await sleep(2000);
  const st = await app.evaluate(({ BrowserWindow }) => {
    const w = BrowserWindow.getAllWindows().find((w) => !w.webContents.getURL().includes('overlay.html'));
    return w ? { destroyed: w.isDestroyed(), visible: w.isVisible() } : null;
  });
  note.afterClose = st;
  check('closing hides the window instead of quitting', st && !st.destroyed && !st.visible);
  check('the backend keeps running', await healthy());

  // Dictation from a hidden window: the shortcut's toggle, then Stop in the overlay.
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => !w.webContents.getURL().includes('overlay.html')).webContents.send('dictation:toggle'));
  let overlay = null;
  for (let t = 0; t < 20000 && !overlay; t += 250) {
    overlay = app.windows().find((w) => w.url().includes('overlay.html')) ?? null;
    if (!overlay) await sleep(250);
  }
  check('dictation opens from the hidden window', overlay);
  await overlay.getByRole('button', { name: 'Stop' }).waitFor({ timeout: 20000 });
  await sleep(2500);
  await overlay.getByRole('button', { name: 'Stop' }).click();
  await overlay.getByText(/Copied\./).waitFor({ timeout: 30000 });
  check('dictation works while hidden', (await app.evaluate(({ clipboard }) => clipboard.readText())) === 'Overlay smoke test transcript.');

  // A second launch of Voxwell brings the window back.
  await app.evaluate(({ app: a }) => a.emit('second-instance', {}, [], ''));
  await sleep(1000);
  check('a second launch shows the window again', await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => !w.webContents.getURL().includes('overlay.html')).isVisible()));

  await app.evaluate(({ app: a }) => a.quit());
  const code = await Promise.race([closed, sleep(15000).then(() => 'still running')]);
  check('quitting still quits', code === 0, code);
  if (code === 'still running') await app.close();
}

main()
  .catch((e) => {
    checks['ran to the end'] = false;
    note.error = String(e).slice(0, 800);
  })
  .finally(() => {
    const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
    const report = { platform: process.platform, arch: process.arch, passed: Object.keys(checks).length - failed.length, failed, checks, note };
    fs.writeFileSync(path.join(OUT, `${process.platform}-background-report.json`), JSON.stringify(report, null, 1));
    console.log(JSON.stringify(report, null, 1));
    process.exit(failed.length ? 1 : 0);
  });
