import type { Page } from '@playwright/test';
import { BACKEND, expect, openFeature, test } from './fixtures';
import { TONE_URL } from './mock-backend';

/** Speech requests wait until released, so takes can be added while one renders. */
async function slowSpeech(page: Page, { held = true } = {}) {
  const sent: { text: string; start: number; end?: number }[] = [];
  const gates: (() => void)[] = [];
  await page.route(`${BACKEND}/api/voice_cloning/synthesize`, async (route) => {
    const entry: { text: string; start: number; end?: number } = { text: route.request().postDataJSON().text, start: Date.now() };
    sent.push(entry);
    if (held) await new Promise<void>((resolve) => gates.push(resolve));
    else await new Promise((resolve) => setTimeout(resolve, 300));
    entry.end = Date.now();
    if (entry.text.startsWith('Fail')) {
      return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Speech synthesis failed; see the Voxwell log.' }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'a-1', url: TONE_URL }) });
  });
  return {
    sent,
    release: () => {
      held = false;
      gates.splice(0).forEach((open) => open());
    },
  };
}

const textBox = (page: Page) => page.locator('#clone-text');
const queue = (page: Page) => page.getByRole('list').filter({ has: page.getByText(/Position \d|Generating|Done|Failed/) });

async function add(page: Page, text: string) {
  await textBox(page).fill(text);
  await page.getByRole('button', { name: /^(Generate|Queue this take)/ }).click();
}

test.describe('take queue', () => {
  test('takes added while one renders run one at a time, in order, each as it was typed', async ({ app: page }) => {
    const speech = await slowSpeech(page);
    await openFeature(page, 'Voice cloning');
    await add(page, 'First take.');
    await expect(page.getByRole('button', { name: /^Queue this take/ })).toBeVisible();
    await add(page, 'Second take.');
    await add(page, 'Third take.');
    await expect(page.getByText('Queued. 2 waiting.')).toBeVisible();
    await expect(queue(page).getByText('Position 1')).toBeVisible();
    await expect(queue(page).getByText('Position 2')).toBeVisible();
    await expect(page.getByRole('button', { name: /^Queue this take/ }).getByText('2')).toBeVisible();
    expect(speech.sent.map((s) => s.text)).toEqual(['First take.']);

    speech.release();
    await expect(queue(page).getByText('Done', { exact: true })).toHaveCount(3);
    await expect(page.getByText('Take ready: Third take.')).toBeVisible();
    expect(speech.sent.map((s) => s.text)).toEqual(['First take.', 'Second take.', 'Third take.']);
    for (let i = 1; i < speech.sent.length; i++) expect(speech.sent[i].start).toBeGreaterThanOrEqual(speech.sent[i - 1].end!);
    await expect(page.getByRole('button', { name: 'Generate', exact: true })).toBeVisible();
  });

  test('waiting takes can be removed one by one or all at once, and are never sent', async ({ app: page }) => {
    const speech = await slowSpeech(page);
    await openFeature(page, 'Voice cloning');
    for (const text of ['Keep me.', 'Drop me.', 'Drop me too.', 'And me.']) await add(page, text);
    await page.getByRole('button', { name: 'Drop this take: Drop me.' }).click();
    await expect(queue(page).getByText('Drop me.', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'Remove waiting' }).click();
    await expect(queue(page)).toHaveCount(0); // one take left, still running: no list
    speech.release();
    await expect(page.getByText('Take ready: Keep me.')).toBeVisible();
    expect(speech.sent.map((s) => s.text)).toEqual(['Keep me.']);
  });

  test('a failed take shows why and the next one still runs; finished rows can be cleared', async ({ app: page }) => {
    await slowSpeech(page, { held: false });
    await openFeature(page, 'Voice cloning');
    await add(page, 'Fail this one.');
    await add(page, 'After the failure.');
    await expect(queue(page).getByText('Failed', { exact: true })).toBeVisible();
    await expect(queue(page).getByText('Speech synthesis failed; see the Voxwell log.')).toBeVisible();
    await expect(queue(page).getByText('Done', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Clear finished' }).click();
    await expect(queue(page)).toHaveCount(0);
  });

  test('the queue stops taking more at its limit', async ({ app: page }) => {
    await slowSpeech(page);
    await openFeature(page, 'Voice cloning');
    await add(page, 'Running.');
    for (let i = 1; i <= 50; i++) {
      await textBox(page).fill(`Waiting ${i}.`);
      await textBox(page).press('Control+Enter');
    }
    await expect(page.getByRole('button', { name: /^Queue this take/ }).getByText('50')).toBeVisible();
    await add(page, 'One too many.');
    await expect(page.getByText('The queue is full (50 takes). Wait for some to finish first.')).toBeVisible();
    await expect(queue(page).getByText('One too many.')).toHaveCount(0);
  });

  test('the queue keeps going while you are on another page', async ({ app: page }) => {
    const speech = await slowSpeech(page);
    await openFeature(page, 'Voice cloning');
    await add(page, 'Before leaving.');
    await add(page, 'Also before leaving.');
    await openFeature(page, 'Voice design');
    speech.release();
    await expect.poll(() => speech.sent.filter((s) => s.end).length).toBe(2);
    await openFeature(page, 'Voice cloning');
    await expect(queue(page).getByText('Done', { exact: true })).toHaveCount(2);
  });

  test('Ctrl+Enter adds a take; with no text it adds nothing', async ({ app: page }) => {
    const speech = await slowSpeech(page);
    await openFeature(page, 'Voice cloning');
    await textBox(page).press('Control+Enter');
    await textBox(page).fill('From the keyboard.');
    await textBox(page).press('Control+Enter');
    await expect.poll(() => speech.sent.map((s) => s.text)).toEqual(['From the keyboard.']);
  });

  test('a queue with long text fits phone, tablet and desktop widths', async ({ app: page }) => {
    await slowSpeech(page);
    await openFeature(page, 'Voice cloning');
    await add(page, 'x'.repeat(300));
    await add(page, 'y'.repeat(300));
    await expect(queue(page).getByText('Position 1')).toBeVisible();
    for (const width of [390, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), { message: `no sideways scroll at ${width} px` }).toBe(true);
    }
  });
});
