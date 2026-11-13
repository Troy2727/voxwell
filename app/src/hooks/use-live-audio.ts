import { useCallback, useEffect, useRef, useState } from 'react';
import { wsUrl } from '@/api';
import { NO_MICROPHONE } from '@/lib/microphone';

/** A message from a live session; the protocol is described in backend/voxwell/live_audio.py. */
export interface LiveMessage {
  type: 'ready' | 'speaking' | 'turn_end' | 'turn' | 'warning' | 'error' | 'done' | 'reply_start' | 'reply_text' | 'reply_audio' | 'cut_ack';
  index?: number | null;
  message?: string;
  [field: string]: unknown;
}

export type LiveStatus = 'idle' | 'connecting' | 'listening' | 'finishing';

const RATE = 16000; // what the server expects: 16 kHz mono PCM16
const SEND_SAMPLES = 1600; // 100 ms per message
const LEVEL_WINDOW_MS = 20; // the microphone level is reported per window this long
// Microphone audio kept while paused and sent first on resume(true): enough for speech that began just as
// a sentence started playing (the cut-in grace, then its minimum run, plus slack).
const PRE_ROLL_SAMPLES = (RATE * 600) / 1000;

// Runs on the audio thread and hands the page blocks of microphone samples.
const TAP = `class VoxwellTap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i];
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
    }
    return true;
  }
}
registerProcessor('voxwell-tap', VoxwellTap);`;

/** Converts blocks at the microphone's rate to 16 kHz PCM16 by averaging (a simple low-pass). */
function downsampler(inputRate: number) {
  const ratio = inputRate / RATE;
  let pending = new Float32Array(0);
  return (block: Float32Array): Int16Array => {
    const input = new Float32Array(pending.length + block.length);
    input.set(pending);
    input.set(block, pending.length);
    const n = Math.floor(input.length / ratio);
    const out = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const a = Math.floor(i * ratio);
      const b = Math.max(a + 1, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = a; j < b; j++) sum += input[j];
      const v = Math.max(-1, Math.min(1, sum / (b - a)));
      out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    pending = input.slice(Math.floor(n * ratio));
    return out;
  };
}

function micError(e: unknown): string {
  if (!navigator.mediaDevices) return NO_MICROPHONE;
  const name = e instanceof DOMException ? e.name : '';
  if (name === 'NotAllowedError') return 'Microphone access was denied. Allow it in your system or browser settings and try again.';
  if (name === 'NotFoundError') return 'No microphone found.';
  return `Could not open the microphone: ${e instanceof Error ? e.message : String(e)}`;
}

interface Session {
  ws: WebSocket;
  stream: MediaStream;
  ctx: AudioContext;
  flush: () => void;
  feed: (pcm: Int16Array) => void;
  ending: boolean;
}

/**
 * Streams the microphone to a live endpoint (e.g. '/api/dictation/live') and passes every
 * server message to `onMessage`. `start(config)` opens a session; `stop()` lets the server
 * finish the last turn (status 'finishing' until it says 'done'); `cancel()` drops it now.
 * While `pause(true)`, silence is sent instead of the microphone, e.g. during playback; the last
 * moment of real microphone audio is kept, and `resume(true)` sends it first so no words are lost.
 * `watchLevel(fn)` reports the microphone level (RMS per short window), paused or not, and
 * `send(message)` sends a JSON control message to the server.
 */
