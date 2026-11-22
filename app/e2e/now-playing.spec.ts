import type { Page } from '@playwright/test';
import { BACKEND, expect, openFeature, test } from './fixtures';
import { TONE_URL } from './mock-backend';

const bar = (page: Page) => page.getByRole('region', { name: 'Now playing' });

async function speak(page: Page, text: string) {
  await page.locator('#clone-text').fill(text);
  await page.getByRole('button', { name: 'Generate' }).click();
  await page.getByRole('button', { name: 'Play in Now playing bar' }).click();
}

test.describe('now playing bar', () => {
  test.skip(({ mode }) => mode === 'real', 'uses the mock clip');

  test('a clip keeps playing in the bar across pages, and Close removes it', async ({ app: page }) => {
    await openFeature(page, 'Voice cloning');
    await expect(bar(page)).toHaveCount(0);
    await speak(page, 'A clip for the bar.');
    await expect(bar(page).getByText('A clip for the bar.')).toBeVisible();
    await expect(bar(page).getByText('Voice cloning')).toBeVisible();
    await expect.poll(() => bar(page).locator('audio').evaluate((a: HTMLAudioElement) => !a.paused && a.currentTime > 0)).toBe(true);

    for (const name of ['Projects', 'Voice cloning']) {
      await openFeature(page, name);
      await expect(bar(page)).toBeVisible();
      for (const width of [390, 768, 1024, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), { message: `${name}: no sideways scroll at ${width} px` }).toBe(true);
      }
    }
    expect(await bar(page).locator('audio').evaluate((a: HTMLAudioElement) => a.paused)).toBe(false);

    await bar(page).getByRole('button', { name: 'Close Now playing bar' }).click();
    await expect(bar(page)).toHaveCount(0);
  });

  test('a second clip replaces the first in the one bar', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/voice_cloning/synthesize`, (route) =>
      route.fulfill({ json: { id: 'a-2', url: `${TONE_URL}?take=${route.request().postDataJSON().text.length}` } }));
    await openFeature(page, 'Voice cloning');
    await speak(page, 'First.');
    await expect(bar(page).getByText('First.')).toBeVisible();
    await speak(page, 'The second clip.');
    await expect(bar(page)).toHaveCount(1);
    await expect(bar(page).getByText('The second clip.')).toBeVisible();
    await expect.poll(() => bar(page).locator('audio').getAttribute('src')).toContain('take=16');
  });

  test('only one clip plays at a time', async ({ app: page }) => {
    await openFeature(page, 'Voice cloning');
    await speak(page, 'Playing in the bar.');
    await expect.poll(() => bar(page).locator('audio').evaluate((a: HTMLAudioElement) => !a.paused)).toBe(true);
    await page.evaluate(async (src) => {
      const other = document.createElement('audio');
      other.src = src;
      document.body.append(other);
      await other.play();
    }, `${BACKEND}${TONE_URL}`);
    await expect.poll(() => bar(page).locator('audio').evaluate((a: HTMLAudioElement) => a.paused)).toBe(true);
    await expect(bar(page)).toBeVisible(); // paused, not closed
  });

  test('a clip that cannot be played says so, and Close still works', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/voice_cloning/synthesize`, (route) => route.fulfill({ json: { id: 'a-3', url: '/mock/missing.wav' } }));
    await page.route(`${BACKEND}/mock/missing.wav`, (route) => route.fulfill({ status: 404, body: '' }));
    await openFeature(page, 'Voice cloning');
    await speak(page, 'Gone.');
    await expect(bar(page).getByText("This audio can't be played.")).toBeVisible();
    await bar(page).getByRole('button', { name: 'Close Now playing bar' }).click();
    await expect(bar(page)).toHaveCount(0);
  });
});
