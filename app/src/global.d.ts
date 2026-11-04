/** What the dictation overlay shows; null hides it. */
type DictationStatus =
  | { phase: 'recording'; startedAt: number; deviceId?: string }
  | { phase: 'transcribing' }
  | { phase: 'done'; text: string }
  | { phase: 'error'; message: string }
  | null;

type DictationOverlayAction = 'ready' | 'stop' | 'cancel' | 'dismiss';

interface VoxwellBridge {
  backendUrl: string;
  dictation: {
    onToggle(callback: () => void): () => void;
    onCancel(callback: () => void): () => void;
    deliver(text: string): Promise<void>;
    setStatus(status: DictationStatus): void;
    onStatus(callback: (status: DictationStatus) => void): () => void;
    overlayAction(action: DictationOverlayAction): void;
  };
  auth: {
    onCallback(callback: (url: string) => void): () => void;
    openExternal(url: string): Promise<void>;
  };
}

interface Window {
  // Undefined when the UI runs in a plain browser (vite dev without Electron).
  voxwell?: VoxwellBridge;
}
