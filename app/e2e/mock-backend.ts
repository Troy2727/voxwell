import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Page } from '@playwright/test';

const BACKEND = 'http://127.0.0.1:8765';
const TONE = readFileSync(path.join(__dirname, 'fixtures', 'tone-1s.wav'));

/** Every faked audio result points here; the route below serves the 1 s tone for it. */
export const TONE_URL = '/mock/tone.wav';

type Reply = unknown | ((url: URL) => unknown);

const VOICES = [
  { id: 'v-upload', name: 'Narrator', source: 'upload' },
  { id: 'v-design', name: 'Warm British voice with a deliberately long name for wrapping', source: 'design' },
  { id: 'v-remix', name: 'Zoë (remix)', source: 'remix' },
];

/**
 * Fake replies, by "METHOD /path" (exact) or a RegExp tested against "METHOD /path".
 * Anything not listed answers 501 with a message naming the request, so a missing mock fails loudly.
 */
const ROUTES: [string | RegExp, Reply][] = [
  ['GET /api/health', { status: 'ok' }],
  ['GET /api/voices', VOICES],
  ['GET /api/voice_collections', [{ id: 'c-1', name: 'Narrators', voice_ids: ['v-upload', 'v-design'] }]],

  ['POST /api/voice_collections', { id: 'c-new', name: 'E2E collection', voice_ids: [] }],
  [/^(PATCH|DELETE) \/api\/voice_collections\/[^/]+$/, {}],
  [/^(PUT|DELETE) \/api\/voice_collections\/[^/]+\/voices\/[^/]+$/, {}],
  [/^(PATCH|DELETE) \/api\/voices\/[^/]+$/, {}],

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
  ['POST /api/sound/generate', { id: 's-1', prompt: 'Rain on a tin roof with distant thunder', duration: 3, seed: 42, steps: 20, created: 1_790_000_000, url: TONE_URL }],

  ['POST /api/voice_cloning/voices', { id: 'v-new', name: 'E2E voice', source: 'upload' }],
  ['POST /api/voice_cloning/synthesize', { id: 'a-1', url: TONE_URL }],

  ['POST /api/voice_design/preview', { preview_id: 'p-1', url: TONE_URL }],
  ['POST /api/voice_design/save', { id: 'v-new', name: 'Designed', source: 'design' }],

  ['GET /api/voice_remix/status', { ready: true, default_script: 'This is how the new voice sounds.' }],
  ['POST /api/voice_remix/preview', { preview_id: 'p-2', url: TONE_URL }],
  ['POST /api/voice_remix/save', { id: 'v-new2', name: 'Narrator (remix)', source: 'remix' }],
];

function find(method: string, pathname: string): Reply | undefined {
  const key = `${method} ${pathname}`;
  for (const [match, reply] of ROUTES) {
    if (typeof match === 'string' ? match === key : match.test(key)) return reply;
  }
  return undefined;
}

export async function installMockBackend(page: Page) {
  await page.route(`${BACKEND}/**`, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (method === 'GET' && (url.pathname === TONE_URL || url.pathname.endsWith('.wav') || url.pathname.endsWith('/audio'))) {
      return route.fulfill({ status: 200, contentType: 'audio/wav', body: TONE });
    }
    const reply = find(method, url.pathname);
    if (reply === undefined) {
      return route.fulfill({ status: 501, contentType: 'application/json', body: JSON.stringify({ detail: `No mock for ${method} ${url.pathname}` }) });
    }
    const body = typeof reply === 'function' ? reply(url) : reply;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}
