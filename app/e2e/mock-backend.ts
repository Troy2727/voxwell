import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Page, Request } from '@playwright/test';

const BACKEND = 'http://127.0.0.1:8765';
const TONE = readFileSync(path.join(__dirname, 'fixtures', 'tone-1s.wav'));

/** Every faked audio result points here; the route below serves the 1 s tone for it. */
export const TONE_URL = '/mock/tone.wav';

type Reply = unknown | ((url: URL, request: Request) => unknown);

const VOICES = [
  { id: 'v-upload', name: 'Narrator', source: 'upload' },
  { id: 'v-design', name: 'Warm British voice with a deliberately long name for wrapping', source: 'design' },
  { id: 'v-remix', name: 'Zoë (remix)', source: 'remix' },
];

/** A background job seen through polling: each look moves it one step, then it stays on the last. */
function job<T>(steps: T[]) {
  let seen = 0;
  return () => steps[Math.min(seen++, steps.length - 1)];
}

const NOW = 1_790_000_000;

const MUSIC_STATUS = {
  installed: true,
  install: { state: 'idle', step: '', percent: 0, detail: '', error: '' },
  engine: 'ready',
  device: 'cpu',
  languages: { en: 'English', es: 'Spanish' },
  keys: ['C major', 'A minor'],
  limits: { min_seconds: 10, max_seconds: 240, max_prompt: 500, max_lyrics: 4000 },
};

function track(status: string, progress: number) {
  return {
    id: 't-1', title: 'Neon nights', prompt: 'Dreamy synth-pop', lyrics: '[Verse]\nCity lights', instrumental: false, language: 'en',
    duration: 30, bpm: 110, key: 'A minor', seed: 7, steps: 8, created: NOW, status, progress, stage: 'Composing', error: '',
    parent_id: null, edit_start: null, edit_end: null, has_reference: false, stems: false, url: status === 'done' ? TONE_URL : undefined,
  };
}

function book(state: string, done: boolean, include = [true, true]) {
  return {
    id: 'b-1', title: 'The Lighthouse', created: NOW, language: 'en', voice: 'default', state, step: 'Chapter 1 of 1', percent: done ? 100 : 40, error: null,
    chapters: [
      { title: 'The Storm', chars: 300, include: include[0], status: done && include[0] ? 'done' : 'pending', audio_url: done && include[0] ? TONE_URL : null },
      { title: 'Morning', chars: 250, include: include[1], status: done && include[1] ? 'done' : 'pending', audio_url: done && include[1] ? TONE_URL : null },
    ],
    download_url: '/mock/book.zip',
  };
}

/**
 * Fake replies, by "METHOD /path" (exact) or a RegExp tested against "METHOD /path". Built per test,
 * so jobs start fresh. Anything not listed answers 501 naming the request, so a missing mock fails loudly.
 */
