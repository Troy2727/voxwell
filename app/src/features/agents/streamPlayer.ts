/**
 * Flow replies: plays a reply's sentences back to back on one audio clock, in `seq` order.
 *
 * Each sentence arrives as its own WAV. A sentence starts at the end of the one before plus a short
 * gap, or at once if it arrives late; one that arrives early waits its turn, so nothing overlaps.
 * A sentence with no audio (it could not be spoken) just lets the next one through.
 */

export const SENTENCE_GAP_S = 0.25;

export class StreamPlayer {
  private ctx: AudioContext | null = null;
  private next = 0; // the seq to schedule next
  private end = 0; // when the last scheduled sentence ends, on the audio clock
  private ready = new Map<number, AudioBuffer | null>(); // decoded, waiting for an earlier seq
  private sources = new Set<AudioBufferSourceNode>();
  private decoding = 0; // sentences received but not yet decoded
  private generation = 0; // bumped by clear() and newReply(), so decodes that finish afterwards are dropped
  private timeline: { seq: number; at: number; duration: number }[] = []; // this reply's sentences

  /** `onStart(seq)` runs when a sentence starts playing; `onIdle()` when the last one scheduled ends. */
  constructor(private onStart: (seq: number) => void, private onIdle: () => void) {}

  /** A new reply: its sentences count from seq 0 again. */
  newReply() {
    this.generation++;
    this.next = 0;
    this.ready.clear();
    this.timeline = [];
  }

  /** What of this reply has been heard: the last sentence that started playing (null: none), and ms played. */
  heard(): { seq: number | null; ms: number } {
    const now = this.ctx?.currentTime ?? 0;
    const started = this.timeline.filter((s) => s.at <= now);
    const ms = started.reduce((sum, s) => sum + Math.min(s.duration, now - s.at), 0) * 1000;
    return { seq: started.length ? Math.max(...started.map((s) => s.seq)) : null, ms: Math.round(ms) };
  }

  /** True while a sentence plays, is scheduled, or is still decoding or waiting for an earlier one. */
  get playing() {
    return this.sources.size > 0 || this.decoding > 0 || this.ready.size > 0;
  }

  async enqueue(seq: number, base64: string | null) {
    const generation = this.generation;
    let buffer: AudioBuffer | null = null;
    this.decoding++;
    if (base64) {
      try {
        this.ctx ??= new AudioContext();
        const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
        buffer = await this.ctx.decodeAudioData(bytes.buffer);
      } catch {
        buffer = null; // undecodable or no Web Audio: the text still shows, the next sentence still plays
      }
    }
    this.decoding--;
    if (generation !== this.generation) return;
    this.ready.set(seq, buffer);
    while (this.ready.has(this.next)) {
      const item = this.ready.get(this.next)!;
      this.ready.delete(this.next);
      if (item && this.ctx) this.schedule(item, this.next);
      this.next++;
    }
    if (!this.playing) this.onIdle(); // e.g. the last sentence had no audio
  }

  /** Stop, and let go of the audio device (the player can't be used again). */
  close() {
    this.clear();
    void this.ctx?.close();
    this.ctx = null;
  }

  /** Stop at once and forget everything queued. */
  clear() {
    this.generation++;
    this.ready.clear();
    for (const source of this.sources) {
      source.onended = null;
      source.stop();
    }
    this.sources.clear();
    this.end = 0;
  }

  private schedule(buffer: AudioBuffer, seq: number) {
    const ctx = this.ctx!;
    if (ctx.state === 'suspended') void ctx.resume();
    const startAt = Math.max(ctx.currentTime, this.end > 0 ? this.end + SENTENCE_GAP_S : 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => {
      this.sources.delete(source);
      if (!this.playing) this.onIdle(); // not while a later sentence is still decoding or waiting
    };
    this.sources.add(source);
    source.start(startAt);
    this.end = startAt + buffer.duration;
    this.timeline.push({ seq, at: startAt, duration: buffer.duration });
    const generation = this.generation;
    window.setTimeout(() => generation === this.generation && this.onStart(seq), Math.max(0, (startAt - ctx.currentTime) * 1000));
  }
}
