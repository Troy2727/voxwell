import { BACKEND, expect, openFeature, test } from './fixtures';
import { installMockBackend } from './mock-backend';

// Shared words: a word added under "All languages" goes to the shared list, each language shows only
// its own list, and Hear it asks which language to speak in.
test.skip(({ mode }) => mode !== 'mock', 'keeps a list per scope');

test('a word added for all languages is kept apart from each language', async ({ page }) => {
  await installMockBackend(page);
  const lists: Record<string, object[]> = {};
  const previews: string[] = [];
  await page.route(`${BACKEND}/api/pronunciation/entries**`, (route) => {
    const req = route.request();
    if (req.method() === 'GET') return route.fulfill({ json: lists[new URL(req.url()).searchParams.get('language') ?? 'en'] ?? [] });
    if (req.method() !== 'POST') return route.fallback();
    const body = req.postDataJSON();
    const entry = { id: `id-${body.word}`, word: body.word, respelling: body.respelling, case_sensitive: false, whole_word: true };
    (lists[body.language] ??= []).push(entry);
    return route.fulfill({ json: entry });
  });
  await page.route(`${BACKEND}/api/pronunciation/preview`, (route) => {
    previews.push(route.request().postDataJSON().language);
    return route.fulfill({ json: { text: 'Pregunta a win.' } });
  });
  await page.goto('/');
  await openFeature(page, 'Pronunciation');

  await page.getByRole('combobox', { name: 'Language' }).click();
  await page.getByRole('option', { name: 'All languages' }).click();
  await expect(page.getByText('No words for all languages yet.')).toBeVisible();
  await page.getByLabel('Word', { exact: true }).fill('Nguyen');
  await page.getByLabel('Respelling').fill('win');
  await page.getByRole('button', { name: 'Add word' }).click();
  await expect(page.getByText('Nguyen → win')).toBeVisible();
  expect(Object.keys(lists)).toEqual(['all']);

  await page.getByRole('combobox', { name: 'Speak in' }).click();
  await page.getByRole('option', { name: 'Spanish' }).click();
  await page.getByLabel('Sentence').fill('Pregunta a Nguyen.');
  await page.getByRole('button', { name: 'Hear it' }).click();
  await expect(page.getByText('Pregunta a win.')).toBeVisible();
  expect(previews).toEqual(['es']);

  await page.getByRole('combobox', { name: 'Language' }).click();
  await page.getByRole('option', { name: 'English' }).click();
  await expect(page.getByText('No words for this language yet.')).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Speak in' })).toHaveCount(0);
});
