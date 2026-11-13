import { BACKEND, dropFile, expect, openFeature, test } from './fixtures';

// Tone memory: the audiobook setting saves, says when saving failed, and the page still fits.
test.skip(({ mode }) => mode !== 'mock', 'fails a request on purpose');

test('tone memory switches on and reports a failed save', async ({ app: page }) => {
  await openFeature(page, 'Audiobook');
  await dropFile(page, 'book.txt');
  const box = page.getByRole('checkbox', { name: 'Tone memory' });
  await expect(box).not.toBeChecked();

  const saved = page.waitForRequest((r) => r.url().endsWith('/api/audiobook/books/b-1') && r.method() === 'PATCH');
  await box.click();
  expect((await saved).postDataJSON()).toEqual({ tone_memory: true });
  await expect(box).toBeChecked();

  await page.route(`${BACKEND}/api/audiobook/books/b-1`, (route) =>
    route.request().method() === 'PATCH' ? route.fulfill({ status: 409, json: { detail: 'Wait for the render to finish before changing settings.' } }) : route.fallback(),
  );
  await box.click();
  await expect(page.getByText('Wait for the render to finish before changing settings.')).toBeVisible();
  await expect(box).toBeChecked();

  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
});
