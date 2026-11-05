const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('voxwellSetup', {
  onProgress: (callback) => ipcRenderer.on('setup:progress', (_event, line) => callback(line)),
  onFailed: (callback) => ipcRenderer.on('setup:failed', (_event, reason) => callback(reason)),
  retry: () => ipcRenderer.send('setup:retry'),
  quit: () => ipcRenderer.send('setup:quit'),
});
