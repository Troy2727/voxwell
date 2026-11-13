import type { Page, WebSocketRoute } from '@playwright/test';
import { BACKEND, expect, openFeature, test } from './fixtures';
import { installMockBackend } from './mock-backend';

// Flow replies: a live reply arrives sentence by sentence. The bubble grows with each sentence, the
// sentences play back to back without overlapping, and the microphone stays silenced until the
// whole reply has played. Mock backend only: the test scripts the server's messages.
test.skip(({ mode }) => mode !== 'mock', 'scripts the live session');

const AGENT = { id: 'ag-1', name: 'Alpha', system_prompt: '', voice: '', language: 'en', tools: [], follow_languages: [], mood_match: false };

/** A short WAV tone, base64. */
function tone(seconds: number): string {
  const rate = 24000;
  const samples = Math.round(rate * seconds);
  const buf = Buffer.alloc(44 + samples * 2);
  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + samples * 2, 4);
  buf.write('WAVEfmt ', 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++) buf.writeInt16LE(Math.round(8000 * Math.sin((2 * Math.PI * 440 * i) / rate)), 44 + i * 2);
  return buf.toString('base64');
}

/** Runs in the page: a microphone that always grants, and a record of every sentence scheduled to play. */
function probe() {
  const w = window as unknown as { __starts: { at: number; duration: number }[]; __stops: number; __mic: (level: number) => void };
  w.__starts = [];
  w.__stops = 0;
  navigator.mediaDevices.getUserMedia = async () => {
    const ctx = new AudioContext();
    const out = ctx.createMediaStreamDestination();
    // A steady tone, so silenced frames can be told from heard ones. Quiet (like room noise, under the
    // cut-in level) until __mic() turns it up to stand for the user talking over the agent.
    const voice = ctx.createOscillator();
    const gain = ctx.createGain();
    gain.gain.value = 0.02;
    voice.connect(gain).connect(out);
    voice.start();
    w.__mic = (level: number) => gain.gain.setValueAtTime(level, ctx.currentTime);
    return out.stream;
  };
  // Every sentence scheduled to play: when on the audio clock, and how long.
  const NativeAudioContext = window.AudioContext;
  window.AudioContext = class extends NativeAudioContext {
    createBufferSource() {
      const node = super.createBufferSource();
      const start = node.start.bind(node);
      node.start = (when?: number) => {
        w.__starts.push({ at: when ?? 0, duration: node.buffer?.duration ?? 0 });
        start(when);
      };
      const stop = node.stop.bind(node);
      node.stop = (when?: number) => {
        w.__stops++;
        stop(when);
      };
      return node;
    }
  };
}

/** The agents page with a live conversation open on a scripted server; `say` sends a message for turn 0. */
async function openLive(page: Page) {
  await installMockBackend(page);
  await page.addInitScript(probe);
  await page.route(`${BACKEND}/api/agents/agents`, (route) =>
    route.request().method() === 'GET' ? route.fulfill({ json: [AGENT] }) : route.fallback(),
  );
  let server: WebSocketRoute | null = null;
  const frames: { silent: boolean; at: number }[] = [];
  const events: ({ kind: 'frame'; silent: boolean } | { kind: 'control'; message: Record<string, unknown> })[] = [];
  let config: Record<string, unknown> = {};
  await page.routeWebSocket(/\/api\/agents\/agents\/ag-1\/live$/, (ws) => {
    server = ws;
    ws.onMessage((data) => {
      if (typeof data === 'string') {
        const m = JSON.parse(data);
        events.push({ kind: 'control', message: m });
        if (m.type === 'end') ws.send(JSON.stringify({ type: 'done' }));
        if (m.type === 'start') {
          config = m.config;
          ws.send(JSON.stringify({ type: 'ready' }));
        }
        return;
      }
      const samples = new Int16Array(new Uint8Array(data as Buffer).buffer);
      frames.push({ silent: samples.every((v) => v === 0), at: Date.now() });
      events.push({ kind: 'frame', silent: samples.every((v) => v === 0) });
    });
  });
  const say = (m: object) => server!.send(JSON.stringify({ index: 0, ...m }));

  await page.goto('/');
  await openFeature(page, 'Voice agents');
  const main = page.getByRole('main');
  await main.getByRole('button', { name: 'Live conversation' }).click();
  await expect.poll(() => server !== null && Object.keys(config).length > 0).toBe(true);
  return { main, say, frames, config, events };
}

