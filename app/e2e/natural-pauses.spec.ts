import type { Page } from '@playwright/test';
import { BACKEND, dropFile, expect, openFeature, test } from './fixtures';

/** The JSON bodies the page sends to `path` (the mock still answers them). */
async function bodies(page: Page, path: string, method = 'POST') {
  const sent: Record<string, unknown>[] = [];
  await page.route(`${BACKEND}${path}`, (route) => {
    if (route.request().method() === method) sent.push(route.request().postDataJSON());
    return route.fallback();
  });
  return sent;
}

const box = (page: Page) => page.getByRole('switch', { name: 'Natural pauses' });

test.describe('natural pauses', () => {
  test.skip(({ mode }) => mode === 'real', 'checks what the pages send');

  test('voice cloning: off by default, and sent with each take once on', async ({ app: page }) => {
    const sent = await bodies(page, '/api/voice_cloning/synthesize');
    await openFeature(page, 'Voice cloning');
    await expect(box(page)).not.toBeChecked();
    await page.locator('#clone-text').fill('Hello. [pause 1] Bye.');
    await page.getByRole('button', { name: 'Generate' }).click();
    await expect.poll(() => sent.length).toBe(1);
    await box(page).click();
    await page.getByRole('button', { name: 'Generate' }).click();
    await expect.poll(() => sent.map((b) => b.natural_pauses)).toEqual([false, true]);
    for (const width of [390, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), { message: `no sideways scroll at ${width} px` }).toBe(true);
    }
  });

  test('stories: the story is made with it', async ({ app: page }) => {
    const sent = await bodies(page, '/api/stories/jobs');
    await openFeature(page, 'Stories');
    await page.getByLabel('Script', { exact: true }).fill('Anna: Hi.\nTom: Hello.');
    await expect(box(page)).not.toBeChecked();
    await box(page).click();
    await page.getByRole('button', { name: 'Generate story' }).click();
    await expect.poll(() => sent.map((b) => b.natural_pauses)).toEqual([true]);
  });

  test('audiobook: a book setting, saved with the book', async ({ app: page }) => {
    const sent = await bodies(page, '/api/audiobook/books/b-1', 'PATCH');
    await openFeature(page, 'Audiobook');
    await dropFile(page, 'book.txt');
    await expect(page.getByText('The Storm', { exact: true })).toBeVisible();
    await expect(box(page)).not.toBeChecked();
    await box(page).click();
    await expect(box(page)).toBeChecked();
    expect(sent).toEqual([{ natural_pauses: true }]);
  });
});
