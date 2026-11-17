/** What to tell someone whose browser has no microphone access: an old browser, or a page that isn't https. */
export const NO_MICROPHONE = "This browser can't use a microphone here. Try Chrome, Edge or Safari on a secure (https) page.";

/**
 * Level (RMS, full scale 1.0) at or below which a reading counts as silence. 0.0003 is about -70 dBFS,
 * ten steps of a 16-bit sample. A muted or dead microphone delivers exact zeros (or one step of
 * dither); even a quiet room with noise suppression sits well above this, so it is never flagged.
 */
export const SILENCE_RMS = 0.0003;
export const SILENCE_AFTER_MS = 1800; // silence this long at the start (or after sound) triggers the warning
export const SILENCE_POLL_MS = 50; // one level reading; an analyser window of 2048 samples covers about this much

/** Silent when the last SILENCE_AFTER_MS of readings were all at or below SILENCE_RMS. */
export function isSilent(levels: readonly number[]): boolean {
  const needed = SILENCE_AFTER_MS / SILENCE_POLL_MS;
  return levels.length >= needed && levels.slice(-needed).every((rms) => rms <= SILENCE_RMS);
}

/**
 * Mic check: watches a microphone stream and calls `onChange(true)` once it has been silent for a moment and
 * `onChange(false)` as soon as sound arrives. Returns a function that stops watching and closes the
 * audio context; call it when recording ends.
 */
export function startMicCheck(stream: MediaStream, onChange: (silent: boolean) => void): () => void {
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 2048;
  context.createMediaStreamSource(stream).connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const levels: number[] = [];
  let silent = false;
  const timer = window.setInterval(() => {
    // A context started without a user gesture stays suspended and reads zeros; that is not a muted mic.
    if (context.state !== 'running') {
      void context.resume().catch(() => {});
      return;
    }
    analyser.getFloatTimeDomainData(samples);
    levels.push(Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length));
    if (levels.length > SILENCE_AFTER_MS / SILENCE_POLL_MS) levels.shift();
    const now = isSilent(levels);
    if (now !== silent) {
      silent = now;
      onChange(now);
    }
  }, SILENCE_POLL_MS);
  return () => {
    window.clearInterval(timer);
    void context.close().catch(() => {});
  };
}

/** What to tell someone whose microphone records nothing at all. */
export const SILENT_MICROPHONE = "Your microphone isn't picking up any sound. Check that it isn't muted, or pick another one on the Dictation page.";