test('a live reply streams sentence by sentence and plays back to back', async ({ page }) => {
  const { main, say, frames, config } = await openLive(page);
  expect(config.stream_reply).toBe(true);

  say({ type: 'turn_end' });
  await expect(main.getByText('Thinking…')).toBeVisible();
  say({ type: 'reply_start', transcript: 'tell me something', tool_calls: [] });
  say({ type: 'reply_text', seq: 0, text: 'The first sentence is here.' });
  await expect(main.getByText('The first sentence is here.', { exact: true })).toBeVisible();
  say({ type: 'reply_audio', seq: 0, audio: tone(0.4), duration_ms: 400 });
  await expect(main.getByText('Speaking…')).toBeVisible();

  // The next sentence is still being written: the microphone must stay silenced through the gap.
  await page.waitForTimeout(700);
  const gapStart = Date.now() - 250;
  await expect(main.getByText('Speaking…')).toBeVisible();
  say({ type: 'reply_text', seq: 1, text: 'And a second one.' });
  say({ type: 'reply_audio', seq: 1, audio: null, error: 'Could not speak this sentence.' });
  say({ type: 'reply_text', seq: 2, text: 'A third to finish.' });
  say({ type: 'reply_audio', seq: 2, audio: tone(0.3), duration_ms: 300 });
  await expect(main.getByText('The first sentence is here. And a second one. A third to finish.', { exact: true })).toBeVisible();
  const inGap = frames.filter((f) => f.at >= gapStart && f.at <= gapStart + 200);
  expect(inGap.length).toBeGreaterThan(0);
  expect(inGap.every((f) => f.silent)).toBe(true);

  say({ type: 'turn', transcript: 'tell me something', reply: 'The first sentence is here. And a second one. A third to finish.', tool_calls: [], streamed: true, parts: 3, language: 'en', timing: {} });
  await expect(main.getByText('Listening…')).toBeVisible({ timeout: 3000 });
  const finishedAt = Date.now();
  await expect.poll(() => frames.some((f) => f.at > finishedAt && !f.silent), { timeout: 3000 }).toBe(true);

  const starts = await page.evaluate(() => (window as unknown as { __starts: { at: number; duration: number }[] }).__starts);
  expect(starts).toHaveLength(2); // the sentence with no audio did not block the third
  expect(starts[1].at).toBeGreaterThanOrEqual(starts[0].at + starts[0].duration);
  await expect(main.getByText('tell me something', { exact: true })).toBeVisible();
});

test('the microphone stays silenced while the last sentence is still decoding', async ({ page }) => {
  const { main, say, frames } = await openLive(page);
  say({ type: 'turn_end' });
  say({ type: 'reply_start', transcript: 'hi', tool_calls: [] });
  say({ type: 'reply_text', seq: 0, text: 'A short first sentence.' });
  say({ type: 'reply_audio', seq: 0, audio: tone(0.2), duration_ms: 200 });
  await expect(main.getByText('Speaking…')).toBeVisible();
  await page.waitForTimeout(600); // the first sentence has ended; the next is still being written
  // The last sentence and the end of the turn arrive back to back.
  say({ type: 'reply_text', seq: 1, text: 'And the last one.' });
  say({ type: 'reply_audio', seq: 1, audio: tone(0.6), duration_ms: 600 });
  say({ type: 'turn', transcript: 'hi', reply: 'A short first sentence. And the last one.', tool_calls: [], streamed: true, parts: 2, language: 'en', timing: {} });
  const sent = Date.now();
  await expect(main.getByText('Speaking…')).toBeVisible();
  await page.waitForTimeout(400); // well inside the last sentence
  const during = frames.filter((f) => f.at > sent + 100 && f.at < sent + 400);
  expect(during.length).toBeGreaterThan(0);
  expect(during.every((f) => f.silent)).toBe(true);
  await expect(main.getByText('Listening…')).toBeVisible({ timeout: 3000 });
});


test('speaking over the agent cuts it off and keeps only what was heard', async ({ page }) => {
  const { main, say, events } = await openLive(page);
  say({ type: 'turn_end' });
  say({ type: 'reply_start', transcript: 'tell me a long story', tool_calls: [] });
  say({ type: 'reply_text', seq: 0, text: 'Once upon a time there was a lighthouse.' });
  say({ type: 'reply_audio', seq: 0, audio: tone(3), duration_ms: 3000 });
  await expect(main.getByText('Speaking…')).toBeVisible();
  await page.waitForTimeout(500); // past the moment after playback starts, when echo is ignored

  const before = events.length;
  await page.evaluate(() => (window as unknown as { __mic: (level: number) => void }).__mic(0.5));
  await expect.poll(() => events.some((e) => e.kind === 'control' && e.message.type === 'cut'), { timeout: 2000 }).toBe(true);
  await expect(main.getByText('Listening…')).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __stops: number }).__stops)).toBeGreaterThan(0);

  const i = events.findIndex((e) => e.kind === 'control' && e.message.type === 'cut');
  const cut = (events[i] as { message: Record<string, unknown> }).message;
  expect(cut).toMatchObject({ type: 'cut', index: 0, heard_seq: 0 });
  expect(Number(cut.heard_ms)).toBeGreaterThan(300);
  // While the agent spoke only silence went out; right after the cut, the audio from just before it.
  expect(events.slice(before, i).filter((e) => e.kind === 'frame').every((e) => e.kind === 'frame' && e.silent)).toBe(true);
  await expect.poll(() => events.slice(i + 1).some((e) => e.kind === 'frame')).toBe(true);
  const next = events.slice(i + 1).find((e) => e.kind === 'frame');
  expect(next && next.kind === 'frame' && next.silent).toBe(false);

  // Anything the server still sends for the cut turn is ignored.
  const starts = await page.evaluate(() => (window as unknown as { __starts: unknown[] }).__starts.length);
  say({ type: 'reply_text', seq: 1, text: 'This sentence was never heard.' });
  say({ type: 'reply_audio', seq: 1, audio: tone(0.5), duration_ms: 500 });
  say({ type: 'turn', transcript: 'tell me a long story', reply: 'Once upon a time there was a lighthouse. This sentence was never heard.', tool_calls: [], streamed: true, parts: 2, language: 'en', timing: {} });
  say({ type: 'cut_ack', reply: 'Once upon a time there was a lighthouse.' });
  await expect(main.getByText('Interrupted')).toBeVisible();
  await expect(main.getByText('Once upon a time there was a lighthouse.', { exact: true })).toBeVisible();
  await expect(main.getByText(/never heard/)).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __starts: unknown[] }).__starts.length)).toBe(starts);
});

