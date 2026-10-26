interface VoxwellBridge {
  backendUrl: string;
  dictation: {
    onToggle(callback: () => void): () => void;
    deliver(text: string): Promise<void>;
  };
}

interface Window {
  // Undefined when the UI runs in a plain browser (vite dev without Electron).
  voxwell?: VoxwellBridge;
}
