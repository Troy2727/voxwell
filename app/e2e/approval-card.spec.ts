import { BACKEND, dropFile, expect, openFeature, test } from './fixtures';

test('voice cloning asks whose voice it is before uploading; without consent nothing is sent', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'counts the uploads the page sends');
  let uploads = 0;
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url() === `${BACKEND}/api/voice_cloning/voices`) uploads += 1;
  });

  await openFeature(page, 'Voice cloning');
  await page.getByLabel('Name').fill('E2E voice');
  await dropFile(page, 'speech.wav');
  const card = page.getByRole('group', { name: 'Before cloning this voice' });

  // No consent: nothing is uploaded, and the page says why.
  await page.getByRole('button', { name: 'Upload voice' }).click();
  await expect(card.getByText('Whose voice is in this clip?')).toBeVisible();
  await expect(card.getByRole('button', { name: "It's my own voice" })).toBeFocused();
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
  await card.getByRole('button', { name: "Someone who hasn't agreed" }).click();
  await expect(card).toBeHidden();
  await expect(page.getByRole('alert').filter({ hasText: "only clones a voice with the speaker's permission" })).toBeVisible();
  expect(uploads).toBe(0);

  // Cancel drops it too.
  await page.getByRole('button', { name: 'Upload voice' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'permission' })).toBeHidden();
  await card.getByRole('button', { name: 'Cancel' }).click();
  await expect(card).toBeHidden();
  expect(uploads).toBe(0);

  // With the speaker's agreement, the voice is uploaded.
  await page.getByRole('button', { name: 'Upload voice' }).click();
  await card.getByRole('button', { name: 'Someone who agreed to be cloned' }).click();
  await expect(page.getByText('Saved "E2E voice"')).toBeVisible();
  expect(uploads).toBe(1);
});
