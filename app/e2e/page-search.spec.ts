import { expect, test } from './fixtures';

test('search pages: Ctrl K filters pages live, Enter opens one, no match says so', async ({ app: page }) => {
  await page.keyboard.press('Control+k');
  const dialog = page.getByRole('dialog', { name: 'Search pages' });
  await expect(dialog).toBeVisible();

  const input = dialog.getByPlaceholder('Go to a page…');
  await input.pressSequentially('dub');
  const options = dialog.getByRole('option');
  await expect(options.filter({ hasText: 'Batch dub' })).toBeVisible();
  await expect(options.filter({ hasText: /^\s*Dubbing$/ })).toBeVisible();
  await expect(options.filter({ hasText: 'Voice design' })).toHaveCount(0);

  await input.fill('batch');
  await page.keyboard.press('Enter');
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading', { level: 1, name: 'Batch dub' })).toBeVisible();

  await page.keyboard.press('Control+k');
  await dialog.getByPlaceholder('Go to a page…').fill('zzz');
  await expect(dialog.getByText('No page matches “zzz”.')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('search pages: the header button opens it on a phone', async ({ app: page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Search pages' }).click();
  const dialog = page.getByRole('dialog', { name: 'Search pages' });
  await dialog.getByRole('option', { name: 'Transcribe' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Transcribe' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
