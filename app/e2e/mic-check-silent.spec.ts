import type { Page } from '@playwright/test';
import { expect, fixture, openFeature, test } from './fixtures';
import { fire, installBridge, lastPhase, openWithBridge } from './fake-bridge';

// Mic check: a muted microphone (digital silence) gets a warning while still recording.
test.skip(({ mode }) => mode === 'real', 'the desktop bridge is faked');

const statusOf = (page: Page) => page.evaluate(() => window.fakeBridge.statuses.at(-1) as unknown as { phase: string; silent?: boolean });

test('the overlay swaps the waveform for the Mic check warning', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 64 });
  await page.addInitScript(installBridge);
  await page.goto('/overlay.html');
  await expect.poll(() => page.evaluate(() => window.fakeBridge.actions)).toEqual(['ready']);
  await fire(page, 'status', { phase: 'recording', startedAt: Date.now(), silent: true });
  await expect(page.getByRole('alert')).toContainText("isn't picking up any sound");
  await expect(page.getByRole('button', { name: 'Stop' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true);
  await fire(page, 'status', { phase: 'recording', startedAt: Date.now(), silent: false });
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test.use({
  permissions: ['microphone'],
  launchOptions: {
    args: [
      '--autoplay-policy=no-user-gesture-required',
      '--disable-features=LocalNetworkAccessChecks',
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${fixture('silent.wav')}`,
    ],
  },
});

test('Mic check: the shortcut tells the overlay while still recording', async ({ app: page }) => {
  await openWithBridge(page);
  await fire(page, 'toggle');
  await expect.poll(() => lastPhase(page)).toBe('recording');
  await expect.poll(async () => (await statusOf(page)).silent, { timeout: 8_000 }).toBe(true);
  await fire(page, 'toggle');
});

test('Mic check: the Dictation page warns while recording, and the warning goes away after', async ({ app: page }) => {
  await openFeature(page, 'Dictation');
  await page.getByRole('button', { name: 'Record' }).click();
  await expect(page.getByRole('alert').filter({ hasText: "isn't picking up any sound" })).toBeVisible({ timeout: 8_000 });
  await page.getByRole('button', { name: 'Stop' }).click();
  await expect(page.getByText("isn't picking up any sound")).toHaveCount(0);
});
