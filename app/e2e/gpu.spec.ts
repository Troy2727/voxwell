import { BACKEND, expect, openFeature, test } from './fixtures';

const LABEL = 'Move the speech model to system RAM when idle';
const SETTING = `${BACKEND}/api/voice_cloning/free-the-gpu`;

test.describe('free the gpu', () => {
  test('saves the choice, and a failed save puts it back and says so', async ({ app: page }) => {
    const sent: unknown[] = [];
    let fail = false;
    await page.route(SETTING, async (route) => {
      if (route.request().method() !== 'PUT') return route.fallback();
      sent.push(route.request().postDataJSON());
      if (fail) return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: "Couldn't save this setting." }) });
      return route.fallback();
    });
    await openFeature(page, 'Voice cloning');
    const box = page.getByRole('checkbox', { name: LABEL });
    await expect(box).not.toBeChecked();
    await expect(page.getByText('Frees graphics memory for other apps')).toBeVisible();
    for (const width of [390, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), `no sideways scroll at ${width} px`).toBe(true);
    }

    await box.click();
    await expect(box).toBeChecked();
    expect(sent).toEqual([{ enabled: true }]);

    fail = true;
    await box.click();
    await expect(page.getByText("Couldn't save this setting. Try again.")).toBeVisible();
    await expect(box).toBeChecked();
  });

  test('on a computer without a GPU it says the setting has no effect', async ({ app: page }) => {
    await page.route(SETTING, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ enabled: false, device: 'cpu' }) }));
    await openFeature(page, 'Voice cloning');
    await expect(page.getByText('the model already lives in system RAM and this has no effect')).toBeVisible();
  });
});
