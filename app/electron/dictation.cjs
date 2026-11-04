// Main-process side of dictation: global shortcut, text delivery and the status overlay window.
// Owned by the dictation feature; main.cjs only calls register/unregister.
const path = require('node:path');
const { BrowserWindow, globalShortcut, ipcMain, clipboard, screen } = require('electron');

const SHORTCUT = 'CommandOrControl+Shift+Space';
const OVERLAY_SIZE = { width: 420, height: 64 };
const OVERLAY_BOTTOM_GAP = 24;
let registered = false;
let overlay = null;
let overlayReady = false;
let status = null;

// Bottom centre of the screen the pointer is on, which is most likely where the user is working.
function placeOverlay() {
  const { workArea } = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  overlay.setBounds({
    ...OVERLAY_SIZE,
    x: Math.round(workArea.x + (workArea.width - OVERLAY_SIZE.width) / 2),
    y: workArea.y + workArea.height - OVERLAY_SIZE.height - OVERLAY_BOTTOM_GAP,
  });
}

function createOverlay(url) {
  overlay = new BrowserWindow({
    ...OVERLAY_SIZE,
    show: false,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    // Never takes focus, so the app being dictated into keeps its cursor. Buttons still click.
    focusable: false,
    ...(process.platform === 'darwin' ? { type: 'panel' } : {}),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      // Nobody clicks in this window before the waveform starts, and it must not idle while unfocused.
      autoplayPolicy: 'no-user-gesture-required',
      backgroundThrottling: false,
    },
  });
  overlay.setAlwaysOnTop(true, 'screen-saver');
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true });
  overlay.on('closed', () => {
    overlay = null;
    overlayReady = false;
  });
  overlay.loadURL(url);
}

function presentStatus() {
  if (!overlay || !overlayReady) return;
  overlay.webContents.send('dictation:status', status); // null too, so the waveform lets go of the microphone
  if (!status) overlay.hide();
  else if (!overlay.isVisible()) {
    placeOverlay();
    overlay.showInactive();
  }
}

function register(win, overlayUrl) {
  // Never simulate keystrokes into other apps: no cross-platform way without native code.
  ipcMain.removeHandler('dictation:deliver');
  ipcMain.handle('dictation:deliver', (_event, text) => {
    if (typeof text !== 'string' || !text) return;
    clipboard.writeText(text);
  });

  ipcMain.removeAllListeners('dictation:status');
  ipcMain.on('dictation:status', (event, next) => {
    if (event.sender !== win.webContents) return;
    status = next;
    if (status && !overlay) createOverlay(overlayUrl);
    presentStatus();
  });

  ipcMain.removeAllListeners('dictation:overlay-action');
  ipcMain.on('dictation:overlay-action', (event, action) => {
    if (!overlay || event.sender !== overlay.webContents) return;
    if (action === 'ready') {
      overlayReady = true;
      presentStatus();
    } else if (action === 'dismiss') {
      status = null;
      presentStatus();
    } else if (!win.isDestroyed() && (action === 'stop' || action === 'cancel')) {
      win.webContents.send(action === 'stop' ? 'dictation:toggle' : 'dictation:cancel');
    }
  });

  // A hidden overlay still counts as an open window, and would keep the app from quitting.
  win.on('closed', () => overlay?.destroy());

  try {
    registered = globalShortcut.register(SHORTCUT, () => {
      if (!win.isDestroyed()) win.webContents.send('dictation:toggle');
    });
  } catch (err) {
    registered = false;
    console.error('[dictation] shortcut registration threw:', err);
  }
  if (!registered) console.error(`[dictation] could not register ${SHORTCUT}; use the in-app Record button`);
}

function unregister() {
  if (registered) globalShortcut.unregister(SHORTCUT);
  registered = false;
  ipcMain.removeHandler('dictation:deliver');
  ipcMain.removeAllListeners('dictation:status');
  ipcMain.removeAllListeners('dictation:overlay-action');
  overlay?.destroy();
}

module.exports = { register, unregister };
