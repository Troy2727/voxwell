import { BACKEND, expect, openFeature, test } from './fixtures';
import { installMockBackend } from './mock-backend';

// Mood match: the editor saves the switch, and a reply that says how it was spoken shows that mood.
test.skip(({ mode }) => mode !== 'mock', 'scripts the replies');

test('mood match is saved and the reply shows its mood', async ({ page }) => {
  await installMockBackend(page);
  const replies = [
    { reply: 'That is wonderful news!', language: 'en', mood: 'upbeat' },
    { reply: 'Plain answer.', language: 'en' },
  ];
  await page.route(`${BACKEND}/api/agents/agents/ag-1/chat`, (route) => route.fulfill({ json: { ...replies.shift(), tool_calls: [] } }));
  await page.goto('/');
  await openFeature(page, 'Voice agents');
  const main = page.getByRole('main');

  await main.getByRole('button', { name: 'New agent' }).click();
  await main.getByLabel('Name').fill('Cheerful');
  const box = main.getByRole('checkbox', { name: 'Mood match' });
  await expect(box).not.toBeChecked(); // off for a new agent
  await box.click();
  const saved = page.waitForRequest((r) => r.url().endsWith('/api/agents/agents') && r.method() === 'POST');
  await main.getByRole('button', { name: 'Save' }).click();
  expect((await saved).postDataJSON().mood_match).toBe(true);

  const input = main.getByPlaceholder('Message Cheerful');
  await input.fill('We got the job!');
  await main.getByRole('button', { name: 'Send' }).click();
  await expect(main.getByText('That is wonderful news!')).toBeVisible();
  await expect(main.getByLabel('Mood: upbeat')).toBeVisible();
  await input.fill('ok');
  await main.getByRole('button', { name: 'Send' }).click();
  await expect(main.getByText('Plain answer.')).toBeVisible();
  await expect(main.getByLabel(/^Mood:/)).toHaveCount(1); // the reply without a mood shows no badge
});
