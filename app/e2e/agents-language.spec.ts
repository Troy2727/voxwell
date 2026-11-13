import { BACKEND, expect, openFeature, test } from './fixtures';
import { installMockBackend } from './mock-backend';

// Language follow: the editor saves the languages an agent may follow the user into, and the
// conversation labels each reply's language and carries the last one into the next request.
test.skip(({ mode }) => mode !== 'mock', 'scripts the replies');

test('an agent that follows the user labels the reply language and keeps it', async ({ page }) => {
  await installMockBackend(page);
  const sent: { language?: string }[] = [];
  const replies = [{ reply: 'Hola.', language: 'es' }, { reply: 'Sigo en español.', language: 'es' }];
  await page.route(`${BACKEND}/api/agents/agents/ag-1/chat`, (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({ json: { ...replies.shift(), tool_calls: [] } });
  });
  await page.goto('/');
  await openFeature(page, 'Voice agents');
  const main = page.getByRole('main');

  await main.getByRole('button', { name: 'New agent' }).click();
  await main.getByLabel('Name').fill('Bilingual');
  await expect(main.getByRole('checkbox', { name: 'English' })).toHaveCount(0); // the main language is not offered
  await main.getByRole('checkbox', { name: 'Spanish' }).click();
  const saved = page.waitForRequest((r) => r.url().endsWith('/api/agents/agents') && r.method() === 'POST');
  await main.getByRole('button', { name: 'Save' }).click();
  expect((await saved).postDataJSON().follow_languages).toEqual(['es']);

  const box = main.getByPlaceholder('Message Bilingual');
  await box.fill('hola');
  await main.getByRole('button', { name: 'Send' }).click();
  await expect(main.getByText('Hola.', { exact: true })).toBeVisible();
  await expect(main.getByText('Spanish', { exact: true })).toBeVisible();
  await box.fill('¿y ahora?');
  await main.getByRole('button', { name: 'Send' }).click();
  await expect(main.getByText('Sigo en español.', { exact: true })).toBeVisible();
  expect(sent.map((b) => b.language)).toEqual(['en', 'es']);
});
