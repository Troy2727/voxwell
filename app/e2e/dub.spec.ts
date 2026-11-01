import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { dropFile, expect, openFeature, test } from './fixtures';

test('dubbing: dub a video into Spanish, with subtitles', async ({ app: page }) => {
  await openFeature(page, 'Dubbing');
  await dropFile(page, 'video.mp4');
  await page.getByRole('button', { name: 'Start' }).click();
  await expect(page.getByText('Dubbed video', { exact: true })).toBeVisible();

  // The dubbed video plays and lasts about as long as the original (6 s).
  const video = page.locator('video');
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.duration || 0)).toBeGreaterThan(3);

  const href = await page.getByRole('link', { name: 'Download subtitles' }).getAttribute('href');
  const srt = await page.evaluate(async (url) => (await fetch(url!)).text(), href); // from the page, so mocks apply
  expect(srt).toMatch(/\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}/);
});

test('batch dub: queue several videos; a file that is not a video is refused', async ({ app: page }) => {
  await openFeature(page, 'Batch dub');
  await dropFile(page, ['video.mp4', 'bad.exe']);
  await expect(page.getByRole('button', { name: 'Remove bad.exe' })).toBeVisible();
  await page.getByRole('button', { name: 'Dub 2 videos' }).click();
  await expect(page.getByText(/^bad\.exe: /)).toBeVisible();
  await expect(page.getByText('Done', { exact: true })).toBeVisible();
});

test('batch dub: watch a folder, then stop', async ({ app: page }) => {
  await openFeature(page, 'Batch dub');
  const folder = mkdtempSync(path.join(tmpdir(), 'vx-watch-'));
  await page.getByLabel('Folder').fill(folder);
  await page.getByRole('button', { name: 'Start watching' }).click();
  await expect(page.getByText('Watching', { exact: true })).toBeVisible();
  await expect(page.getByText(/0 existing videos skipped/)).toBeVisible();
  await page.getByRole('button', { name: 'Stop watching' }).click();
  await expect(page.getByText('Off', { exact: true })).toBeVisible();
});
