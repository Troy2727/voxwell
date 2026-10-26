// Main-process side of dictation: global shortcut and text delivery.
// Owned by the dictation feature; main.cjs only calls register/unregister.
const { globalShortcut, ipcMain, clipboard, Notification } = require('electron');

const SHORTCUT = 'CommandOrControl+Shift+Space';
const PASTE_KEY = process.platform === 'darwin' ? 'Cmd+V' : 'Ctrl+V';
let registered = false;

function register(win) {
  // Never simulate keystrokes into other apps: no cross-platform way without native code.
  ipcMain.removeHandler('dictation:deliver');
  ipcMain.handle('dictation:deliver', (_event, text) => {
    if (typeof text !== 'string' || !text) return;
    clipboard.writeText(text);
    if (Notification.isSupported()) {
      new Notification({ title: 'Voxwell', body: `Copied — press ${PASTE_KEY} to paste`, silent: true }).show();
    }
  });

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
}

module.exports = { register, unregister };
