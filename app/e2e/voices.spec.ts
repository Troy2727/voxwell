import { dropFile, ensureVoice, expect, expectAudio, openFeature, pickVoice, test } from './fixtures';

test('voice cloning: upload a clip, then speak in that voice', async ({ app: page }) => {
  await openFeature(page, 'Voice cloning');
  await page.getByLabel('Name').fill('E2E voice');
  await dropFile(page, 'speech.wav');
  await expect(page.getByText('speech.wav')).toBeVisible();
  await page.getByRole('button', { name: 'Upload voice' }).click();
  await expect(page.getByText('Saved "E2E voice"')).toBeVisible();

  await page.getByLabel('Text').fill('Hello from the end to end test.');
  await page.getByRole('button', { name: 'Generate' }).click();
  await expectAudio(page, 1);
});

test('voice design: describe, preview and save a voice', async ({ app: page }) => {
  await openFeature(page, 'Voice design');
  await page.getByRole('button', { name: /^Energetic young male narrator/ }).click();
  await expect(page.getByLabel('Description')).toHaveValue(/Energetic young male narrator/);
  await page.getByRole('button', { name: 'Preview' }).click();
  await expectAudio(page, 0.5);
  await page.getByLabel('Voice name').fill('E2E designed');
  await page.getByRole('button', { name: 'Save to voices' }).click();
  await expect(page.getByText(/Saved ".+" to your voices\./)).toBeVisible();
});

test('voice cloning: pause buttons add a tag at the cursor, and speed and pitch reach the server', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'Checks the request, so it only runs against the mock backend.');
  await openFeature(page, 'Voice cloning');
  const text = page.getByLabel('Text');
  await text.fill('Hello there');
  await text.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(5, 5));
  await page.getByRole('button', { name: 'Medium pause' }).click();
  await expect(text).toHaveValue('Hello [pause 1] there');
  await expect(text).toBeFocused();
  await page.keyboard.type('X');
  await expect(text).toHaveValue('Hello [pause 1] Xthere'); // the cursor lands right after the tag

  const speed = page.getByRole('slider', { name: 'Speed', exact: true });
  await speed.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByText('Speed: 1.05×')).toBeVisible();
  const pitch = page.getByRole('slider', { name: 'Pitch', exact: true });
  await pitch.focus();
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByText('Pitch: -0.5 semitones')).toBeVisible();

  const sent = page.waitForRequest('**/api/voice_cloning/synthesize');
  await page.getByRole('button', { name: 'Generate' }).click();
  expect((await sent).postDataJSON().effects).toMatchObject({ speed: 1.05, pitch: -0.5 });
});

test('voice cloning: untouched speed and pitch send no effects at all', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'Checks the request, so it only runs against the mock backend.');
  await openFeature(page, 'Voice cloning');
  await page.getByLabel('Text').fill('Plain speech.');
  const sent = page.waitForRequest('**/api/voice_cloning/synthesize');
  await page.getByRole('button', { name: 'Generate' }).click();
  expect((await sent).postDataJSON().effects).toBeNull();
});

test('voice remix: remix a saved voice and save it', async ({ app: page, mode }) => {
  const voice = await ensureVoice(page, mode);
  await openFeature(page, 'Voice remix');
  await pickVoice(page, mode === 'mock' ? 'Narrator' : voice);
  await page.getByLabel('Describe the new voice').fill('A young woman with a bright voice speaks quickly and cheerfully.');
  await page.getByRole('button', { name: 'Remix', exact: true }).click();
  await expectAudio(page, 0.5);
  await expect(page.getByLabel('Name for the new voice')).toHaveValue(/\(remix\)$/);
  await page.getByRole('button', { name: 'Save to voices' }).click();
  await expect(page.getByRole('button', { name: 'Remix this one further' })).toBeVisible();
});
