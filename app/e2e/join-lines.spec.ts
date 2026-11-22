import { BACKEND, expect, openFeature, test } from './fixtures';

const SCRIPT = 'Anna: Did you hear that?\nAnna: Over there.\nTom: No.';
const JOINED = 'Anna: Did you hear that? Over there.\nTom: No.';

test.describe('join lines', () => {
  test.skip(({ mode }) => mode === 'real', 'stubs the join request to check what the page sends');

  test('joins the line at the cursor with the next, says so, and can be undone', async ({ app: page }) => {
    const sent: unknown[] = [];
    await page.route(`${BACKEND}/api/stories/join`, (route) => {
      sent.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ script: JOINED, joined: 1, too_long: 0, line: 1 }) });
    });
    await openFeature(page, 'Stories');
    const box = page.getByLabel('Script', { exact: true });
    await box.fill(SCRIPT);
    await box.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(3, 3));
    await page.getByRole('button', { name: 'Join lines' }).click();
    await expect(box).toHaveValue(JOINED);
    await expect(page.getByRole('status').filter({ hasText: 'Joined 1 line.' })).toBeVisible();
    expect(sent).toEqual([{ script: SCRIPT, first_line: 1, last_line: 2 }]);

    for (const width of [390, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), { message: `no sideways scroll at ${width} px` }).toBe(true);
    }

    await page.getByRole('button', { name: 'Undo join' }).click();
    await expect(box).toHaveValue(SCRIPT);
    await expect(page.getByRole('button', { name: 'Undo join' })).toHaveCount(0);
  });

  test('a selection sends every line it touches, and nothing to join says why', async ({ app: page }) => {
    const sent: { first_line: number; last_line: number }[] = [];
    await page.route(`${BACKEND}/api/stories/join`, (route) => {
      sent.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ script: SCRIPT, joined: 0, too_long: 0, line: 2 }) });
    });
    await openFeature(page, 'Stories');
    const box = page.getByLabel('Script', { exact: true });
    await box.fill(SCRIPT);
    const secondLine = SCRIPT.indexOf('Anna: Over');
    await box.evaluate((el: HTMLTextAreaElement, from) => el.setSelectionRange(from, el.value.length), secondLine);
    await page.getByRole('button', { name: 'Join lines' }).click();
    await expect(page.getByText('Nothing to join. Lines need the same speaker and no blank line between them.')).toBeVisible();
    expect(sent.map((s) => [s.first_line, s.last_line])).toEqual([[2, 3]]);
    await expect(box).toHaveValue(SCRIPT);
  });
});