function routes(): [string | RegExp, Reply][] {
  let tracks: object[] = [];
  let trackJob = job([track('generating', 0.5), track('done', 1)]);
  let books: object[] = [];
  let include = [true, true];
  let rendering: (() => object) | null = null;
  let transcribed: (() => object) | null = null;
  let entries: object[] = [];
  let phone = {
    enabled: false, public_url: '', auth_token_set: false, greeting_text: '', voice_id: '', language: 'en', greeting_ready: false,
    gateway: 'stopped', gateway_running: false, webhook_url: '', calls: [],
  };
  let agents: object[] = [];
  let watch = { enabled: false, folder: '', target_language: 'es', voice: 'original', problem: null, output_folder: 'dubbed', skipped: 0, files: [] };
  const story = job([
    { id: 'st-1', title: 'The knock', state: 'queued', step: 'Waiting', percent: 0, error: null, audio_url: '' },
    { id: 'st-1', title: 'The knock', state: 'running', step: 'Line 2 of 4', percent: 50, error: null, audio_url: '' },
    { id: 'st-1', title: 'The knock', state: 'done', step: '', percent: 100, error: null, audio_url: TONE_URL },
  ]);

  return [
    ['GET /api/health', { status: 'ok' }],
    ['GET /api/voices', VOICES],
    ['GET /api/voice_collections', [{ id: 'c-1', name: 'Narrators', voice_ids: ['v-upload', 'v-design'] }]],
    ['POST /api/voice_collections', { id: 'c-new', name: 'E2E collection', voice_ids: [] }],
    [/^(PATCH|DELETE) \/api\/voice_collections\/[^/]+$/, {}],
    [/^(PUT|DELETE) \/api\/voice_collections\/[^/]+\/voices\/[^/]+$/, {}],
    [/^(PATCH|DELETE) \/api\/voices\/[^/]+$/, {}],

    ['POST /api/voice_cloning/voices', { id: 'v-new', name: 'E2E voice', source: 'upload' }],
    ['POST /api/voice_cloning/synthesize', { id: 'a-1', url: TONE_URL }],

    ['POST /api/voice_design/preview', { preview_id: 'p-1', url: TONE_URL }],
    ['POST /api/voice_design/save', { id: 'v-new', name: 'Designed', source: 'design' }],

    ['GET /api/voice_remix/status', { ready: true, default_script: 'This is how the new voice sounds.' }],
    ['POST /api/voice_remix/preview', { preview_id: 'p-2', url: TONE_URL }],
    ['POST /api/voice_remix/save', { id: 'v-new2', name: 'Narrator (remix)', source: 'remix' }],

    ['GET /api/gallery/presets', [
      { id: 'calm', name: 'Calm Narrator', category: 'Narration', description: 'A calm, warm voice.', sample: 'It was late.', ready: false, audio_url: null },
      { id: 'bright', name: 'Bright Storyteller', category: 'Narration', description: 'A bright voice.', sample: 'Once upon a time.', ready: true, audio_url: TONE_URL },
    ]],
    [/^POST \/api\/gallery\/presets\/[^/]+\/sample$/, (url: URL) => ({
      id: url.pathname.split('/')[4], name: 'Calm Narrator', category: 'Narration', description: 'A calm, warm voice.', sample: 'It was late.', ready: true, audio_url: TONE_URL,
    })],
    [/^POST \/api\/gallery\/presets\/[^/]+\/add$/, { id: 'v-gallery', name: 'Calm Narrator', source: 'design' }],

    ['POST /api/audio_effects/apply', { url: TONE_URL }],

    ['GET /api/sound/status', { ready: true, installed: true, token_set: true, model: 'stabilityai/stable-audio-open-1.0', model_url: 'https://huggingface.co/stabilityai/stable-audio-open-1.0' }],
    ['GET /api/sound/history', []],
    ['POST /api/sound/generate', { id: 's-1', prompt: 'Rain on a tin roof with distant thunder', duration: 3, seed: 42, steps: 20, created: NOW, url: TONE_URL }],

    ['GET /api/music/status', MUSIC_STATUS],
    ['POST /api/music/lyrics', { lyrics: '[Verse 1]\nCity lights are calling\n\n[Chorus]\nWe run through neon nights' }],
    ['POST /api/music/generate', () => {
      trackJob = job([track('generating', 0.5), track('done', 1)]); // the POST itself answers "queued"
      tracks = [track('queued', 0)];
      return tracks[0];
    }],
    ['GET /api/music/tracks', () => (tracks.length ? [trackJob()] : [])],

    ['POST /api/stories/parse', (_url: URL, request: Request) => {
      const lines: string[] = request.postDataJSON().script.split('\n').filter((l: string) => l.trim());
      const speakers = [...new Set(lines.map((l) => (/^(\w+):/.exec(l)?.[1] ?? 'Narrator')))];
      return { speakers, lines: lines.length };
    }],
    ['POST /api/stories/jobs', { id: 'st-1' }],
    ['GET /api/stories/jobs/st-1', story],

    ['GET /api/audiobook/books', () => (rendering ? [rendering()] : books)],
    ['POST /api/audiobook/books', () => {
      books = [book('draft', false)];
      return books[0];
    }],
    ['PATCH /api/audiobook/books/b-1', (_url: URL, request: Request) => {
      const chapters: { include: boolean }[] | undefined = request.postDataJSON().chapters;
      if (chapters) include = chapters.map((c) => c.include);
      books = [book('draft', false, include)];
      return books[0];
    }],
    ['POST /api/audiobook/books/b-1/preview', { url: TONE_URL }],
    ['POST /api/audiobook/books/b-1/render', () => {
      rendering = job([book('running', false, include), book('done', true, include)]);
      return {};
    }],

    ['POST /api/dubbing/jobs', { id: 'd-1' }],
    ['GET /api/dubbing/jobs/d-1', dub()],
    ['POST /api/batch/jobs', { jobs: [{ name: 'video.mp4', id: 'd-2' }], errors: [{ name: 'bad.exe', error: 'Not a video or audio file.' }] }],
    ['GET /api/dubbing/jobs/d-2', dub()],
    ['GET /api/transcription/jobs', () => (transcribed ? [transcribed()] : [])],
    ['POST /api/transcription/jobs', () => {
      transcribed = job([{ ...TRANSCRIPT, state: 'running', percent: 50 }, TRANSCRIPT]);
      return { id: 'tr-1' };
    }],
    ['GET /api/transcription/jobs/tr-1', { ...TRANSCRIPT, transcript: { text: SPEECH, language: 'en', segments: [{ start: 0, end: 5.9, text: SPEECH }] } }],
    ['GET /api/transcription/edit/presets', [{ id: 'tidy', label: 'Fix punctuation and capitals', instruction: 'Fix punctuation.' }]],
    ['POST /api/transcription/edit', { text: SPEECH.replace('seven o\'clock', '7:00'), chunks: 1, kept: 0 }],
    ['POST /api/transcription/align', {
      cues: [{ start: 0, end: 2.9, text: SPEECH.split('. ')[0] + '.' }, { start: 3, end: 5.9, text: SPEECH.split('. ')[1] }],
      srt: '', vtt: '', matched: 22, total: 22, fallback: false,
    }],

    ['POST /api/tools/convert', { url: TONE_URL }],
    ['POST /api/tools/isolate', { voice: { url: '/mock/voice.wav' }, background: { url: '/mock/background.wav' }, seconds: 10 }],
    ['POST /api/tools/direction/interpret', { intensity: 0.2, pace: 'slow', summary: 'quiet, sad, slow' }],
    ['POST /api/tools/direction/speak', { url: TONE_URL }],
    ['POST /api/tools/speak', { url: TONE_URL }],
    ['POST /api/tools/fit', { url: TONE_URL, original_seconds: 5.92 }],
    ['POST /api/tools/probe', {
      format: 'QuickTime / MOV', duration: 5.92, size: 67855, bit_rate: 91700,
      streams: [
        { type: 'video', codec: 'H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10', width: 640, height: 360, fps: 25.0 },
        { type: 'audio', codec: 'AAC (Advanced Audio Coding)', sample_rate: 24000, channels: 1 },
      ],
    }],

    ['GET /api/pronunciation/entries', () => entries],
    ['POST /api/pronunciation/entries', (_url: URL, request: Request) => {
      const { word, respelling, case_sensitive, whole_word } = request.postDataJSON();
      entries = [{ id: 'pr-1', word, respelling, case_sensitive, whole_word }];
      return entries[0];
    }],
    [/^DELETE \/api\/pronunciation\/entries\/[^/]+$/, () => {
      entries = [];
      return {};
    }],
    ['POST /api/pronunciation/preview', { text: 'Ask Ms. win about it.' }],

    ['GET /api/projects/items', [
      { kind: 'speech', id: 'sp-1', title: 'A project for the end to end test.', created: NOW, language: 'en', voice: 'default', text: 'A project for the end to end test.', audio_url: TONE_URL },
      { kind: 'transcript', id: 'tr-1', title: 'speech.wav', created: NOW - 60, language: 'en', voice: '', state: 'done', step: '', percent: 100, error: null, text: SPEECH,
        exports: { txt: '/mock/export/txt', srt: '/mock/export/srt', vtt: '/mock/export/vtt' } },
    ]],
    [/^(PATCH|DELETE) \/api\/projects\/items\/[^/]+\/[^/]+$/, {}],

    ['GET /api/agents/status', {
      ready: true,
      tools: [{ name: 'current_time', description: 'The current local date and time.' }, { name: 'calculator', description: 'Exact arithmetic.' }],
      languages: ['en', 'es'],
    }],
    ['GET /api/agents/agents', () => agents],
    ['POST /api/agents/agents', (_url: URL, request: Request) => {
      agents = [{ id: 'ag-1', ...request.postDataJSON() }];
      return agents[0];
    }],
    ['POST /api/agents/agents/ag-1/chat', { reply: '17 times 23 is 391.', tool_calls: [{ tool: 'calculator', arguments: { expression: '17*23' }, result: '391' }], audio: TONE_URL }],

    ['GET /api/integrations/info', {
      api_base: `${BACKEND}/v1`, cli: 'voxwell', skill: { claude: false, codex: false },
      mcp: { command: 'uv', args: ['run', '--directory', '<voxwell>/backend', 'voxwell-mcp'], env: {} },
    }],
    ['GET /api/integrations/phone', () => phone],
    ['PUT /api/integrations/phone', (_url: URL, request: Request) => {
      const { public_url, greeting_text, voice_id, language, enabled } = request.postDataJSON();
      phone = { ...phone, public_url, greeting_text, voice_id, language, enabled };
      return phone;
    }],
    ['POST /api/integrations/phone/greeting', () => {
      phone = { ...phone, greeting_ready: true };
      return phone;
    }],

    ['GET /api/translation/status', { ready: true, sources: ['en', 'es'], targets: ['en', 'es'] }],
    ['POST /api/dictation/transcribe', { text: SPEECH, language: 'en' }],

    ['GET /api/batch/watch', () => watch],
    ['PUT /api/batch/watch', (_url: URL, request: Request) => {
      const { enabled, folder, target_language, voice } = request.postDataJSON();
      watch = { ...watch, enabled, folder, target_language, voice };
      return watch;
    }],
  ];
}

