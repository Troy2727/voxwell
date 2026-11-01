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
