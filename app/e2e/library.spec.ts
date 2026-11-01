import { BACKEND, dropFile, ensureVoice, expect, expectAudio, openFeature, test } from './fixtures';

test('saved voices: make a collection, file a voice in it, rename and delete', async ({ app: page, mode }) => {
  const voice = await ensureVoice(page, mode, 'E2E library voice');
  const name = mode === 'mock' ? 'Narrator' : voice;
  await openFeature(page, 'Saved voices');
  const card = page.locator('[data-slot=card]').filter({ has: page.getByRole('heading', { name, exact: true }) });
  await expect(card).toBeVisible();

  await page.getByRole('button', { name: 'New collection' }).click();
  await page.getByLabel('Collection name').fill('E2E collection');
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page.getByText('Created "E2E collection"')).toBeVisible();
  await page.getByRole('button', { name: /^All \(\d+\)$/ }).click(); // creating one opens it, and it is empty

  await card.getByRole('button', { name: 'Collections' }).click();
  await page.getByRole('menuitemcheckbox', { name: mode === 'mock' ? 'Narrators' : 'E2E collection' }).click();
  await expect(page.getByText(/^(Added to|Removed from) "/)).toBeVisible();
  await page.keyboard.press('Escape');

  await card.getByRole('button', { name: 'Rename' }).click();
  // The heading turns into a text box, so the card is found by its editor now.
  const editing = page.locator('[data-slot=card]').filter({ has: page.getByRole('textbox') });
  await editing.getByRole('textbox').fill(`${name} renamed`);
  await editing.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Renamed', { exact: true })).toBeVisible();

  const renamed = page.locator('[data-slot=card]').filter({ has: page.getByRole('heading', { name: mode === 'mock' ? name : `${name} renamed`, exact: true }) });
  await renamed.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText(/^Deleted "/)).toBeVisible();

  if (mode === 'real') {
    // Leave the scratch library as we found it.
    const collections: { id: string; name: string }[] = await (await page.request.get(`${BACKEND}/api/voice_collections`)).json();
    for (const c of collections.filter((c) => c.name === 'E2E collection')) await page.request.delete(`${BACKEND}/api/voice_collections/${c.id}`);
  }
});

test('gallery: listen to a preset, then add it to my voices', async ({ app: page }) => {
  await openFeature(page, 'Gallery');
  const card = page.locator('[data-slot=card]').first();
  await card.getByRole('button', { name: 'Listen' }).click();
  await expect(card.getByRole('button', { name: 'Add to my voices' })).toBeVisible();
  await card.getByRole('button', { name: 'Add to my voices' }).click();
  await expect(card.getByText(/Added as “.+” in Saved voices\./)).toBeVisible();
});

test('audio effects: add reverb and distance to a recording', async ({ app: page }) => {
  await openFeature(page, 'Audio effects');
  await dropFile(page, 'speech.wav');
  const reverb = page.getByLabel('Reverb', { exact: true }).getByRole('slider');
  await reverb.focus();
  for (let i = 0; i < 8; i++) await page.keyboard.press('ArrowRight');
  await expect(page.getByText('Reverb: 40%')).toBeVisible();
  await page.getByRole('button', { name: 'Apply effects' }).click();
  await expectAudio(page, 1);
});

test('sound effects: generate a sound from a description', async ({ app: page, mode }) => {
  if (mode === 'real') {
    const status = await (await page.request.get(`${BACKEND}/api/sound/status`)).json();
    test.skip(!status.token_set, 'Sound effects need a Hugging Face token (Stable Audio Open is gated).');
  }
  await openFeature(page, 'Sound effects');
  await page.getByLabel('Description').fill('Rain on a tin roof with distant thunder');
  await page.getByLabel('Length (seconds)').fill('3');
  await page.getByLabel('Quality steps').fill('20');
  await page.getByRole('button', { name: 'Generate' }).click();
  await expectAudio(page, 1);
  // The new sound is first in History.
  await expect(page.getByRole('paragraph').filter({ hasText: /^Rain on a tin roof with distant thunder$/ })).toBeVisible();
});
