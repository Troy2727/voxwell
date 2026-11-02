import { BACKEND, expect, expectAudio, openFeature, test } from './fixtures';

test('pronunciation: teach a word, hear it, then remove it', async ({ app: page }) => {
  await openFeature(page, 'Pronunciation');
  await page.getByLabel('Word', { exact: true }).fill('Nguyen');
  await page.getByLabel('Respelling').fill('win');
  await page.getByRole('button', { name: 'Add word' }).click();
  await expect(page.getByText('Saved "Nguyen"')).toBeVisible();
  const row = page.locator('div').filter({ hasText: /^Nguyen → win/ }).last();
  await expect(row).toBeVisible();

  await page.getByLabel('Sentence').fill('Ask Ms. Nguyen about it.');
  await page.getByRole('button', { name: 'Hear it' }).click();
  await expectAudio(page, 1);

  await page.getByRole('button', { name: 'Delete' }).last().click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText('No words for this language yet.')).toBeVisible();
});

test('projects: what you made is listed; rename and delete it', async ({ app: page, mode }) => {
  if (mode === 'real') {
    // Something to find: one line of speech, which Voice cloning saves to Projects.
    const res = await page.request.post(`${BACKEND}/api/voice_cloning/synthesize`, { data: { text: 'A project for the end to end test.', language: 'en', voice_id: null, effects: null } });
    expect(res.ok(), await res.text()).toBeTruthy();
  }
  await openFeature(page, 'Projects');
  const card = page.locator('[data-slot=card]').filter({ hasText: 'A project for the end to end test.' }).first();
  await expect(card).toBeVisible();
  await expect(card.getByText('Speech', { exact: true })).toBeVisible();

  await card.getByRole('button', { name: 'Rename' }).click();
  const editing = page.locator('[data-slot=card]').filter({ has: page.getByRole('textbox') });
  await editing.getByRole('textbox').fill('E2E project');
  await editing.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Renamed', { exact: true })).toBeVisible();

  const renamed = page.locator('[data-slot=card]').filter({ has: page.getByRole('heading', { name: mode === 'mock' ? /end to end test/ : 'E2E project' }) }).first();
  await renamed.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText(/^Deleted "/)).toBeVisible();
});

test('voice agents: make an agent with the calculator and ask it a sum', async ({ app: page, mode }) => {
  await openFeature(page, 'Voice agents');
  await page.getByRole('button', { name: 'New agent' }).click();
  await page.getByLabel('Name', { exact: true }).fill('E2E maths helper');
  await page.getByLabel('Instructions').fill('You help with arithmetic. Use the calculator for every sum and answer in one short sentence.');
  await page.locator('label').filter({ hasText: /^calculator/ }).getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Talk to E2E maths helper')).toBeVisible();

  await page.getByPlaceholder('Message E2E maths helper').fill('What is 17 times 23?');
  await page.getByRole('button', { name: 'Send' }).click();
  // The spoken reply says the answer, and the tool call it made is shown under it.
  try {
    await expect(page.locator('p').filter({ hasText: /391/ }).first()).toBeVisible({ timeout: 3 * 60_000 });
    await expect(page.getByText(/^calculator\(/)).toBeVisible();
  } finally {
    if (mode === 'real') {
      const agents: { id: string; name: string }[] = await (await page.request.get(`${BACKEND}/api/agents/agents`)).json();
      for (const a of agents.filter((a) => a.name === 'E2E maths helper')) await page.request.delete(`${BACKEND}/api/agents/agents/${a.id}`);
    }
  }
});