function dub() {
  return job([
    { id: 'd', state: 'running', step: 'Translating', percent: 50, error: null },
    { id: 'd', state: 'done', step: '', percent: 100, error: null },
  ]);
}

const SRT = '1\n00:00:00,000 --> 00:00:02,500\nEl rápido zorro marrón salta sobre el perro perezoso.\n';
const SPEECH = readFileSync(path.join(__dirname, 'fixtures', 'speech.txt'), 'utf8').trim();
const TRANSCRIPT = { id: 'tr-1', title: 'speech.wav', created: NOW, language: '', detected: 'en', state: 'done', percent: 100, error: null };
const VIDEO = readFileSync(path.join(__dirname, 'fixtures', 'video.mp4'));

/** Files the pages load directly (players, downloads) rather than as JSON. */
function file(pathname: string): { contentType: string; body: Buffer | string } | null {
  if (pathname === TONE_URL || pathname.endsWith('.wav') || pathname.endsWith('/audio')) return { contentType: 'audio/wav', body: TONE };
  if (pathname.endsWith('/video')) return { contentType: 'video/mp4', body: VIDEO };
  if (pathname.endsWith('/subtitles') || pathname.endsWith('/export/srt')) return { contentType: 'application/x-subrip', body: SRT };
  return null;
}