export function useLiveAudio(path: string, onMessage: (message: LiveMessage) => void) {
  const [status, setStatus] = useState<LiveStatus>('idle');
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState('');
  const session = useRef<Session | null>(null);
  const handler = useRef(onMessage);
  handler.current = onMessage;
  const paused = useRef(false);
  const preRoll = useRef<Int16Array[]>([]);
  const level = useRef<((rms: number, now: number, ms: number) => void) | null>(null);
  // A start() still waiting for the microphone or the audio worklet. stop(), cancel() and unmounting
  // clear it, so that start gives up instead of opening a session nobody is left to close.
  const starting = useRef<object | null>(null);

  const abandonStart = useCallback(() => {
    if (!starting.current) return;
    starting.current = null;
    setStatus('idle');
  }, []);

  const stopAudio = (s: Session) => {
    s.stream.getTracks().forEach((t) => t.stop());
    if (s.ctx.state !== 'closed') void s.ctx.close();
  };

  const close = useCallback((s: Session) => {
    stopAudio(s);
    s.ws.onclose = null;
    if (s.ws.readyState === WebSocket.CONNECTING || s.ws.readyState === WebSocket.OPEN) s.ws.close();
    if (session.current === s) {
      session.current = null;
      setStatus('idle');
      setSpeaking(false);
    }
  }, []);

  const start = useCallback(
    async (config: Record<string, unknown>, deviceId?: string) => {
      if (session.current || starting.current) return;
      const attempt = {};
      starting.current = attempt;
      const abandoned = () => starting.current !== attempt;
      setError('');
      setStatus('connecting');
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { ...(deviceId ? { deviceId: { exact: deviceId } } : {}), channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (e) {
        if (abandoned()) return;
        starting.current = null;
        setError(micError(e));
        setStatus('idle');
        return;
      }
      if (abandoned()) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      const ctx = new AudioContext();
      let tap: AudioWorkletNode;
      try {
        const url = URL.createObjectURL(new Blob([TAP], { type: 'text/javascript' }));
        await ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        tap = new AudioWorkletNode(ctx, 'voxwell-tap');
      } catch (e) {
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close();
        if (abandoned()) return;
        starting.current = null;
        setError(`Live audio is not available here: ${e instanceof Error ? e.message : String(e)}`);
        setStatus('idle');
        return;
      }
      if (abandoned()) {
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close();
        return;
      }
      starting.current = null;
      ctx.createMediaStreamSource(stream).connect(tap);
      tap.connect(ctx.destination); // keeps the tap running; it outputs silence

      const ws = new WebSocket(wsUrl(path));
      ws.binaryType = 'arraybuffer';
      const toPcm = downsampler(ctx.sampleRate);
      let chunk = new Int16Array(SEND_SAMPLES);
      let filled = 0;
      const s: Session = {
        ws,
        stream,
        ctx,
        ending: false,
        flush: () => {
          if (filled && ws.readyState === WebSocket.OPEN) ws.send(chunk.slice(0, filled).buffer);
          filled = 0;
        },
        feed: (pcm: Int16Array) => {
          for (let i = 0; i < pcm.length; i++) {
            chunk[filled++] = pcm[i];
            if (filled === SEND_SAMPLES) {
              ws.send(chunk.buffer);
              chunk = new Int16Array(SEND_SAMPLES);
              filled = 0;
            }
          }
        },
      };
      const windowSamples = Math.max(1, Math.round((ctx.sampleRate * LEVEL_WINDOW_MS) / 1000));
      const windowMs = (windowSamples / ctx.sampleRate) * 1000;
      session.current = s;
      let opened = false;
      let failed = false;

      tap.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        if (ws.readyState !== WebSocket.OPEN || s.ending) return;
        const watch = level.current;
        if (watch) {
          const now = performance.now();
          for (let start = 0; start + windowSamples <= ev.data.length; start += windowSamples) {
            let sum = 0;
            for (let i = start; i < start + windowSamples; i++) sum += ev.data[i] * ev.data[i];
            watch(Math.sqrt(sum / windowSamples), now - ((ev.data.length - start) / ctx.sampleRate) * 1000, windowMs);
          }
        }
        const pcm = toPcm(ev.data);
        if (paused.current) {
          preRoll.current.push(pcm.slice());
          let kept = preRoll.current.reduce((n, b) => n + b.length, 0);
          while (kept - preRoll.current[0].length >= PRE_ROLL_SAMPLES) kept -= preRoll.current.shift()!.length;
          pcm.fill(0);
        }
        s.feed(pcm);
      };
      ws.onopen = () => {
        opened = true;
        ws.send(JSON.stringify({ type: 'start', config }));
      };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== 'string') return;
        let m: LiveMessage;
        try {
          m = JSON.parse(ev.data) as LiveMessage;
        } catch {
          return;
        }
        if (m.type === 'ready') setStatus('listening');
        else if (m.type === 'speaking') setSpeaking(true);
        else if (m.type === 'turn_end') setSpeaking(false);
        else if (m.type === 'error' && m.index == null) {
          failed = true;
          setError(m.message || 'The live session stopped.');
        }
        handler.current(m);
        if (m.type === 'done') close(s);
      };
      ws.onclose = () => {
        if (!s.ending && !failed) {
          setError(opened ? 'The live connection closed unexpectedly.' : 'Could not connect to Voxwell. Is it still running?');
        }
        close(s);
      };
    },
    [path, close],
  );

  const stop = useCallback(() => {
    const s = session.current;
    if (!s) {
      abandonStart();
      return;
    }
    if (s.ws.readyState !== WebSocket.OPEN || s.ending) {
      close(s);
      return;
    }
    s.flush();
    s.ending = true;
    stopAudio(s);
    s.ws.send(JSON.stringify({ type: 'end' }));
    setStatus('finishing');
    setSpeaking(false);
  }, [close, abandonStart]);

  const cancel = useCallback(() => {
    if (session.current) close(session.current);
    else abandonStart();
  }, [close, abandonStart]);

  const pause = useCallback((on: boolean) => {
    if (on && !paused.current) preRoll.current = []; // a new pause; staying paused keeps what was kept
    paused.current = on;
  }, []);
  /** Stop sending silence; with `withPreRoll`, first send the microphone audio kept while paused. */
  const resume = useCallback((withPreRoll: boolean) => {
    const s = session.current;
    paused.current = false;
    if (withPreRoll && s && s.ws.readyState === WebSocket.OPEN && !s.ending) for (const block of preRoll.current) s.feed(block);
    preRoll.current = [];
  }, []);
  const watchLevel = useCallback((fn: ((rms: number, now: number, ms: number) => void) | null) => {
    level.current = fn;
  }, []);
  const send = useCallback((message: Record<string, unknown>) => {
    const s = session.current;
    if (s && s.ws.readyState === WebSocket.OPEN && !s.ending) s.ws.send(JSON.stringify(message));
  }, []);

  useEffect(() => () => {
    abandonStart();
    if (session.current) close(session.current);
  }, [close, abandonStart]);

  return { status, speaking, error, start, stop, cancel, pause, resume, watchLevel, send };
}
