import { expect, fixture, openFeature, recall, test } from './fixtures';

// The microphone is Chromium's fake device playing mic.wav (1 s silence, the script, 3 s silence) on a loop.
test.use({
  permissions: ['microphone'],
  launchOptions: {
    args: [
      '--autoplay-policy=no-user-gesture-required',
      '--disable-features=LocalNetworkAccessChecks',
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${fixture('mic.wav')}`,
    ],
  },
});

/** Wait until some element under `scope` holds most of the script, and return its text. */
async function heard(scope: import('@playwright/test').Locator) {
  let best = '';
  await expect.poll(async () => {
    for (const text of await scope.allInnerTexts()) if (recall(text) > recall(best)) best = text;
    return recall(best);
  }, { timeout: 5 * 60_000 }).toBeGreaterThanOrEqual(0.6);
  return best;
}

test('live translation: speak English, read and hear it in Spanish', async ({ app: page }) => {
  await openFeature(page, 'Live translation');
  await page.getByRole('main').getByRole('button', { name: 'Start' }).click();
  const conversation = page.locator('[data-slot=card]').filter({ hasText: 'Conversation' });
  await heard(conversation.locator('p'));
  await page.getByRole('main').getByRole('button', { name: 'Stop' }).click();
  // Each turn shows what was said, then its translation.
  expect(await conversation.locator('p').count()).toBeGreaterThanOrEqual(2);
});

test('dictation: record, stop, and get the text', async ({ app: page }) => {
  await openFeature(page, 'Dictation');
  await page.getByRole('main').getByRole('button', { name: 'Record' }).click();
  await expect(page.getByText(/● Recording 0:0[5-9]/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole('main').getByRole('button', { name: 'Stop' }).click();
  const result = page.locator('[data-slot=card]').filter({ hasText: 'Result' });
  await heard(result.locator('p'));
  await expect(page.getByRole('main').getByRole('button', { name: 'Copy' }).first()).toBeVisible();
});

test('dictation live: text appears turn by turn while speaking', async ({ app: page }) => {
  await openFeature(page, 'Dictation');
  await page.getByRole('tab', { name: 'Live' }).click();
  await page.getByRole('button', { name: 'Start live' }).click();
  const transcript = page.locator('[data-slot=card]').filter({ hasText: 'Live transcript' });
  await heard(transcript.locator('p'));
  await page.getByRole('main').getByRole('button', { name: 'Stop' }).click();
  await expect(page.getByRole('button', { name: 'Start live' })).toBeVisible({ timeout: 60_000 });
});
