import { expect, openFeature, test } from './fixtures';

test('voice agents: the reply streams in and its tool call is a chip that expands', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'checks the mocked reply word for word');
  await openFeature(page, 'Voice agents');
  await page.getByRole('button', { name: 'New agent' }).click();
  await page.getByLabel('Name', { exact: true }).fill('Chip check');
  await page.getByLabel('Instructions').fill('Use the calculator.');
  await page.locator('label').filter({ hasText: /^calculator/ }).getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Save', exact: true }).click();

  await page.getByPlaceholder('Message Chip check').fill('What is 17 times 23?');
  await page.getByRole('button', { name: 'Send' }).click();

  // The whole reply is in the page at once; its words fade in from a blur.
  const reply = page.locator('p').filter({ hasText: '17 times 23 is 391.' });
  await expect(reply).toHaveText('17 times 23 is 391.');
  await expect(reply.locator('span.animate-in')).toHaveCount(5);

  // The tool call is one row of chips: the tool and its argument.
  const chip = page.getByRole('button', { name: /^Called calculator/ });
  await expect(chip).toContainText('17*23');
  await expect(chip).toHaveAttribute('aria-expanded', 'false');
  await chip.click();
  await expect(chip).toHaveAttribute('aria-expanded', 'true');
  const detail = page.locator('pre').filter({ hasText: 'arguments' });
  await expect(detail).toContainText('{"expression":"17*23"}');
  await expect(detail).toContainText('result     391');

  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
});
