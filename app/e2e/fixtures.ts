import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test as base, expect, type Page } from '@playwright/test';
import { installMockBackend } from './mock-backend';

export type Mode = 'mock' | 'real';

export const BACKEND = 'http://127.0.0.1:8765';

/** A file in e2e/fixtures/. */
export const fixture = (name: string) => path.join(__dirname, 'fixtures', name);

export const test = base.extend<{ mode: Mode; app: Page }>({
  mode: ['mock', { option: true }],
  /** The app, open on the home page, with the backend faked in mock mode. */
  app: async ({ page, mode }, use) => {
    if (mode === 'mock') await installMockBackend(page);
    await page.goto('/');
    await use(page);
  },
});

export { expect };

/** Open a feature from the sidebar by its title. */
export async function openFeature(page: Page, title: string) {
  await page.locator('[data-sidebar="menu-button"]', { hasText: new RegExp(`^${title}$`) }).click();
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible();
}

/** Pick a file through a FileDrop: its hidden input sits inside the drop button. */
export async function dropFile(page: Page, file: string, scope = page.locator('body')) {
  await scope.locator('input[type=file]').first().setInputFiles(fixture(file));
}

/** Choose an entry in a VoicePicker (the "Choose a voice" combobox). */
export async function pickVoice(page: Page, name: string, scope = page.locator('body')) {
  // The picker is a popover trigger; the collection filter next to it is a plain select.
  await scope.locator('button[role=combobox][aria-haspopup=dialog]').first().click();
  await page.getByRole('option', { name: new RegExp(name) }).first().click();
}

/** An AudioResult that loaded real audio: its <audio> element reports a duration. */
export async function expectAudio(page: Page, minSeconds = 0.5) {
  const download = page.getByRole('link', { name: 'Download' }).last();
  await expect(download).toBeVisible();
  const src = await download.getAttribute('href');
  expect(src).toBeTruthy();
  const seconds = await page.evaluate(async (url) => {
    const ctx = new AudioContext();
    try {
      const buffer = await ctx.decodeAudioData(await (await fetch(url)).arrayBuffer());
      return buffer.duration;
    } finally {
      void ctx.close();
    }
  }, src!);
  expect(seconds).toBeGreaterThanOrEqual(minSeconds);
  return seconds;
}

/** In real mode, a saved voice made from the speech fixture, so voice pickers have something to pick. */
export async function ensureVoice(page: Page, mode: Mode, name = 'E2E voice') {
  if (mode === 'mock') return name;
  const voices: { name: string }[] = await (await page.request.get(`${BACKEND}/api/voices`)).json();
  if (voices.some((v) => v.name === name)) return name;
  const res = await page.request.post(`${BACKEND}/api/voice_cloning/voices`, {
    multipart: { name, file: { name: 'speech.wav', mimeType: 'audio/wav', buffer: readFileSync(fixture('speech.wav')) } },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return name;
}
