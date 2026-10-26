const { app, BrowserWindow } = require('electron');
const path = require('node:path');
const { spawn } = require('node:child_process');
const dictation = require('./dictation.cjs');

const BACKEND_PORT = process.env.VOXWELL_PORT || '8765';
let backend;

function startBackend() {
  backend = spawn('uv', ['run', 'voxwell'], {
    cwd: path.join(__dirname, '..', '..', 'backend'),
    env: { ...process.env, VOXWELL_PORT: BACKEND_PORT },
    stdio: 'inherit',
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
  if (backend) backend.kill();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
