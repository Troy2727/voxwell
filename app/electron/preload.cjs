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
    // Hand finished text to the main process (clipboard / insertion).
    deliver: (text) => ipcRenderer.invoke('dictation:deliver', text),
  },
});
