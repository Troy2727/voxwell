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
