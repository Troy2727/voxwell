import { BACKEND, dropFile, expect, openFeature, test } from './fixtures';

test('batch dub: each video gets a task row; a failed one retries on its own', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'fakes a failing dub');

  let posts = 0;
  await page.route(`${BACKEND}/api/batch/jobs`, (route) => {
    posts += 1;
    const jobs = posts === 1 ? [{ name: 'video.mp4', id: 'd-a' }, { name: 'video.mp4', id: 'd-b' }] : [{ name: 'video.mp4', id: 'd-c' }];
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ jobs, errors: [] }) });
  });
  const seen: Record<string, number> = {};
  await page.route(new RegExp(`${BACKEND}/api/dubbing/jobs/d-[abc]$`), (route) => {
    const id = route.request().url().slice(-3);
    const n = (seen[id] = (seen[id] ?? 0) + 1);
    const body =
      id === 'd-b' ? { state: 'error', step: '', percent: 30, error: 'Ran out of GPU memory.' }
      : n < 3 ? { state: 'running', step: 'Translating', percent: 40 * n, error: null }
      : { state: 'done', step: '', percent: 100, error: null };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await openFeature(page, 'Batch dub');
  await dropFile(page, ['video.mp4', 'video.mp4']);
  await page.getByRole('button', { name: 'Dub 2 videos' }).click();

  const rows = page.locator('[data-task-state]');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toHaveAttribute('data-task-state', 'running');
  await expect(rows.nth(0)).toContainText('Running');
  await expect(rows.nth(1)).toHaveAttribute('data-task-state', 'failed');
  await expect(rows.nth(1)).toContainText('Ran out of GPU memory.'); // the error shows without expanding

  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }

  // Retry sends only the failed video, and its row runs to Done.
  await rows.nth(1).getByRole('button', { name: 'Retry' }).click();
  await expect(rows.nth(1)).toHaveAttribute('data-task-state', 'running');
  await expect(rows.nth(0)).toHaveAttribute('data-task-state', 'done', { timeout: 10_000 });
  await expect(rows.nth(1)).toHaveAttribute('data-task-state', 'done', { timeout: 10_000 });
  expect(posts).toBe(2);

  // A finished row's details say where the dub went.
  const details = rows.nth(0).getByRole('button', { name: 'Details for video.mp4' });
  await details.click();
  await expect(details).toHaveAttribute('aria-expanded', 'true');
  await expect(rows.nth(0)).toContainText('Find it in Projects');
});
