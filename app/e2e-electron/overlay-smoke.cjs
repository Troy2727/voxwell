// Drives the built Electron app on this OS: fake backend, fake microphone.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { _electron } = require('@playwright/test');

const APP = path.join(__dirname, '..');
const OUT = path.join(APP, 'overlay-smoke');
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isOverlay = (w) => w.url().includes('overlay.html');
const checks = {};
const note = {};
const check = (name, ok, detail) => {
  checks[name] = Boolean(ok);
  if (detail !== undefined) note[name] = detail;
};

function screen(name) {
  try {
    const file = path.join(OUT, `${process.platform}-${name}.png`);
    if (process.platform === 'darwin') execFileSync('screencapture', ['-x', file]);
    else execFileSync('import', ['-window', 'root', file]);
  } catch (e) {
    note[`screen-${name}`] = String(e).slice(0, 200);
  }
}

const overlayState = (app) => app.evaluate(({ BrowserWindow, screen: s }) => {
  const all = BrowserWindow.getAllWindows();
  const o = all.find((w) => w.webContents.getURL().includes('overlay.html'));
  if (!o) return null;
  const m = all.find((w) => w !== o);
  const { workArea } = s.getDisplayMatching(o.getBounds());
  return { visible: o.isVisible(), focusable: o.isFocusable(), overlayFocused: o.isFocused(), mainFocused: m?.isFocused(), onTop: o.isAlwaysOnTop(), bounds: o.getBounds(), workArea };
});

async function main() {
  const app = await _electron.launch({
    cwd: APP,
    args: ['.', ...(process.platform === 'linux' ? ['--no-sandbox'] : []), '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${path.join(APP, 'e2e', 'fixtures', 'mic.wav')}`],
    env: { ...process.env, VOXWELL_PORT: '18765', VOXWELL_DEV: '', PATH: `${path.join(__dirname, 'bin')}${path.delimiter}${process.env.PATH}` },
  });
  const closed = new Promise((r) => app.process().once('exit', r));
  const page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(async () => { try { return (await fetch(`${window.voxwell.backendUrl}/api/health`)).ok; } catch { return false; } }, null, { timeout: 60000, polling: 500 });
  await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 30000 });
  check('shortcut registered', await app.evaluate(({ globalShortcut }) => globalShortcut.isRegistered('CommandOrControl+Shift+Space')));

  const findOverlay = async (ms) => {
    for (let t = 0; t < ms; t += 250) {
      const w = app.windows().find(isOverlay);
      if (w) return w;
      await sleep(250);
    }
    return null;
  };
  const sendToggle = () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => !w.webContents.getURL().includes('overlay.html')).webContents.send('dictation:toggle'));

  // A real keypress where a test machine can make one; macOS needs Accessibility approval for it.
  let trigger = 'ipc';
  if (process.platform === 'linux') {
    execFileSync('xdotool', ['key', 'ctrl+shift+space']);
    if (await findOverlay(6000)) trigger = 'real keypress';
  }
  if (trigger === 'ipc') await sendToggle();
  note.trigger = trigger;

  const overlay = await findOverlay(20000);
  check('overlay window opened', overlay);
  await overlay.getByRole('button', { name: 'Stop' }).waitFor({ timeout: 20000 });
  await sleep(2500);
  const st = await overlayState(app);
  note.state = st;
  check('visible', st.visible);
  check('never takes focus', !st.focusable && !st.overlayFocused);
  check('always on top', st.onTop);
  const centreOff = Math.abs(st.bounds.x + st.bounds.width / 2 - (st.workArea.x + st.workArea.width / 2));
  const bottomGap = st.workArea.y + st.workArea.height - (st.bounds.y + st.bounds.height);
  check('bottom centre', centreOff <= 1 && bottomGap >= 0 && bottomGap <= 60, { centreOff, bottomGap });
  // Keeps looking, since a slow machine may not have painted yet. Silent bars count: macOS test
  // machines give the fake microphone no signal, so this can't check that the bars react to sound.
  check('waveform drawn', await overlay.waitForFunction(() => {
    const c = document.querySelector('canvas');
    if (!c) return false;
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true;
    return false;
  }, null, { timeout: 10000, polling: 250 }).then(() => true, () => false));
  await overlay.screenshot({ path: path.join(OUT, `${process.platform}-pill-recording.png`) });
  screen('recording');

  await overlay.getByRole('button', { name: 'Stop' }).click();
  await overlay.getByText(/Copied\./).waitFor({ timeout: 30000 });
  await overlay.screenshot({ path: path.join(OUT, `${process.platform}-pill-copied.png`) });
  screen('copied');
  const clip = await app.evaluate(({ clipboard }) => clipboard.readText());
  check('Stop puts the text on the clipboard', clip === 'Overlay smoke test transcript.', clip);
  await sleep(4500);
  check('hides itself after the result', !(await overlayState(app)).visible);

  await app.evaluate(({ clipboard }) => clipboard.writeText('marker'));
  await sendToggle();
  await overlay.getByRole('button', { name: 'Cancel' }).waitFor({ timeout: 20000 });
  await sleep(1000);
  await overlay.getByRole('button', { name: 'Cancel' }).click();
  await sleep(1000);
  check('Cancel hides it', !(await overlayState(app)).visible);
  check('Cancel leaves the clipboard', (await app.evaluate(({ clipboard }) => clipboard.readText())) === 'marker');
  check('microphone released', (await overlay.locator('canvas').count()) === 0);

  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => !w.webContents.getURL().includes('overlay.html')).close());
  if (process.platform === 'darwin') {
    // macOS apps stay running with no windows, by design in main.cjs. The overlay must still go.
    await sleep(2000);
    check('closing the main window removes the overlay', (await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length)) === 0);
    await app.close();
  } else {
    const code = await Promise.race([closed, sleep(15000).then(() => 'still running')]);
    check('closing the main window quits the app', code === 0, code);
    if (code === 'still running') await app.close();
  }
}

main()
  .catch((e) => {
    checks['ran to the end'] = false;
    note.error = String(e).slice(0, 800);
  })
  .finally(() => {
    screen('final');
    const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
    const report = { platform: process.platform, arch: process.arch, passed: Object.keys(checks).length - failed.length, failed, checks, note };
    fs.writeFileSync(path.join(OUT, `${process.platform}-report.json`), JSON.stringify(report, null, 1));
    console.log(JSON.stringify(report, null, 1));
    process.exit(failed.length ? 1 : 0);
  });
