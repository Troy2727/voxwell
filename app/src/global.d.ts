/** What the dictation overlay shows; null hides it. */
type DictationStatus =
  | { phase: 'recording'; startedAt: number; deviceId?: string; silent?: boolean }
  | { phase: 'transcribing' }
  | { phase: 'done'; text: string; pasted?: boolean; reason?: string }
  | { phase: 'error'; message: string }
  | null;

type DictationOverlayAction = 'ready' | 'stop' | 'cancel' | 'dismiss';

interface VoxwellBridge {
  backendUrl: string;
  dictation: {
    onToggle(callback: () => void): () => void;
    onCancel(callback: () => void): () => void;
    /** Copies the text and, with pasteInPlace, pastes it into the focused app. reason says why not. */
    deliver(text: string, pasteInPlace: boolean): Promise<{ pasted: boolean; reason?: string }>;
    setStatus(status: DictationStatus): void;
    onStatus(callback: (status: DictationStatus) => void): () => void;
    overlayAction(action: DictationOverlayAction): void;
  };
  /** Run in background. Both resolve to the saved value; set rejects when it could not be saved. */
  background: {
    get(): Promise<boolean>;
    set(enabled: boolean): Promise<boolean>;
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
