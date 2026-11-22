// Run in background: with the setting on, closing the main window hides Voxwell in the system tray,
// so the backend and its jobs keep running. Off by default; then closing behaves as before.
const fs = require('node:fs');
const path = require('node:path');

const PREFS_FILE = 'preferences.json';
const NO_TRAY = "This computer can't show a tray icon.";

let win = null;
let tray = null;
let enabled = false;
let quitting = false;

/** What closing the main window does: 'hide' keeps the app running in the tray. */
function closeAction({ enabled, trayAvailable, quitting }) {
  return enabled && trayAvailable && !quitting ? 'hide' : 'close';
}

/** Saved preferences; a missing or unreadable file, or anything but true, counts as off. */
function loadPrefs(file) {
  try {
    return { runInBackground: JSON.parse(fs.readFileSync(file, 'utf8')).runInBackground === true };
  } catch {
    return { runInBackground: false };
  }
}

function savePrefs(file, prefs) {
  fs.writeFileSync(file, JSON.stringify(prefs));
}

/** Brings the main window back: from the tray, a second launch or the macOS Dock. */
function show() {
  if (!win || win.isDestroyed()) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function addTray() {
  const { app, Menu, Tray } = require('electron');
  if (tray) return;
  tray = new Tray(path.join(__dirname, 'tray.png'));
  tray.setToolTip('Voxwell');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open Voxwell', click: show },
    { label: 'Quit Voxwell', click: () => app.quit() },
  ]));
  tray.on('click', show);
  tray.on('double-click', show);
}

function removeTray() {
  tray?.destroy();
  tray = null;
}

function register(mainWindow) {
  const { app, ipcMain } = require('electron');
  win = mainWindow;
  const file = path.join(app.getPath('userData'), PREFS_FILE);
  enabled = loadPrefs(file).runInBackground;
  if (enabled) {
    try {
      addTray();
    } catch (e) {
      console.error('Run in background: no tray icon, so closing the window quits.', e);
      removeTray();
    }
  }

  app.on('before-quit', () => { quitting = true; });
  win.on('close', (event) => {
    if (closeAction({ enabled, trayAvailable: Boolean(tray), quitting }) !== 'hide') return;
    event.preventDefault();
    win.hide();
  });

  const fromMainWindow = (event) => {
    if (event.sender !== win.webContents) throw new Error('Not allowed.');
  };
  ipcMain.handle('background:get', (event) => {
    fromMainWindow(event);
    return enabled;
  });
  ipcMain.handle('background:set', (event, value) => {
    fromMainWindow(event);
    if (typeof value !== 'boolean') throw new Error('Expected true or false.');
    if (value && !tray) {
      try {
        addTray();
      } catch {
        removeTray();
        throw new Error(NO_TRAY);
      }
    }
    try {
      savePrefs(file, { runInBackground: value });
    } catch (e) {
      if (!enabled) removeTray();
      throw e;
    }
    enabled = value;
    if (!enabled) removeTray();
    return enabled;
  });
}

function unregister() {
  removeTray();
}

module.exports = { closeAction, loadPrefs, savePrefs, register, unregister, show };