/**
 * The live endpoints (dictation, translation): after the start message the server says "ready";
 * once about a second of microphone audio has arrived it reports one finished turn; "end" closes it.
 */
async function installLiveSocket(page: Page) {
  await page.routeWebSocket(/\/api\/(dictation|translation)\/live$/, (ws) => {
    const translation = ws.url().includes('translation');
    let chunks = 0;
    ws.onMessage((message) => {
      if (typeof message === 'string') {
        const m = JSON.parse(message);
        if (m.type === 'start') ws.send(JSON.stringify({ type: 'ready' }));
        if (m.type === 'end') ws.send(JSON.stringify({ type: 'done' }));
        return;
      }
      if (++chunks !== 10) return; // 100 ms per chunk
      ws.send(JSON.stringify({ type: 'speaking' }));
      ws.send(JSON.stringify({ type: 'turn_end', index: 0 }));
      ws.send(JSON.stringify(translation
        ? { type: 'turn', index: 0, transcript: SPEECH, source: 'en', translation: 'El rápido zorro marrón salta sobre el perro perezoso.', audio: TONE.toString('base64') }
        : { type: 'turn', index: 0, text: SPEECH }));
    });
  });
}

export async function installMockBackend(page: Page) {
  await installLiveSocket(page);
  const table = routes();
  await page.route(`${BACKEND}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const served = method === 'GET' ? file(url.pathname) : null;
    if (served) return route.fulfill({ status: 200, ...served });
    const key = `${method} ${url.pathname}`;
    const reply = table.find(([match]) => (typeof match === 'string' ? match === key : match.test(key)))?.[1];
    if (reply === undefined) {
      return route.fulfill({ status: 501, contentType: 'application/json', body: JSON.stringify({ detail: `No mock for ${key}` }) });
    }
    const body = typeof reply === 'function' ? reply(url, request) : reply;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}
