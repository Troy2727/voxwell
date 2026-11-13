import { BACKEND, expect, openFeature, test } from './fixtures';

test('voice cloning text: @ picks a voice, / adds a pause, Ctrl+Enter generates', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'checks the request the page sends');
  await openFeature(page, 'Voice cloning');
  const text = page.getByLabel('Text');
  const menu = page.getByRole('listbox');

  await text.fill('Hello ');
  await text.press('End');
  await text.pressSequentially('@nar');
  await expect(menu).toHaveAccessibleName('Voices');
  await expect(menu.getByRole('option')).toHaveCount(1);
  await text.press('Enter');
  await expect(menu).toBeHidden();
  await expect(text).toHaveValue('Hello '); // the typed "@nar" is gone
  await expect(page.locator('button[role=combobox][aria-haspopup=dialog]').first()).toContainText('Narrator');

  await text.pressSequentially('there /pa');
  await expect(menu).toHaveAccessibleName('Pauses and cues');
  await expect(menu.getByRole('option')).toHaveCount(3);
  await text.press('ArrowDown');
  await text.press('ArrowDown');
  await expect(menu.getByRole('option', { selected: true })).toContainText('pause-long');
  await text.press('Enter');
  await expect(text).toHaveValue('Hello there [pause 2] ');

  // / also offers the cue tags; a two-word cue is typed with a hyphen.
  await text.pressSequentially('/clear');
  await expect(menu.getByRole('option')).toHaveCount(1);
  await expect(menu.getByRole('option')).toContainText('clear-throat');
  await expect(menu.getByRole('option')).toContainText('Sounds');
  await text.press('Enter');
  await expect(text).toHaveValue('Hello there [pause 2] [clear throat] ');

  // Escape closes the menu and keeps what was typed.
  await text.pressSequentially('@');
  await expect(menu).toBeVisible();
  await text.press('Escape');
  await expect(menu).toBeHidden();
  await text.press('Backspace');
  await text.pressSequentially('friend.');

  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }

  const sent = page.waitForRequest(`${BACKEND}/api/voice_cloning/synthesize`);
  await text.press('Control+Enter');
  const body = (await sent).postDataJSON();
  expect(body.text).toBe('Hello there [pause 2] [clear throat] friend.');
  expect(body.voice_id).toBe('v-upload');
  await expect(page.locator('a[aria-label="Download"], audio[src]').last()).toBeAttached();
});

test('voice cloning text: / offers only pauses in a language without cues', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'uses the mock cue languages');
  await openFeature(page, 'Voice cloning');
  await page.getByRole('combobox', { name: 'Language' }).click();
  await page.getByRole('option', { name: 'Spanish' }).click();
  const text = page.getByLabel('Text');
  const menu = page.getByRole('listbox');
  await expect(menu).toHaveCount(0); // the language list has closed

  await text.pressSequentially('/');
  await expect(menu).toHaveAccessibleName('Pauses');
  await expect(menu.getByRole('option')).toHaveCount(3);
  await text.pressSequentially('la');
  await expect(menu).toBeHidden();
});