test('the agent own voice at room level does not cut it off', async ({ page }) => {
  const { main, say, events } = await openLive(page);
  say({ type: 'turn_end' });
  say({ type: 'reply_start', transcript: 'hi', tool_calls: [] });
  say({ type: 'reply_text', seq: 0, text: 'A reply that plays out to the very end.' });
  say({ type: 'reply_audio', seq: 0, audio: tone(1), duration_ms: 1000 });
  say({ type: 'turn', transcript: 'hi', reply: 'A reply that plays out to the very end.', tool_calls: [], streamed: true, parts: 1, language: 'en', timing: {} });
  await expect(main.getByText('Speaking…')).toBeVisible();
  await expect(main.getByText('Listening…')).toBeVisible({ timeout: 4000 });
  expect(events.some((e) => e.kind === 'control' && e.message.type === 'cut')).toBe(false);
  await expect(main.getByText('Interrupted')).toHaveCount(0);
});


test('with interrupting turned off, talking over the agent does not cut it off', async ({ page }) => {
  const { main, say, events } = await openLive(page);
  await main.getByRole('checkbox', { name: 'Talk over the agent to interrupt it' }).click();
  say({ type: 'turn_end' });
  say({ type: 'reply_start', transcript: 'hi', tool_calls: [] });
  say({ type: 'reply_text', seq: 0, text: 'A reply that plays out to the very end.' });
  say({ type: 'reply_audio', seq: 0, audio: tone(1.5), duration_ms: 1500 });
  await expect(main.getByText('Speaking…')).toBeVisible();
  await page.waitForTimeout(500);
  await page.evaluate(() => (window as unknown as { __mic: (level: number) => void }).__mic(0.5));
  await page.waitForTimeout(600);
  expect(events.some((e) => e.kind === 'control' && e.message.type === 'cut')).toBe(false);
  await expect(main.getByText('Speaking…')).toBeVisible();
  await page.reload(); // the choice is remembered
  await openFeature(page, 'Voice agents');
  await expect(page.getByRole('main').getByRole('checkbox', { name: 'Talk over the agent to interrupt it' })).not.toBeChecked();
});

test('a new live session never rewrites an earlier session reply', async ({ page }) => {
  const { main, say } = await openLive(page);
  say({ type: 'turn_end' });
  say({ type: 'reply_start', transcript: 'first question', tool_calls: [] });
  say({ type: 'reply_text', seq: 0, text: 'The first answer stays as it is.' });
  say({ type: 'reply_audio', seq: 0, audio: null });
  say({ type: 'turn', transcript: 'first question', reply: 'The first answer stays as it is.', tool_calls: [], streamed: true, parts: 1, language: 'en', timing: {} });
  await expect(main.getByText('The first answer stays as it is.', { exact: true })).toBeVisible();
  await main.getByRole('button', { name: 'End conversation' }).click();
  await main.getByRole('button', { name: 'Live conversation' }).click();
  await expect(main.getByText('Listening…')).toBeVisible();
  say({ type: 'turn_end' }); // turn numbers start at 0 again in the new session
  say({ type: 'reply_start', transcript: 'second question', tool_calls: [] });
  say({ type: 'reply_text', seq: 0, text: 'A second answer.' });
  say({ type: 'reply_audio', seq: 0, audio: null });
  say({ type: 'turn', transcript: 'second question', reply: 'A second answer.', tool_calls: [], streamed: true, parts: 1, language: 'en', timing: {} });
  await expect(main.getByText('A second answer.', { exact: true })).toBeVisible();
  await expect(main.getByText('The first answer stays as it is.', { exact: true })).toBeVisible();
});
