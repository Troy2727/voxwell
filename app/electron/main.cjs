const { app, BrowserWindow, ipcMain, net, protocol, shell } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { spawn } = require('node:child_process');
const dictation = require('./dictation.cjs');
const { enginePaths, install, isReady } = require('./backend-setup.cjs');

const BACKEND_PORT = process.env.VOXWELL_PORT || '8765';
// uv must trust the OS certificate store, or installing/updating dependencies fails behind
// TLS-inspecting proxies and antivirus.
const UV_TLS = { UV_SYSTEM_CERTS: '1' };
let backend;
let setupChild;
let win;

// An installed app has its own uv and backend; a source checkout uses the developer's.
const engine = app.isPackaged
  ? enginePaths({ resourcesPath: process.resourcesPath, userData: app.getPath('userData'), version: app.getVersion() })
  : null;

// The built UI loads from app://voxwell, an origin of its own that the backend allows. From file://
// its origin would be "null", which sandboxed iframes on any website share.
const APP_SCHEME = 'app';
const DIST = path.join(__dirname, '..', 'dist');
protocol.registerSchemesAsPrivileged([
  { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

function serveDist(request) {
  const file = path.join(DIST, decodeURIComponent(new URL(request.url).pathname));
  if (path.relative(DIST, file).startsWith('..')) return new Response('Not found', { status: 404 });
  return net.fetch(pathToFileURL(file).toString());
}

// Account emails and Google sign-in return to voxwell://auth/callback; the OS hands those links to
// this app (a second instance on Windows/Linux, 'open-url' on macOS) and the window finishes sign-in.
const AUTH_SCHEME = 'voxwell';
let pendingAuthUrl = null;
let authReady = false;

if (process.defaultApp) app.setAsDefaultProtocolClient(AUTH_SCHEME, process.execPath, [path.resolve(process.argv[1])]);
else app.setAsDefaultProtocolClient(AUTH_SCHEME);

const authUrlIn = (argv) => argv.find((arg) => arg.startsWith(`${AUTH_SCHEME}://`));

function deliverAuthUrl(url) {
  pendingAuthUrl = url;
  if (win && authReady) {
    win.webContents.send('auth:callback', pendingAuthUrl);
    pendingAuthUrl = null;
  }
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
}

// One instance owns the window and the backend port; later launches pass their link to it and exit.
const primary = app.requestSingleInstanceLock();
if (!primary) app.quit();
app.on('second-instance', (_event, argv) => {
  const url = authUrlIn(argv);
  if (url) deliverAuthUrl(url);
  else if (win) win.focus();
});
app.on('open-url', (event, url) => {
  event.preventDefault();
  deliverAuthUrl(url);
});
ipcMain.on('auth:ready', () => {
  authReady = true;
  if (pendingAuthUrl) deliverAuthUrl(pendingAuthUrl);
});
ipcMain.handle('auth:open', (_event, url) => {
  if (new URL(url).protocol !== 'https:') throw new Error('Only https links open in the browser.');
  return shell.openExternal(url);
});

function startBackend() {
  // The backend stops when its stdin closes, which the OS does however this app ends. Killing
  // `uv` alone is not enough: on Windows the server process it started would keep running.
  const [command, args, cwd] = engine
    ? [engine.uv, ['run', '--no-sync', 'voxwell'], engine.project]
    : ['uv', ['run', 'voxwell'], path.join(__dirname, '..', '..', 'backend')];
  backend = spawn(command, args, {
    cwd,
    env: { ...UV_TLS, ...process.env, ...engine?.env, VOXWELL_PORT: BACKEND_PORT, VOXWELL_EXIT_WITH_PARENT: '1' },
    stdio: ['pipe', 'inherit', 'inherit'],
    windowsHide: true,
  });
}

/** First launch: shows progress until the engine is installed, and offers another try if it fails. */
async function runSetup() {
  const setupWin = new BrowserWindow({
    width: 560,
    height: 420,
    resizable: false,
    title: 'Setting up Voxwell',
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'setup-preload.cjs'), contextIsolation: true },
  });
  const send = (channel, value) => {
    if (!setupWin.isDestroyed()) setupWin.webContents.send(channel, value);
  };
  ipcMain.on('setup:quit', () => app.quit());
  await setupWin.loadFile(path.join(__dirname, 'setup.html'));
  for (;;) {
    try {
      await install(engine, { onLine: (line) => send('setup:progress', line), onChild: (child) => { setupChild = child; } });
      setupChild = null;
      return setupWin;
    } catch (e) {
      setupChild = null;
      send('setup:failed', e.message);
      await new Promise((resolve) => ipcMain.once('setup:retry', resolve));
    }
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true },
  });
  if (process.env.VOXWELL_DEV) win.loadURL('http://localhost:5173');
  else win.loadURL(`${APP_SCHEME}://voxwell/index.html`);
  win.webContents.on('did-start-loading', () => { authReady = false; });
  return win;
}

app.whenReady().then(async () => {
  if (!primary) return;
  protocol.handle(APP_SCHEME, serveDist);
  const setupWin = engine && !isReady(engine) ? await runSetup() : null;
  startBackend();
  dictation.register(
    createWindow(),
    process.env.VOXWELL_DEV ? 'http://localhost:5173/overlay.html' : `${APP_SCHEME}://voxwell/overlay.html`,
  );
  setupWin?.close(); // after the main window opens, or closing the last window would quit
  const url = authUrlIn(process.argv);
  if (url) deliverAuthUrl(url);
});

app.on('will-quit', () => {
  dictation.unregister();
  setupChild?.kill();
  if (backend) {
    backend.stdin.end();
    backend.kill();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
