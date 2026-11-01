import { BACKEND, dropFile, expect, expectAudio, openFeature, test } from './fixtures';

test('music: write lyrics with AI and generate a song', async ({ app: page, mode }) => {
  if (mode === 'real') {
    const status = await (await page.request.get(`${BACKEND}/api/music/status`)).json();
    test.skip(!status.installed, 'The music engine is not installed (about 12 GB).');
  }
  await openFeature(page, 'Music');
  await page.getByLabel('Style').fill('Dreamy synth-pop with airy female vocals and a driving bassline');
  await page.getByRole('button', { name: 'Write with AI' }).click();
  await expect(page.getByLabel('Lyrics')).toHaveValue(/\[(Verse|Chorus)/);
  await page.getByRole('button', { name: 'Generate', exact: true }).click();
  const card = page.locator('article').first();
  await expect(card.getByText(/Waiting to start|Composing|%/).first()).toBeVisible();
  await expect(card.getByRole('link', { name: 'Download' })).toBeVisible();
  await expectAudio(page, 1);
});

test('stories: cast a two-speaker script and generate it', async ({ app: page }) => {
  await openFeature(page, 'Stories');
  await page.getByLabel('Title (optional)').fill('The knock');
  await page.getByRole('button', { name: 'Use the example' }).click();
  // The backend reads the script and lists who speaks.
  await expect(page.getByText('4 lines', { exact: false })).toBeVisible();
  for (const speaker of ['Anna', 'Tom', 'Narrator']) await expect(page.getByText(speaker, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Generate story' }).click();
  await expectAudio(page, 1);
});

test('audiobook: import a book, preview a chapter, render the rest', async ({ app: page }) => {
  await openFeature(page, 'Audiobook');
  await dropFile(page, 'book.txt');
  await expect(page.getByText('The Storm', { exact: true })).toBeVisible();
  await expect(page.getByText('Morning', { exact: true })).toBeVisible();

  // Leave the second chapter out.
  await page.getByRole('checkbox', { name: 'Include Morning' }).click();
  await expect(page.getByText(/^1 of 2 chapters selected/)).toBeVisible();

  await page.getByRole('button', { name: 'Preview' }).first().click();
  await expect(page.getByText('Preview of “The Storm”')).toBeVisible();
  await expectAudio(page, 1);

  await page.getByRole('button', { name: 'Render audiobook' }).click();
  await expect(page.getByText('All selected chapters are rendered.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'WAV' })).toHaveCount(1);
  await expect(page.getByRole('link', { name: /Download all chapters/ })).toBeVisible();
});
