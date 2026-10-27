const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('node:path');
const { spawn } = require('node:child_process');
const dictation = require('./dictation.cjs');

const BACKEND_PORT = process.env.VOXWELL_PORT || '8765';
// uv must trust the OS certificate store, or installing/updating dependencies fails behind
// TLS-inspecting proxies and antivirus.
const UV_TLS = { UV_SYSTEM_CERTS: '1' };
let backend;
let win;

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
  backend = spawn('uv', ['run', 'voxwell'], {
    cwd: path.join(__dirname, '..', '..', 'backend'),
    env: { ...UV_TLS, ...process.env, VOXWELL_PORT: BACKEND_PORT, VOXWELL_EXIT_WITH_PARENT: '1' },
    stdio: ['pipe', 'inherit', 'inherit'],
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true },
  });
  if (process.env.VOXWELL_DEV) win.loadURL('http://localhost:5173');
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  win.webContents.on('did-start-loading', () => { authReady = false; });
  return win;
}

app.whenReady().then(() => {
  if (!primary) return;
  startBackend();
  dictation.register(createWindow());
  const url = authUrlIn(process.argv);
  if (url) deliverAuthUrl(url);
});

app.on('will-quit', () => {
  dictation.unregister();
  if (backend) {
    backend.stdin.end();
    backend.kill();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
