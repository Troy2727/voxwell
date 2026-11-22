import { BACKEND, expect, openFeature, pickVoice, test } from './fixtures';

test('voice pronunciation: words for one voice go to that voice\'s list', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'stubs the word lists to check what the page sends');
  const sent: { method: string; url: string; body: Record<string, unknown> | null }[] = [];
  await page.route(`${BACKEND}/api/pronunciation/entries**`, (route) => {
    const req = route.request();
    sent.push({ method: req.method(), url: req.url(), body: req.postData() ? req.postDataJSON() : null });
    if (req.method() === 'GET') return route.fulfill({ json: [] });
    return route.fulfill({ json: { id: 'e-1', word: 'Nguyen', respelling: 'nuyen', case_sensitive: false, whole_word: true } });
  });
  await openFeature(page, 'Pronunciation');
  const section = page.locator('[data-slot=card]').filter({ hasText: 'Voice pronunciation' });
  await pickVoice(page, 'Narrator', section);
  await expect(page.getByText('No words for this voice in this language yet.')).toBeVisible();
  await expect(page.getByText('Only for Narrator. Everything else comes from the language list.')).toBeVisible();
  expect(sent.at(-1)?.url).toContain('language=en&voice_id=v-upload');

  await page.getByLabel('Word', { exact: true }).fill('Nguyen');
  await page.getByLabel('Respelling').fill('nuyen');
  await page.getByRole('button', { name: 'Add word' }).click();
  await expect(page.getByText('Saved "Nguyen"')).toBeVisible();
  expect(sent.find((s) => s.method === 'POST')?.body).toMatchObject({ language: 'en', word: 'Nguyen', voice_id: 'v-upload' });

  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), { message: `no sideways scroll at ${width} px` }).toBe(true);
  }

  await pickVoice(page, 'Every voice', section);
  await expect(page.getByText('No words for this language yet.')).toBeVisible();
  expect(sent.at(-1)?.url).toMatch(/language=en$/);
});
