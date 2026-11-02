import { BACKEND, dropFile, expect, expectAudio, openFeature, test } from './fixtures';
import { installMockBackend } from './mock-backend';

const PAGES = [
  'Voice cloning', 'Voice design', 'Sound effects', 'Music', 'Stories', 'Audiobook', 'Audio effects',
  'Voice remix', 'Saved voices', 'Gallery', 'Pronunciation',
  'Dubbing', 'Batch dub', 'Dictation', 'Transcribe', 'Live translation',
  'Tools', 'Voice agents', 'Integrations', 'Projects',
];

test('home: shows the backend is running and opens a feature', async ({ app: page }) => {
  await expect(page.getByText('Running on this computer')).toBeVisible();
  await page.getByRole('button', { name: 'Clone a voice', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Voice cloning' })).toBeVisible();
});

test('every page opens without an error and fits phone, tablet and desktop widths', async ({ app: page }) => {
  test.setTimeout(5 * 60_000);
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const title of ['Home', ...PAGES]) {
      if (width < 768) {
        await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click(); // the menu is a sheet on a phone
      }
      if (title === 'Home') {
        await page.locator('[data-sidebar="menu-button"]', { hasText: /^Home$/ }).click(); // its heading is a greeting
        await expect(page.getByText('Recent projects')).toBeVisible();
      } else {
        await openFeature(page, title);
      }
      await page.waitForLoadState('networkidle');
      await expect.soft(page.getByRole('main').locator('[data-slot=alert][role=alert]').filter({ hasText: /\S/ }), `${title} at ${width}px`).toHaveCount(0);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect.soft(overflow, `${title} scrolls sideways at ${width}px`).toBeLessThanOrEqual(0);
    }
  }
});

test('every slider has a name a screen reader can announce', async ({ app: page }) => {
  for (const title of PAGES) {
    await openFeature(page, title);
    await page.waitForLoadState('networkidle');
    for (const slider of await page.getByRole('main').getByRole('slider').all()) {
      await expect.soft(slider, `a slider on ${title}`).toHaveAccessibleName(/\S/);
    }
  }
});

test('integrations: shows the local API and records a phone greeting', async ({ app: page }) => {
  await openFeature(page, 'Integrations');
  await expect(page.getByText(`${BACKEND}/v1`).first()).toBeVisible();
  // Installing the agent skill writes into the user's home folder, so it is not clicked here.
  await page.getByLabel('Greeting').fill('Hi! You have reached the end to end test.');
  await page.getByRole('button', { name: /^(Record greeting|Record again)$/ }).click();
  await expect(page.getByRole('button', { name: 'Record again' })).toBeVisible();
  await expectAudio(page, 1);
});

test.describe('errors the user can see', () => {
  test.skip(({ mode }) => mode === 'real', 'These fake the failures, so they only run against the mock backend.');

  test('backend offline: the app says so, then recovers when it comes back', async ({ page }) => {
    await installMockBackend(page); // not the app fixture: health must fail before the first load
    await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
    await page.goto('/');
    await expect(page.getByText("Voxwell isn't running on this computer").first()).toBeVisible();
    await page.unroute(`${BACKEND}/api/health`);
    await expect(page.getByText('Running on this computer', { exact: true })).toBeVisible({ timeout: 15_000 });
  });

  test('a file that is too large: the server message is shown', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/voice_cloning/voices`, (route) =>
      route.fulfill({ status: 413, contentType: 'application/json', body: JSON.stringify({ detail: 'The file is too large. The limit is 50 MB.' }) }));
    await openFeature(page, 'Voice cloning');
    await page.getByLabel('Name').fill('Too big');
    await dropFile(page, 'speech.wav');
    await page.getByRole('button', { name: 'Upload voice' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'The file is too large. The limit is 50 MB.' })).toBeVisible();
  });

  test('invalid input: every validation message is shown', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/voice_cloning/synthesize`, (route) =>
      route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: [{ msg: 'Text is too long.' }, { msg: 'Unknown language.' }] }) }));
    await openFeature(page, 'Voice cloning');
    await page.getByLabel('Text').fill('Hello');
    await page.getByRole('button', { name: 'Generate' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Text is too long. Unknown language.' })).toBeVisible();
  });

  test('a server crash: its plain-text message is shown, not a blank page', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/audio_effects/apply`, (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: 'Internal Server Error' }));
    await openFeature(page, 'Audio effects');
    await dropFile(page, 'speech.wav');
    await page.getByRole('button', { name: 'Apply effects' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Internal Server Error' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1, name: 'Audio effects' })).toBeVisible();
  });

  test('an empty recording is refused with a message', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/tools/probe`, (route) =>
      route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'The file has no audio or video.' }) }));
    await openFeature(page, 'Tools');
    await page.getByRole('tab', { name: 'File info' }).click();
    await dropFile(page, 'empty.wav', page.getByRole('tabpanel'));
    await expect(page.getByRole('alert').filter({ hasText: 'The file has no audio or video.' })).toBeVisible();
  });
});
