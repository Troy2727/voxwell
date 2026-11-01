import { readFileSync } from 'node:fs';
import { dropFile, expect, fixture, openFeature, test } from './fixtures';

const SCRIPT = readFileSync(fixture('speech.txt'), 'utf8').trim();
const words = (s: string) => s.toLowerCase().replace(/[^a-z' ]/g, ' ').split(/\s+/).filter(Boolean);

/** Share of the script's words that appear in `heard`, in any order: a forgiving accuracy check. */
function recall(heard: string) {
  const got = new Set(words(heard));
  const want = words(SCRIPT);
  return want.filter((w) => got.has(w)).length / want.length;
}

test('transcribe: the transcript matches what was said; export and AI clean-up work', async ({ app: page }) => {
  await openFeature(page, 'Transcribe');
  await dropFile(page, 'speech.wav');
  await page.getByRole('main').getByRole('button', { name: 'Transcribe', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Download SRT' })).toBeVisible();

  const shown = await page.locator('[data-slot=card]').filter({ has: page.getByRole('link', { name: 'Download SRT' }) }).innerText();
  expect(recall(shown)).toBeGreaterThanOrEqual(0.8);

  const href = await page.getByRole('link', { name: 'Download SRT' }).getAttribute('href');
  const srt = await page.evaluate(async (url) => (await fetch(url!)).text(), href);
  expect(srt).toMatch(/00:00:\d\d,\d{3} --> 00:00:\d\d,\d{3}/);

  const cleanup = page.locator('[data-slot=card]').filter({ hasText: 'Clean up with AI' });
  await cleanup.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(cleanup.getByRole('heading', { name: 'Edited' })).toBeVisible();
  await cleanup.getByRole('button', { name: 'Accept' }).click();
  await expect(cleanup.getByText('Showing your accepted edit.', { exact: false })).toBeVisible();
});

test('subtitles from a script: every word is timed against the recording', async ({ app: page }) => {
  await openFeature(page, 'Transcribe');
  const align = page.locator('[data-slot=card]').filter({ hasText: 'Subtitles from a script' });
  await dropFile(page, 'speech.wav', align);
  await align.getByRole('textbox').fill(SCRIPT); // its label is not tied to the box (no htmlFor)
  await align.getByRole('button', { name: 'Align' }).click();
  const badge = align.getByText(/^\d+ of \d+ words matched$/);
  await expect(badge).toBeVisible();
  const [matched, total] = (await badge.innerText()).match(/\d+/g)!.map(Number);
  expect(matched / total).toBeGreaterThanOrEqual(0.8);
  await expect(align.getByText(/^\d:\d\d\.\d – \d:\d\d\.\d$/).first()).toBeVisible();
});
