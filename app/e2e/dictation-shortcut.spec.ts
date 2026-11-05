import type { Page } from '@playwright/test';
import { expect, fixture, openFeature, test } from './fixtures';

// The desktop bridge is faked, so these drive the renderer side of the shortcut and the overlay.
test.skip(({ mode }) => mode === 'real', 'the desktop bridge is faked');

test.use({
  permissions: ['microphone'],
  launchOptions: {
    args: [
      '--autoplay-policy=no-user-gesture-required',
      '--disable-features=LocalNetworkAccessChecks',
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${fixture('mic.wav')}`,
    ],
  },
});

declare global {
  interface Window {
    fakeBridge: FakeBridge;
  }
}

interface FakeBridge {
  statuses: ({ phase: string } | null)[];
  delivered: string[];
  actions: string[];
  fire(event: string, value?: unknown): void;
}

function installBridge() {
  const listeners: Record<string, ((value?: unknown) => void)[]> = {};
  const on = (event: string) => (callback: (value?: unknown) => void) => {
    (listeners[event] ??= []).push(callback);
    return () => {
      listeners[event] = listeners[event].filter((c) => c !== callback);
    };
  };
  const state: FakeBridge = {
    statuses: [],
    delivered: [],
    actions: [],
    fire: (event, value) => listeners[event]?.forEach((c) => c(value)),
  };
  Object.assign(window, {
    fakeBridge: state,
    voxwell: {
      backendUrl: 'http://127.0.0.1:8765',
      dictation: {
        onToggle: on('toggle'),
        onCancel: on('cancel'),
        onStatus: on('status'),
        deliver: async (text: string) => void state.delivered.push(text),
        setStatus: (status: { phase: string } | null) => void state.statuses.push(status),
        overlayAction: (action: string) => void state.actions.push(action),
      },
      auth: { onCallback: () => () => {}, openExternal: async () => {} },
    },
  });
}

const fire = (page: Page, event: string, value?: unknown) =>
  page.evaluate(([e, v]) => window.fakeBridge.fire(e as string, v), [event, value] as const);
const lastPhase = (page: Page) => page.evaluate(() => window.fakeBridge.statuses.at(-1)?.phase ?? null);

async function openWithBridge(page: Page) {
  await page.addInitScript(installBridge);
  await page.reload();
}

test('the shortcut records and delivers from any page, not only Dictation', async ({ app: page }) => {
  await openWithBridge(page);
  await expect(page.getByRole('heading', { level: 1, name: 'Dictation' })).toHaveCount(0);

  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('recording');
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('done');

  const delivered = await page.evaluate(() => window.fakeBridge.delivered);
  expect(delivered).toHaveLength(1);
  expect(delivered[0]).not.toBe('');
});

test('cancelling throws the recording away', async ({ app: page }) => {
  await openWithBridge(page);
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('recording');
  await fire(page, 'cancel');
  await expect.poll(() => page.evaluate(() => window.fakeBridge.statuses.at(-1))).toBeNull();

  const seen = await page.evaluate(() => window.fakeBridge.statuses.map((s) => s?.phase ?? null));
  expect(seen).toEqual(['recording', null]);
  expect(await page.evaluate(() => window.fakeBridge.delivered)).toEqual([]);
});

test('text from the shortcut still reaches an open Dictation page', async ({ app: page }) => {
  await openWithBridge(page);
  await openFeature(page, 'Dictation');
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('recording');
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('done');
  const [delivered] = await page.evaluate(() => window.fakeBridge.delivered);
  await expect(page.getByRole('main').getByText(delivered).first()).toBeVisible();
});

test('the overlay shows each state in its small window', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 64 });
  await page.clock.install();
  await page.addInitScript(installBridge);
  await page.goto('/overlay.html');
  const fits = () => page.evaluate(() => {
    const root = document.documentElement;
    return root.scrollWidth <= innerWidth && root.scrollHeight <= innerHeight;
  });
  await expect.poll(() => page.evaluate(() => window.fakeBridge.actions)).toEqual(['ready']);

  await fire(page, 'status', { phase: 'recording', startedAt: await page.evaluate(() => Date.now()) });
  await page.clock.fastForward(65_000);
  await expect(page.getByText('1:05')).toBeVisible();
  await page.getByRole('button', { name: 'Stop' }).click();
  await page.getByRole('button', { name: 'Cancel' }).click();
  expect(await page.evaluate(() => window.fakeBridge.actions)).toEqual(['ready', 'stop', 'cancel']);
  expect(await fits()).toBe(true);

  await fire(page, 'status', { phase: 'transcribing' });
  await expect(page.getByText('Transcribing…')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop' })).toHaveCount(0);

  await fire(page, 'status', { phase: 'done', text: 'word '.repeat(200) });
  await expect(page.getByText(/Copied\. Press (Ctrl|Cmd)\+V to paste\./)).toBeVisible();
  expect(await fits()).toBe(true);
  await page.clock.fastForward(4_000);
  await expect.poll(() => page.evaluate(() => window.fakeBridge.actions.at(-1))).toBe('dismiss');

  await fire(page, 'status', { phase: 'error', message: 'No speech detected.' });
  await expect(page.getByText('No speech detected.')).toBeVisible();
  await page.getByRole('button', { name: 'Dismiss' }).click();
  expect(await page.evaluate(() => window.fakeBridge.actions.filter((a) => a === 'dismiss'))).toHaveLength(2);

  await fire(page, 'status', null);
  await expect(page.getByText('No speech detected.')).toHaveCount(0);
});

test('a backend that comes back mid-transcription keeps the recording', async ({ app: page }) => {
  await openWithBridge(page);
  let refused = 0;
  await page.route('**/api/dictation/transcribe', (route) => {
    if (refused++ < 2) return route.abort('connectionrefused');
    return route.fallback();
  });
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('recording');
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page), { timeout: 15_000 }).toBe('done');
  expect(refused).toBe(3);
  expect(await page.evaluate(() => window.fakeBridge.delivered)).toHaveLength(1);
});

test('a backend that stays away gets a plain message in the desktop app', async ({ app: page }) => {
  await page.clock.install();
  await openWithBridge(page);
  await page.route('**/api/dictation/transcribe', (route) => route.abort('connectionrefused'));
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('recording');
  await fire(page, 'toggle');
  await expect.poll(async () => {
    await page.clock.fastForward(5_000);
    return lastPhase(page);
  }).toBe('error');
  const status = await page.evaluate(() => window.fakeBridge.statuses.at(-1) as unknown as { message: string });
  expect(status.message).toBe("Voxwell's engine isn't responding. Restart the app and try again.");
});

test('dictation remembers the chosen language and sends it', async ({ app: page }) => {
  await openFeature(page, 'Dictation');
  const main = page.getByRole('main');
  await main.getByRole('combobox', { name: 'Language' }).click();
  await page.getByRole('option', { name: 'Spanish' }).click();

  await page.reload();
  await openFeature(page, 'Dictation');
  await expect(main.getByRole('combobox', { name: 'Language' })).toHaveText('Spanish');

  const sent = page.waitForRequest('**/api/dictation/transcribe');
  await main.getByRole('button', { name: 'Record' }).click();
  await main.getByRole('button', { name: 'Stop' }).click();
  expect((await sent).postData()).toMatch(/name="language"\s+es/);
  await expect(main.getByRole('button', { name: 'Copy' }).first()).toBeVisible();
  await expect(main.getByText(/Detected:/)).toHaveCount(0); // you chose it, so there's nothing to report
});

test('auto-detect says which language it heard, and that goes away with the text', async ({ app: page }) => {
  await openFeature(page, 'Dictation');
  const main = page.getByRole('main');
  await main.getByRole('button', { name: 'Record' }).click();
  await main.getByRole('button', { name: 'Stop' }).click();
  await expect(main.getByText('Detected: English. If that\'s wrong, choose your language above.')).toBeVisible();
  await main.locator('[data-slot=card]').filter({ hasText: 'Result' }).getByRole('button', { name: 'Delete' }).click();
  await expect(main.getByText(/Detected:/)).toHaveCount(0);
});

test('dictated text can be deleted from Result and from Recent', async ({ app: page }) => {
  await openFeature(page, 'Dictation');
  const main = page.getByRole('main');
  const result = main.locator('[data-slot=card]').filter({ hasText: 'Result' });
  const recent = main.locator('[data-slot=card]').filter({ hasText: 'Recent' });
  await page.evaluate(() => {
    for (const text of ['Line one', 'Line two', 'Line three']) window.dispatchEvent(new CustomEvent('voxwell:dictated', { detail: text }));
  });
  await expect(result.getByText('Line three')).toBeVisible();

  // An older line goes from Recent and leaves the current result alone.
  await recent.locator('div', { hasText: /^Line two/ }).last().getByRole('button', { name: 'Delete' }).click();
  await expect(recent.getByText('Line two')).toHaveCount(0);
  await expect(result.getByText('Line three')).toBeVisible();

  // The current result is the same text as the top of Recent, so it goes from both.
  await result.getByRole('button', { name: 'Delete' }).click();
  await expect(main.getByText('Line three')).toHaveCount(0);
  await expect(result.getByText('Nothing yet. Press Record and speak.')).toBeVisible();
  await expect(recent.getByText('Line one')).toBeVisible();

  await recent.getByRole('button', { name: 'Delete' }).click();
  await expect(recent.getByText('No transcripts yet.')).toBeVisible();
});

test('deleting the top of Recent also clears the current result', async ({ app: page }) => {
  await openFeature(page, 'Dictation');
  const main = page.getByRole('main');
  const result = main.locator('[data-slot=card]').filter({ hasText: 'Result' });
  const recent = main.locator('[data-slot=card]').filter({ hasText: 'Recent' });
  await page.evaluate(() => {
    for (const text of ['Older line', 'Newest line']) window.dispatchEvent(new CustomEvent('voxwell:dictated', { detail: text }));
  });
  await expect(result.getByText('Newest line')).toBeVisible();
  await recent.getByRole('button', { name: 'Delete' }).first().click();
  await expect(main.getByText('Newest line')).toHaveCount(0);
  await expect(result.getByText('Nothing yet. Press Record and speak.')).toBeVisible();
  await expect(recent.getByText('Older line')).toBeVisible();
});

test.describe('on the website on a phone', () => {
  const PRIVATE = 'https://desktop-1.tail123.ts.net';
  const CORS = { 'Access-Control-Allow-Origin': '*' };
  test.use({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1', viewport: { width: 390, height: 844 } });

  const openDictation = async (page: Page, address?: string) => {
    if (address) await page.addInitScript((a) => localStorage.setItem('voxwell.phone.address', JSON.stringify(a)), address);
    await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click();
    await openFeature(page, 'Dictation');
  };

  const record = async (page: Page) => {
    const main = page.getByRole('main').last();
    await main.getByRole('button', { name: 'Record' }).click();
    await main.getByRole('button', { name: 'Stop' }).click();
    return main;
  };

  test('with a saved address, recording goes to the computer and the text comes back', async ({ app: page }) => {
    await page.evaluate((a) => localStorage.setItem('voxwell.phone.address', JSON.stringify(a)), PRIVATE);
    await page.reload();
    const sent: string[] = [];
    await page.route(`${PRIVATE}/**`, (route) => {
      sent.push(route.request().url());
      return route.fulfill({ status: 200, headers: CORS, contentType: 'application/json', body: JSON.stringify({ text: 'Hola desde el teléfono.', language: 'es' }) });
    });
    await openDictation(page);
    const main = await record(page);
    await expect(main.getByText('Hola desde el teléfono.').first()).toBeVisible();
    expect(sent).toEqual([`${PRIVATE}/api/dictation/transcribe`]);
  });

  test('when the computer can not be reached, it says what to check', async ({ app: page }) => {
    await page.evaluate((a) => localStorage.setItem('voxwell.phone.address', JSON.stringify(a)), PRIVATE);
    await page.reload();
    await page.route(`${PRIVATE}/**`, (route) => route.abort('connectionrefused'));
    await openDictation(page);
    const main = await record(page);
    await expect(main.getByText(/Can't reach your computer/)).toBeVisible();
    await expect(main.getByText(/runs on a computer/)).toHaveCount(0);
  });

  test('with no saved address, it says to add one', async ({ app: page }) => {
    await page.route('**/api/dictation/transcribe', (route) => route.abort('connectionrefused'));
    await openDictation(page);
    const main = await record(page);
    await expect(main.getByText(/Save your computer's private address/)).toBeVisible();
  });

  test('a tampered saved address is not used', async ({ app: page }) => {
    await page.evaluate(() => localStorage.setItem('voxwell.phone.address', JSON.stringify('https://evil.example')));
    await page.reload();
    const evil: string[] = [];
    await page.route('https://evil.example/**', (route) => { evil.push(route.request().url()); return route.abort(); });
    await page.route('**/api/dictation/transcribe', (route) => route.abort('connectionrefused'));
    await openDictation(page);
    const main = await record(page);
    await expect(main.getByText(/Save your computer's private address/)).toBeVisible();
    expect(evil).toEqual([]);
  });

  test('the Live tab is off, since it can not work through the phone connection', async ({ app: page }) => {
    await openDictation(page);
    await expect(page.getByRole('tab', { name: 'Live' })).toBeDisabled();
  });
});

test('a computer browser ignores a saved phone address', async ({ app: page }) => {
  await page.evaluate(() => localStorage.setItem('voxwell.phone.address', JSON.stringify('https://desktop-1.tail123.ts.net')));
  await page.reload();
  const away: string[] = [];
  await page.route('https://desktop-1.tail123.ts.net/**', (route) => { away.push(route.request().url()); return route.abort(); });
  await openFeature(page, 'Dictation');
  const main = page.getByRole('main');
  await main.getByRole('button', { name: 'Record' }).click();
  await main.getByRole('button', { name: 'Stop' }).click();
  await expect(main.getByRole('button', { name: 'Copy' }).first()).toBeVisible();
  expect(away).toEqual([]);
});

test('in a browser with no backend, the Dictation page says what to do', async ({ app: page }) => {
  await page.route('**/api/dictation/transcribe', (route) => route.abort('connectionrefused'));
  await openFeature(page, 'Dictation');
  const main = page.getByRole('main');
  await main.getByRole('button', { name: 'Record' }).click();
  await main.getByRole('button', { name: 'Stop' }).click();
  await expect(main.getByText(/Start the Voxwell app or run voxwell serve/)).toBeVisible();
  await expect(main.getByText('Failed to fetch')).toHaveCount(0);
});

test.describe('in a browser with no microphone support', () => {
  test.beforeEach(async ({ app: page }) => {
    await page.addInitScript(() => Object.defineProperty(navigator, 'mediaDevices', { value: undefined }));
    await page.reload();
  });

  test('Dictation stays on screen, and Record says why it can not work', async ({ app: page }) => {
    await openFeature(page, 'Dictation');
    const main = page.getByRole('main').last();
    await main.getByRole('button', { name: 'Record' }).click();
    await expect(main.getByText(/This browser can't use a microphone here/)).toBeVisible();
    await expect(page.getByText('Something went wrong')).toHaveCount(0);
  });

  test('Live translation stays on screen, and Start says why it can not work', async ({ app: page }) => {
    await openFeature(page, 'Live translation');
    const main = page.getByRole('main').last();
    await main.getByRole('button', { name: 'Start' }).click();
    await expect(main.getByText(/This browser can't use a microphone here/)).toBeVisible();
    await expect(page.getByText('Something went wrong')).toHaveCount(0);
  });
});

test('in a browser that can not record, Record says why', async ({ app: page }) => {
  await page.addInitScript(() => Object.defineProperty(window, 'MediaRecorder', { value: undefined }));
  await page.reload();
  await openFeature(page, 'Dictation');
  const main = page.getByRole('main').last();
  await main.getByRole('button', { name: 'Record' }).click();
  await expect(main.getByText(/This browser can't use a microphone here/)).toBeVisible();
});
