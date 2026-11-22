import { expect, openFeature, test } from './fixtures';

test('line moods: the Stories page says how to mark a line\'s mood', async ({ app: page }) => {
  await openFeature(page, 'Stories');
  await expect(page.getByText('Start a line with [mood calm], [mood lively], [mood dramatic] or [mood intense] to change how it is delivered.')).toBeVisible();
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), { message: `no sideways scroll at ${width} px` }).toBe(true);
  }
});
