import { dropFile, ensureVoice, expect, expectAudio, openFeature, pickVoice, test } from './fixtures';
import { installMockBackend } from './mock-backend';

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

test('voice cloning remembers voice, language and effects after a reload, and effects can be reset', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'Checks the request, so it only runs against the mock backend.');
  await openFeature(page, 'Voice cloning');
  await pickVoice(page, 'Narrator');
  await page.getByRole('combobox', { name: 'Language' }).click();
  await page.getByRole('option', { name: 'Spanish' }).click();
  await page.getByRole('slider', { name: 'Speed', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByText('Speed: 1.05×')).toBeVisible();

  await page.reload();
  await openFeature(page, 'Voice cloning');
  await expect(page.getByText('Speed: 1.05×')).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Language' })).toHaveText('Spanish');
  await page.getByLabel('Text').fill('Hola.');
  let sent = page.waitForRequest('**/api/voice_cloning/synthesize');
  await page.getByRole('button', { name: 'Generate' }).click();
  const body = (await sent).postDataJSON();
  expect(body).toMatchObject({ language: 'es', effects: { speed: 1.05 } });
  expect(body.voice_id).toBeTruthy();

  await page.getByRole('button', { name: 'Reset effects' }).click();
  await expect(page.getByText('Speed: 1.00×')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Reset effects' })).toHaveCount(0);
  sent = page.waitForRequest('**/api/voice_cloning/synthesize');
  await page.getByRole('button', { name: 'Generate' }).click();
  expect((await sent).postDataJSON().effects).toBeNull();
});

test('voice cloning forgets a remembered voice that was deleted', async ({ page, mode }) => {
  test.skip(mode === 'real', 'Checks the request, so it only runs against the mock backend.');
  await installMockBackend(page);
  await page.addInitScript(() => localStorage.setItem('voxwell.voice_cloning.voice', JSON.stringify('deleted-voice')));
  await page.goto('/');
  await openFeature(page, 'Voice cloning');
  await page.getByLabel('Text').fill('Hello.');
  const sent = page.waitForRequest('**/api/voice_cloning/synthesize');
  await page.getByRole('button', { name: 'Generate' }).click();
  expect((await sent).postDataJSON().voice_id).toBeNull();
});

test('a remembered setting that is unreadable falls back to the default', async ({ page, mode }) => {
  test.skip(mode === 'real', 'Mock backend only.');
  await installMockBackend(page);
  await page.addInitScript(() => localStorage.setItem('voxwell.voice_cloning.effects', '{not json'));
  await page.goto('/');
  await openFeature(page, 'Voice cloning');
  await expect(page.getByText('Speed: 1.00×')).toBeVisible();
});

test('recently used voices come first and are marked', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'Uses the mock backend voices.');
  await openFeature(page, 'Voice cloning');
  const picker = page.locator('button[role=combobox][aria-haspopup=dialog]').first();
  await picker.click();
  const options = page.getByRole('option');
  const names = await options.allInnerTexts();
  const last = names[names.length - 1].split('\n')[0];
  await options.last().click();

  await page.reload();
  await openFeature(page, 'Voice cloning');
  await picker.click();
  const after = await options.allInnerTexts();
  expect(after[0]).toContain('Default voice');
  expect(after[1]).toContain(last);
  expect(after[1]).toContain('Recent');
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
