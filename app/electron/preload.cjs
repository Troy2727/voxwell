const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('voxwell', {
  backendUrl: `http://127.0.0.1:${process.env.VOXWELL_PORT || '8765'}`,
  dictation: {
    // Main process sends this when the global dictation shortcut is pressed.
    onToggle: (callback) => {
      const listener = () => callback();
      ipcRenderer.on('dictation:toggle', listener);
      return () => ipcRenderer.removeListener('dictation:toggle', listener);
    },
    // The overlay's Cancel button, relayed by the main process.
    onCancel: (callback) => {
      const listener = () => callback();
      ipcRenderer.on('dictation:cancel', listener);
      return () => ipcRenderer.removeListener('dictation:cancel', listener);
    },
    // Hand finished text to the main process (clipboard / insertion).
    deliver: (text) => ipcRenderer.invoke('dictation:deliver', text),
    // Main window: report progress for the overlay to show. null hides it.
    setStatus: (status) => ipcRenderer.send('dictation:status', status),
    // Overlay window: receive that progress, and send button presses back.
    onStatus: (callback) => {
      const listener = (_event, status) => callback(status);
      ipcRenderer.on('dictation:status', listener);
      return () => ipcRenderer.removeListener('dictation:status', listener);
    },
    overlayAction: (action) => ipcRenderer.send('dictation:overlay-action', action),
  },
  auth: {
    // Main process sends voxwell://auth/callback links (from account emails and Google) here,
    // including one the app was started with.
    onCallback: (callback) => {
      const listener = (_event, url) => callback(url);
      ipcRenderer.on('auth:callback', listener);
      ipcRenderer.send('auth:ready');
      return () => ipcRenderer.removeListener('auth:callback', listener);
    },
    // Google sign-in runs in the system browser: Google blocks it inside embedded app windows.
    openExternal: (url) => ipcRenderer.invoke('auth:open', url),
  },
});
