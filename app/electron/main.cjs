const { app, BrowserWindow } = require('electron');
const path = require('node:path');
const { spawn } = require('node:child_process');
const dictation = require('./dictation.cjs');

const BACKEND_PORT = process.env.VOXWELL_PORT || '8765';
// uv must trust the OS certificate store, or installing/updating dependencies fails behind
// TLS-inspecting proxies and antivirus.
const UV_TLS = { UV_SYSTEM_CERTS: '1' };
let backend;

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
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true },
  });
  if (process.env.VOXWELL_DEV) win.loadURL('http://localhost:5173');
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  return win;
}

app.whenReady().then(() => {
  startBackend();
  dictation.register(createWindow());
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
