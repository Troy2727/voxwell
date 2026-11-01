import type { Page } from '@playwright/test';
import { dropFile, ensureVoice, expect, expectAudio, openFeature, pickVoice, test } from './fixtures';

async function openTool(page: Page, name: string) {
  await openFeature(page, 'Tools');
  await page.getByRole('tab', { name }).click();
  return page.getByRole('tabpanel');
}

/** Seconds of audio in the file behind a Download link. */
async function seconds(page: Page, link: string) {
  const href = await page.getByRole('link', { name: 'Download' }).and(page.locator(`[download="${link}"]`)).getAttribute('href');
  return page.evaluate(async (url) => {
    const ctx = new AudioContext();
    try {
      return (await ctx.decodeAudioData(await (await fetch(url!)).arrayBuffer())).duration;
    } finally {
      void ctx.close();
    }
  }, href);
}

test('convert voice: re-speak a recording in a saved voice', async ({ app: page, mode }) => {
  const voice = await ensureVoice(page, mode);
  const panel = await openTool(page, 'Convert voice');
  await dropFile(page, 'speech.wav', panel);
  await pickVoice(page, mode === 'mock' ? 'Narrator' : voice, panel);
  await panel.getByRole('button', { name: 'Convert' }).click();
  await expectAudio(page, 1);
});

test('isolate voice: split a song into the voice and the background', async ({ app: page }) => {
  const panel = await openTool(page, 'Isolate voice');
  await dropFile(page, 'song.wav', panel);
  await panel.getByRole('button', { name: 'Isolate voice' }).click();
  await expect(panel.locator('[download="background.wav"]')).toBeVisible();
  expect(await seconds(page, 'voice.wav')).toBeGreaterThan(0.5);
  expect(await seconds(page, 'background.wav')).toBeGreaterThan(0.5);
});

test('AI direction: the local AI turns a note into settings, then speaks the line', async ({ app: page }) => {
  const panel = await openTool(page, 'AI direction');
  await panel.getByLabel('Line').fill('I cannot believe we finally made it home.');
  await panel.getByRole('button', { name: 'whisper it, sad and slow' }).click();
  await panel.getByRole('button', { name: 'Interpret' }).click();
  await expect(panel.getByText(/^The AI heard: “.+”/)).toBeVisible();
  await panel.getByRole('button', { name: 'Speak' }).click();
  await expectAudio(page, 1);
});

test('compare voices: the same sentence in two voices', async ({ app: page, mode }) => {
  const voice = await ensureVoice(page, mode);
  const panel = await openTool(page, 'Compare voices');
  await panel.getByLabel('Text').fill('Welcome back. Here is the news.');
  await panel.getByRole('button', { name: 'Add a voice' }).click();
  await panel.locator('button[role=combobox][aria-haspopup=dialog]').last().click();
  await page.getByRole('option', { name: new RegExp(mode === 'mock' ? 'Narrator' : voice) }).first().click();
  await panel.getByRole('button', { name: 'Compare' }).click();
  await expect(panel.locator('audio[src]')).toHaveCount(2);
});

test('fit length: stretch audio to an exact length', async ({ app: page, mode }) => {
  const panel = await openTool(page, 'Fit length');
  await dropFile(page, 'speech.wav', panel);
  await panel.getByLabel('New length in seconds').fill('3');
  await panel.getByRole('button', { name: 'Fit' }).click();
  await expect(panel.getByText(/^Was \d+\.\d\d s, now 3\.00 s\.$/)).toBeVisible();
  const length = await seconds(page, 'fitted.wav');
  if (mode === 'real') expect(length).toBeCloseTo(3, 0);
});

test('file info: format, length and streams of a video', async ({ app: page }) => {
  const panel = await openTool(page, 'File info');
  await dropFile(page, 'video.mp4', panel);
  await expect(panel.getByText(/^Video: H\.264.* · 640×360 · 25 fps$/)).toBeVisible();
  await expect(panel.getByText(/^Audio: AAC.* · 24000 Hz · mono$/)).toBeVisible();
  await expect(panel.getByText(/^5\.9\d s · /)).toBeVisible();
});
