import type { Page } from '@playwright/test';
import { BACKEND, expect, openFeature, test } from './fixtures';
import { installMockBackend } from './mock-backend';

// Leaving a conversation (another agent, the editor, another page) or ending it must not leave
// anything behind: no open microphone, no live session, no reply spoken afterwards.
// Mock backend only: each test holds a step open (the microphone grant, a reply) at a chosen moment.
test.skip(({ mode }) => mode !== 'mock', 'holds steps of a conversation open');

const AGENTS = [
  { id: 'ag-1', name: 'Alpha', system_prompt: '', voice: '', language: 'en', tools: [], follow_languages: [], mood_match: false },
  { id: 'ag-2', name: 'Bravo', system_prompt: '', voice: '', language: 'en', tools: [], follow_languages: [], mood_match: false },
];

/** Runs in the page: the microphone waits for `__grantMic()`, and what the page opens is counted. */
function probe() {
  const w = window as unknown as {
    __probe: { granted: number; stopped: number; sockets: number; played: number };
    __grantMic: () => void;
  };
  w.__probe = { granted: 0, stopped: 0, sockets: 0, played: 0 };
  let grant: (() => void) | null = null;
  w.__grantMic = () => grant?.();
  navigator.mediaDevices.getUserMedia = async () => {
    await new Promise<void>((resolve) => (grant = resolve));
    const ctx = new AudioContext();
    const out = ctx.createMediaStreamDestination();
    ctx.createOscillator().connect(out);
    for (const track of out.stream.getTracks()) {
      const stop = track.stop.bind(track);
      track.stop = () => {
        w.__probe.stopped++;
        stop();
      };
    }
    w.__probe.granted++;
    return out.stream;
  };
  const NativeWebSocket = window.WebSocket;
  window.WebSocket = class extends NativeWebSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      if (String(url).includes('/api/agents/')) w.__probe.sockets++;
    }
  };
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
    if (this.src.startsWith('data:audio')) w.__probe.played++;
    return play.call(this);
  };
}

const counts = (page: Page) => page.evaluate(() => (window as unknown as { __probe: Record<string, number> }).__probe);

/** The fake backend with two agents, and the probe; later routes take precedence over these. */
async function prepare(page: Page) {
  await installMockBackend(page);
  await page.addInitScript(probe);
  await page.route(`${BACKEND}/api/agents/agents`, (route) =>
    route.request().method() === 'GET' ? route.fulfill({ json: AGENTS }) : route.fallback(),
  );
  await page.routeWebSocket(/\/api\/agents\/agents\/[^/]+\/live$/, () => {});
}

async function openAgents(page: Page) {
  await page.goto('/');
  await openFeature(page, 'Voice agents');
  await expect(main(page).getByText('Talk to Alpha', { exact: true })).toBeVisible();
}

const main = (page: Page) => page.getByRole('main');

test('switching agents while the microphone is being granted releases it', async ({ page }) => {
  await prepare(page);
  await openAgents(page);
  await main(page).getByRole('button', { name: 'Live conversation' }).click();
  await main(page).getByRole('button', { name: 'Bravo', exact: true }).click();
  await expect(main(page).getByText('Talk to Bravo', { exact: true })).toBeVisible();

  await page.evaluate(() => (window as unknown as { __grantMic: () => void }).__grantMic());

  await expect.poll(() => counts(page)).toMatchObject({ granted: 1, stopped: 1, sockets: 0 });
});

test('ending a live conversation before the microphone is granted opens nothing', async ({ page }) => {
  await prepare(page);
  await openAgents(page);
  await main(page).getByRole('button', { name: 'Live conversation' }).click();
  await main(page).getByRole('button', { name: 'End conversation' }).click();

  await page.evaluate(() => (window as unknown as { __grantMic: () => void }).__grantMic());

  await expect.poll(() => counts(page)).toMatchObject({ granted: 1, stopped: 1, sockets: 0 });
  await expect(main(page).getByRole('button', { name: 'Live conversation' })).toBeEnabled();
});

test('a typed reply that arrives after switching agents is not spoken', async ({ page }) => {
  await prepare(page);
  let answer: () => void = () => {};
  const answered = new Promise<void>((resolve) => (answer = resolve));
  await page.route(`${BACKEND}/api/agents/agents/ag-1/chat`, async (route) => {
    await answered;
    await route.fulfill({ json: { reply: 'Alpha answers late.', tool_calls: [], audio: 'UklGRg==' } });
  });
  await openAgents(page);
  await main(page).getByPlaceholder('Message Alpha').fill('Hello?');
  await main(page).getByRole('button', { name: 'Send' }).click();
  await expect(main(page).getByText('Thinking…')).toBeVisible();

  await main(page).getByRole('button', { name: 'Bravo', exact: true }).click();
  await expect(main(page).getByText('Talk to Bravo', { exact: true })).toBeVisible();
  const replied = page.waitForResponse(`${BACKEND}/api/agents/agents/ag-1/chat`);
  answer();
  await replied;

  await page.waitForTimeout(500); // the reply's handler runs after the response lands
  expect((await counts(page)).played).toBe(0);
  await expect(main(page).getByText('Alpha answers late.')).toHaveCount(0);
});
