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
  ];
}

export async function installMockBackend(page: Page) {
  const table = routes();
  await page.route(`${BACKEND}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (method === 'GET' && (url.pathname === TONE_URL || url.pathname.endsWith('.wav') || url.pathname.endsWith('/audio'))) {
      return route.fulfill({ status: 200, contentType: 'audio/wav', body: TONE });
    }
    const key = `${method} ${url.pathname}`;
    const reply = table.find(([match]) => (typeof match === 'string' ? match === key : match.test(key)))?.[1];
    if (reply === undefined) {
      return route.fulfill({ status: 501, contentType: 'application/json', body: JSON.stringify({ detail: `No mock for ${key}` }) });
    }
    const body = typeof reply === 'function' ? reply(url, request) : reply;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}
