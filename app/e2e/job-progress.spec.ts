import { BACKEND, dropFile, expect, openFeature, test } from './fixtures';

test('job progress: pixel loader, step, elapsed timer and percent while a dub runs', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'drives a timed fake job');

  // A dub that runs for about 9 s: first with no percent (the bar pulses), then counting up.
  let started = 0;
  await page.route(`${BACKEND}/api/dubbing/jobs/d-1`, (route) => {
    const s = (Date.now() - (started ||= Date.now())) / 1000;
    const body =
      s < 3 ? { id: 'd', state: 'running', step: 'Downloading the translation model', percent: null, error: null }
      : s < 9 ? { id: 'd', state: 'running', step: 'Translating', percent: Math.round(20 + (s - 3) * 12), error: null }
      : { id: 'd', state: 'done', step: '', percent: 100, error: null };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await openFeature(page, 'Dubbing');
  await dropFile(page, 'video.mp4');
  await page.getByRole('button', { name: 'Start' }).click();

  const step = page.getByRole('status').filter({ hasText: 'Downloading the translation model' });
  await expect(step).toBeVisible();
  const row = step.locator('..');
  await expect(row.locator('[data-pixel-grid] > span')).toHaveCount(9); // the 3x3 pixel grid
  await expect(row.getByText(/^\d+%$/)).toHaveCount(0); // no percent reported yet

  // The loader row fits every width without pushing the page sideways.
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }

  // The elapsed timer ticks.
  const elapsed = row.locator('[data-elapsed]');
  const first = parseFloat((await elapsed.textContent())!);
  await expect.poll(async () => parseFloat((await elapsed.textContent())!)).toBeGreaterThan(first + 1);

  // Then a step with a percent; the timer keeps counting from the start of the job.
  const translating = page.getByRole('status').filter({ hasText: 'Translating' }).locator('..');
  await expect(translating.getByText(/^\d+%$/)).toBeVisible();
  expect(parseFloat((await translating.locator('[data-elapsed]').textContent())!)).toBeGreaterThan(2.5);

  await expect(page.getByText('Dubbed video', { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('status').filter({ hasText: 'Translating' })).toHaveCount(0);
});
