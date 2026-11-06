import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Page } from '@playwright/test';
import { BACKEND, dropFile, expect, expectAudio, openFeature, test } from './fixtures';
import { installMockBackend } from './mock-backend';

const PAGES = [
  'Voice cloning', 'Voice design', 'Sound effects', 'Music', 'Stories', 'Audiobook', 'Audio effects',
  'Voice remix', 'Saved voices', 'Gallery', 'Pronunciation',
  'Dubbing', 'Batch dub', 'Dictation', 'Transcribe', 'Live translation',
  'Tools', 'Voice agents', 'Integrations', 'Projects',
];

test('home: shows the backend is running and opens a feature', async ({ app: page }) => {
  await expect(page.getByText('Running on this computer')).toBeVisible();
  await page.getByRole('button', { name: 'Clone a voice', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Voice cloning' })).toBeVisible();
});

test('form fields are named by their visible labels, so screen readers announce them', async ({ app: page }) => {
  await openFeature(page, 'Dubbing');
  await expect(page.getByRole('combobox', { name: 'Target language' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Voice', exact: true })).toBeVisible();
  await openFeature(page, 'Transcribe');
  await expect(page.getByRole('spinbutton', { name: 'Characters per subtitle' })).toBeVisible();
  await expect(page.getByRole('spinbutton', { name: 'Seconds per subtitle' })).toBeVisible();
  await openFeature(page, 'Pronunciation');
  await expect(page.getByRole('combobox', { name: 'Language', exact: true })).toBeVisible();
});

test.describe('home', () => {
  test.skip(({ mode }) => mode === 'real', 'These fake the backend state, so they only run against the mock backend.');
  const status = (page: Page) => page.locator('[role=status].sr-only');

  test('offline: does not look like lost work, and Check again reconnects', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
    await page.goto('/');
    await expect(page.getByText("Can't reach your projects")).toBeVisible();
    await expect(page.getByText('Nothing here yet')).toHaveCount(0);
    await expect(page.getByText('These need Voxwell running on a computer.')).toBeVisible();
    await expect(status(page)).toHaveText('Not connected to Voxwell');
    await page.getByRole('button', { name: 'Check again' }).click(); // still down
    await expect(page.getByText("Still can't reach Voxwell.")).toBeVisible();
    await page.unroute(`${BACKEND}/api/health`);
    await page.getByRole('button', { name: 'Check again' }).click();
    await expect(page.getByText('Running on this computer', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /speech\.wav/ })).toBeVisible();
    await expect(status(page)).toHaveText('Connected to Voxwell');
  });

  test('a failed load says so instead of showing an empty library, and can retry', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/projects/items`, (route) => route.fulfill({ status: 500, body: '{}' }));
    await page.route(`${BACKEND}/api/voices`, (route) => route.fulfill({ status: 500, body: '{}' }));
    await page.goto('/');
    await expect(page.getByText("Couldn't load your projects")).toBeVisible();
    await expect(page.getByText("Couldn't load your voices.")).toBeVisible();
    await expect(page.getByText('Nothing here yet')).toHaveCount(0);
    await page.unroute(`${BACKEND}/api/projects/items`);
    await page.unroute(`${BACKEND}/api/voices`);
    await page.getByRole('button', { name: 'Try again' }).first().click();
    await expect(page.getByRole('button', { name: /speech\.wav/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Play Narrator' })).toBeVisible();
  });

  test('a truly empty library still says so', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/projects/items`, (route) => route.fulfill({ json: [] }));
    await page.route(`${BACKEND}/api/voices`, (route) => route.fulfill({ json: [] }));
    await page.goto('/');
    await expect(page.getByText('Nothing here yet')).toBeVisible();
    await expect(page.getByText('No saved voices yet.')).toBeVisible();
  });

  test('a recent project opens that project', async ({ app: page }) => {
    await page.getByRole('button', { name: /speech\.wav/ }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Projects' })).toBeVisible();
    await expect(page.locator('#project-transcript-tr-1')).toBeFocused();
    await expect(page.locator('#project-transcript-tr-1')).toBeInViewport();
    expect(new URL(page.url()).hash).toBe('');
  });

  test('saved voices and finished clips play from Home, one at a time', async ({ app: page }) => {
    await page.getByRole('button', { name: 'Play Narrator' }).click();
    await expect(page.getByRole('button', { name: 'Pause Narrator' })).toBeVisible();
    await page.getByRole('button', { name: /^Play A project/ }).click();
    await expect(page.getByRole('button', { name: /^Pause A project/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Play Narrator' })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Play speech\.wav/ })).toHaveCount(0); // a transcript has no audio
  });

  test('recent work shows a relative date', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/projects/items`, (route) =>
      route.fulfill({ json: [{ kind: 'speech', id: 'sp-1', title: 'Just made', created: Date.now() / 1000, language: 'en', voice: 'default', text: 'x', audio_url: '/mock/tone.wav' }] }));
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'speech Just made today' })).toBeVisible();
  });

  test('recent projects line up with the heading and each other, with or without a play button', async ({ app: page }) => {
    const left = async (selector: ReturnType<typeof page.locator>) => (await selector.boundingBox())!.x;
    const right = async (selector: ReturnType<typeof page.locator>) => {
      const box = (await selector.boundingBox())!;
      return box.x + box.width;
    };
    const playable = page.getByRole('button', { name: /^speech A project/ });
    const silent = page.getByRole('button', { name: /^transcript speech\.wav/ });
    await expect(silent).toBeVisible();
    expect(await right(playable.locator('span').last())).toBeCloseTo(await right(silent.locator('span').last()), 0);
    expect(await left(playable.locator('span').first())).toBeCloseTo(await left(page.getByText('Recent projects')), 0);
  });

  test('a clip that will not load says so', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/voices/v-upload/audio`, (route) => route.fulfill({ status: 404, body: '' }));
    await page.getByRole('button', { name: 'Play Narrator' }).click();
    await expect(page.getByText("Couldn't play that clip.")).toBeVisible();
    await expect(page.getByRole('button', { name: 'Play Narrator' })).toBeVisible();
  });

  test('the hero tools are not repeated in the tiles', async ({ app: page }) => {
    const main = page.getByRole('main');
    await expect(main.getByRole('button', { name: /^Voice design/ })).toBeVisible();
    await expect(main.getByRole('button', { name: /^Voice cloning/ })).toHaveCount(0);
    await expect(main.getByRole('button', { name: /^Dubbing/ })).toHaveCount(0);
  });

  test('keyboard users can skip the sidebar', async ({ app: page }) => {
    await expect(page.getByText('Recent projects')).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#main')).toBeFocused();
    expect(new URL(page.url()).hash).toBe('');
  });
});

test('every page opens without an error and fits phone, tablet and desktop widths', async ({ app: page }) => {
  test.setTimeout(5 * 60_000);
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const title of ['Home', ...PAGES]) {
      if (width < 768) {
        await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click(); // the menu is a sheet on a phone
      }
      if (title === 'Home') {
        await page.locator('[data-sidebar="menu-button"]', { hasText: /^Home$/ }).click(); // its heading is a greeting
        await expect(page.getByText('Recent projects')).toBeVisible();
      } else {
        await openFeature(page, title);
      }
      await page.waitForLoadState('networkidle');
      await expect.soft(page.getByRole('main').locator('[data-slot=alert][role=alert]').filter({ hasText: /\S/ }), `${title} at ${width}px`).toHaveCount(0);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect.soft(overflow, `${title} scrolls sideways at ${width}px`).toBeLessThanOrEqual(0);
    }
  }
});

test('every slider has a name a screen reader can announce', async ({ app: page }) => {
  for (const title of PAGES) {
    await openFeature(page, title);
    await page.waitForLoadState('networkidle');
    for (const slider of await page.getByRole('main').getByRole('slider').all()) {
      await expect.soft(slider, `a slider on ${title}`).toHaveAccessibleName(/\S/);
    }
  }
});

test('a result waveform seeks from the keyboard and reads its time', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'Serves the result itself, so it only runs against the mock backend.');
  // Browsers seek only in media served with byte ranges, as the real backend does; the shared mock does not.
  const tone = readFileSync(path.join(__dirname, 'fixtures', 'tone.wav'));
  await page.route('**/mock/tone.wav', (route) => {
    const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers().range ?? '');
    if (!range) return route.fulfill({ body: tone, contentType: 'audio/wav', headers: { 'accept-ranges': 'bytes' } });
    const start = Number(range[1]);
    const end = range[2] ? Number(range[2]) : tone.length - 1;
    return route.fulfill({
      status: 206,
      body: tone.subarray(start, end + 1),
      contentType: 'audio/wav',
      headers: { 'accept-ranges': 'bytes', 'content-range': `bytes ${start}-${end}/${tone.length}` },
    });
  });
  await openFeature(page, 'Audio effects');
  await dropFile(page, 'speech.wav');
  await page.getByRole('button', { name: 'Apply effects' }).click();
  await expectAudio(page);
  const scrubber = page.getByRole('slider', { name: 'Audio waveform scrubber' }).last();
  await expect(scrubber).toHaveAttribute('aria-valuetext', /^0:00 of \d+:\d\d$/);
  await scrubber.focus();
  await page.keyboard.press('ArrowRight');
  await expect(scrubber).toHaveAttribute('aria-valuetext', /^0:0[1-9] of /);
  await page.keyboard.press('Home');
  await expect(scrubber).toHaveAttribute('aria-valuetext', /^0:00 of /);
});

test('a dropped file of the wrong type is refused with a message', async ({ app: page }) => {
  await openFeature(page, 'Audio effects');
  const zone = page.getByRole('button', { name: /Drop a file here/ });
  const drop = async (name: string, type: string) => {
    const data = await page.evaluateHandle(([n, t]) => {
      const d = new DataTransfer();
      d.items.add(new File(['x'], n, { type: t }));
      return d;
    }, [name, type]);
    await zone.dispatchEvent('drop', { dataTransfer: data });
  };
  await drop('notes.txt', 'text/plain');
  await expect(page.getByText("This page can't use notes.txt.")).toBeVisible();
  await expect(zone).toBeVisible(); // nothing was picked
  await drop('clip.wav', 'audio/wav');
  await expect(page.getByText('clip.wav')).toBeVisible();
});

test('a running job announces its step and reports its progress', async ({ app: page, mode }) => {
  test.skip(mode === 'real', 'Relies on the mock job passing through a known running step.');
  await openFeature(page, 'Stories');
  await dropFile(page, 'subtitles.srt');
  await page.getByRole('button', { name: 'Generate from subtitles' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Line 2 of 4' })).toBeVisible();
  await expect(page.getByRole('progressbar', { name: 'Line 2 of 4' })).toHaveAttribute('aria-valuenow', '50');
});

test('integrations: shows the local API and records a phone greeting', async ({ app: page }) => {
  await openFeature(page, 'Integrations');
  await expect(page.getByText(`${BACKEND}/v1`).first()).toBeVisible();
  // Installing the agent skill writes into the user's home folder, so it is not clicked here.
  await page.getByLabel('Greeting').fill('Hi! You have reached the end to end test.');
  await page.getByRole('button', { name: /^(Record greeting|Record again)$/ }).click();
  await expect(page.getByRole('button', { name: 'Record again' })).toBeVisible();
  await expectAudio(page, 1);
});

test.describe('errors the user can see', () => {
  test.skip(({ mode }) => mode === 'real', 'These fake the failures, so they only run against the mock backend.');

  test('backend offline: the app says so, then recovers when it comes back', async ({ page }) => {
    await installMockBackend(page); // not the app fixture: health must fail before the first load
    await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
    await page.goto('/');
    await expect(page.getByText("Voxwell isn't running on this computer")).toBeVisible(); // the Home status line
    await expect(page.getByRole('alert')).toHaveCount(0); // no banner above every page
    await page.unroute(`${BACKEND}/api/health`);
    await expect(page.getByText('Running on this computer', { exact: true })).toBeVisible({ timeout: 15_000 });
  });

  test('backend offline on the website: Home links to the install steps', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Install it' })).toHaveAttribute('href', 'https://github.com/Troy2727/voxwell#-quick-start');
    await expect(page.getByRole('alert')).toHaveCount(0); // still no banner
    await page.unroute(`${BACKEND}/api/health`);
    await expect(page.getByText('Running on this computer', { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('link', { name: 'Install it' })).toHaveCount(0);
  });

  test('backend offline in the desktop app: Home offers no install link', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
    await page.addInitScript(() => {
      const off = () => () => {};
      Object.assign(window, { voxwell: { backendUrl: 'http://127.0.0.1:8765', dictation: { onToggle: off, onCancel: off }, auth: { onCallback: off } } });
    });
    await page.clock.install();
    await page.goto('/');
    // It starts its own backend, so at first a failed check only means it's still starting.
    await expect(page.getByRole('main').getByText('Connecting…')).toBeVisible();
    await expect(page.getByText("Voxwell isn't running on this computer")).toHaveCount(0);
    await page.clock.fastForward('02:05');
    await expect(page.getByText("Voxwell isn't running on this computer")).toBeVisible();
    await expect(page.getByRole('link', { name: 'Install it' })).toHaveCount(0);
  });

  test('backend starting in the desktop app: Home goes straight to running once it answers', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
    await page.addInitScript(() => {
      const off = () => () => {};
      Object.assign(window, { voxwell: { backendUrl: 'http://127.0.0.1:8765', dictation: { onToggle: off, onCancel: off }, auth: { onCallback: off } } });
    });
    await page.goto('/');
    await expect(page.getByRole('main').getByText('Connecting…')).toBeVisible();
    await page.unroute(`${BACKEND}/api/health`);
    await expect(page.getByText('Running on this computer', { exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Voxwell isn't running on this computer")).toHaveCount(0);
  });

  test('an action with no backend says what to do, not "Failed to fetch"', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/audio_effects/apply`, (route) => route.abort('connectionrefused'));
    await openFeature(page, 'Audio effects');
    await dropFile(page, 'speech.wav');
    await page.getByRole('button', { name: 'Apply effects' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Start the Voxwell app or run voxwell serve' })).toBeVisible();
    await expect(page.getByText('Failed to fetch')).toHaveCount(0);
  });

  const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15';
  const BROWSERS = [
    { device: 'an iPhone', userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1', touchPoints: 5, advice: /Voxwell runs on a computer/ },
    { device: 'an Android phone', userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36', touchPoints: 5, advice: /Voxwell runs on a computer/ },
    { device: 'an iPad, which reports itself as a Mac', userAgent: MAC, touchPoints: 5, advice: /Voxwell runs on a computer/ },
    { device: 'a Mac', userAgent: MAC, touchPoints: 0, advice: /Start the Voxwell app or run voxwell serve/ },
  ];
  for (const { device, userAgent, touchPoints, advice } of BROWSERS) {
    test.describe(() => {
      test.use({ userAgent });

      test(`an action with no backend on ${device} gives advice that device can follow`, async ({ app: page }) => {
        await page.evaluate((points) => Object.defineProperty(navigator, 'maxTouchPoints', { value: points }), touchPoints);
        await page.route(`${BACKEND}/api/audio_effects/apply`, (route) => route.abort('connectionrefused'));
        await openFeature(page, 'Audio effects');
        await dropFile(page, 'speech.wav');
        await page.getByRole('button', { name: 'Apply effects' }).click();
        await expect(page.getByRole('alert').filter({ hasText: advice })).toBeVisible();
      });

      test(`Home with no backend on ${device} says what that device can do`, async ({ page }) => {
        await installMockBackend(page);
        await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
        await page.addInitScript((points) => Object.defineProperty(navigator, 'maxTouchPoints', { value: points }), touchPoints);
        await page.goto('/');
        const isComputer = touchPoints === 0;
        await expect(page.getByText(isComputer ? "Voxwell isn't running on this computer" : 'Voxwell runs on a computer, not a phone or tablet')).toBeVisible();
        await expect(page.getByRole('link', { name: 'Install it' })).toHaveCount(isComputer ? 1 : 0);
      });
    });
  }

  test('a script that cannot load: the page says so, not a blank screen', async ({ page }) => {
    await page.route('**/src/main.tsx', (route) => route.abort());
    await page.goto('/');
    await expect(page.getByText("Loading Voxwell… If this doesn't go away, check your connection and reload the page.")).toBeVisible();
  });

  test('a page that crashes: it says so and offers a reload, not a blank screen', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/projects/items`, (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ length: 1 }) }));
    await page.goto('/');
    await expect(page.getByRole('alert').filter({ hasText: 'Something went wrong' })).toBeVisible();
    await page.unroute(`${BACKEND}/api/projects/items`);
    await page.getByRole('button', { name: 'Reload' }).click();
    await expect(page.getByText('Running on this computer', { exact: true })).toBeVisible();
  });

  const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

  test.describe('on a phone', () => {
    test.use({ userAgent: IPHONE, viewport: { width: 390, height: 844 } });

    const openHome = async (page: Page) => {
      await installMockBackend(page);
      await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
      await page.goto('/');
    };

    test('Home saves the private address, opens it, and remembers it', async ({ page }) => {
      await openHome(page);
      const main = page.getByRole('main');
      await expect(main.getByText('Use Voxwell from your phone', { exact: true })).toBeVisible();
      await main.getByLabel("Your computer's private address").fill('  desktop-1.tail123.ts.net  ');
      await main.getByRole('button', { name: 'Save address' }).click();
      const saved = main.getByText('desktop-1.tail123.ts.net');
      await expect(saved).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

      await page.reload();
      await expect(saved).toBeVisible();
      await main.getByRole('button', { name: 'Change address' }).click();
      await expect(main.getByLabel("Your computer's private address")).toBeVisible();
    });

    test('with a saved address, Home goes to Dictation on this website, not away from it', async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem('voxwell.phone.address', JSON.stringify('https://desktop-1.tail123.ts.net')));
      await openHome(page);
      const main = page.getByRole('main');
      await expect(main.locator('a[href*="ts.net"]')).toHaveCount(0);
      await main.getByRole('button', { name: 'Open Dictation' }).click();
      await expect(page.getByRole('heading', { level: 1, name: 'Dictation' })).toBeVisible();
    });

    for (const bad of ['https://evil.example', 'http://desktop-1.tail123.ts.net', 'javascript:alert(1)', 'https://desktop.ts.net.evil.example', 'https://user:pass@desktop-1.tail123.ts.net', 'not an address']) {
      test(`Home refuses ${bad} as the address`, async ({ page }) => {
        await openHome(page);
        const main = page.getByRole('main');
        await main.getByLabel("Your computer's private address").fill(bad);
        await main.getByRole('button', { name: 'Save address' }).click();
        await expect(main.getByText('It ends in .ts.net.')).toBeVisible();
        await expect(main.getByRole('button', { name: 'Change address' })).toHaveCount(0);
      });
    }

    test('a saved address that was tampered with is ignored', async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem('voxwell.phone.address', JSON.stringify('https://evil.example')));
      await openHome(page);
      await expect(page.getByRole('main').getByRole('button', { name: 'Change address' })).toHaveCount(0);
    });

    test('the Dictation page offers it too', async ({ page }) => {
      await openHome(page);
      await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click();
      await openFeature(page, 'Dictation');
      await expect(page.getByRole('main').getByText('Use Voxwell from your phone', { exact: true })).toBeVisible();
    });

    test('an action with no backend points to it', async ({ page }) => {
      await openHome(page);
      await page.route(`${BACKEND}/api/audio_effects/apply`, (route) => route.abort('connectionrefused'));
      await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click();
      await openFeature(page, 'Audio effects');
      await dropFile(page, 'speech.wav');
      await page.getByRole('button', { name: 'Apply effects' }).click();
      await expect(page.getByRole('alert').filter({ hasText: 'Use Voxwell from your phone' })).toBeVisible();
    });

    test('with a saved address, every page uses the computer: Home connects and Gallery lists its voices', async ({ page }) => {
      const PRIVATE = 'https://desktop-1.tail123.ts.net';
      const json = (body: unknown) => ({ status: 200, headers: { 'Access-Control-Allow-Origin': '*' }, contentType: 'application/json', body: JSON.stringify(body) });
      const preset = (id: string, name: string) => ({ id, name, category: 'Narration', gender: 'Female', description: `${name}.`, sample: 'Hi.', ready: false, audio_url: null });
      const local: string[] = [];
      await page.route(`${BACKEND}/**`, (route) => {
        local.push(route.request().url());
        return route.abort('connectionrefused');
      });
      await page.route(`${PRIVATE}/**`, (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/health') return route.fulfill(json({ status: 'ok' }));
        if (path === '/api/gallery/presets') return route.fulfill(json([preset('calm', 'Calm Narrator'), preset('bright', 'Bright Storyteller')]));
        return route.fulfill(json([]));
      });
      await page.addInitScript((a) => localStorage.setItem('voxwell.phone.address', JSON.stringify(a)), PRIVATE);
      await page.goto('/');
      await expect(page.getByText('Connected to your computer', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click();
      await openFeature(page, 'Gallery');
      await expect(page.getByRole('main').getByText('2 voices', { exact: true })).toBeVisible();
      await expect(page.getByRole('main').getByText('Calm Narrator', { exact: true })).toBeVisible();
      expect(local).toEqual([]);
    });

    test('with a saved address the computer does not answer: Home says so, not that phones are unsupported', async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem('voxwell.phone.address', JSON.stringify('https://desktop-1.tail123.ts.net')));
      await page.route('https://desktop-1.tail123.ts.net/**', (route) => route.abort('connectionrefused'));
      await page.goto('/');
      await expect(page.getByText("Can't reach your computer", { exact: true })).toBeVisible();
    });
  });

  test('a computer browser and the desktop app do not offer it', async ({ page }) => {
    await installMockBackend(page);
    await page.route(`${BACKEND}/api/health`, (route) => route.abort('connectionrefused'));
    await page.goto('/');
    await expect(page.getByText("Voxwell isn't running on this computer")).toBeVisible();
    await expect(page.getByRole('main').getByText('Use Voxwell from your phone', { exact: true })).toHaveCount(0);
  });

  test('a file that is too large: the server message is shown', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/voice_cloning/voices`, (route) =>
      route.fulfill({ status: 413, contentType: 'application/json', body: JSON.stringify({ detail: 'The file is too large. The limit is 50 MB.' }) }));
    await openFeature(page, 'Voice cloning');
    await page.getByLabel('Name').fill('Too big');
    await dropFile(page, 'speech.wav');
    await page.getByRole('button', { name: 'Upload voice' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'The file is too large. The limit is 50 MB.' })).toBeVisible();
  });

  test('invalid input: every validation message is shown', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/voice_cloning/synthesize`, (route) =>
      route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: [{ msg: 'Text is too long.' }, { msg: 'Unknown language.' }] }) }));
    await openFeature(page, 'Voice cloning');
    await page.getByLabel('Text').fill('Hello');
    await page.getByRole('button', { name: 'Generate' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Text is too long. Unknown language.' })).toBeVisible();
  });

  test('a server crash: its plain-text message is shown, not a blank page', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/audio_effects/apply`, (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: 'Internal Server Error' }));
    await openFeature(page, 'Audio effects');
    await dropFile(page, 'speech.wav');
    await page.getByRole('button', { name: 'Apply effects' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Internal Server Error' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1, name: 'Audio effects' })).toBeVisible();
  });

  test('an empty recording is refused with a message', async ({ app: page }) => {
    await page.route(`${BACKEND}/api/tools/probe`, (route) =>
      route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'The file has no audio or video.' }) }));
    await openFeature(page, 'Tools');
    await page.getByRole('tab', { name: 'File info' }).click();
    await dropFile(page, 'empty.wav', page.getByRole('tabpanel'));
    await expect(page.getByRole('alert').filter({ hasText: 'The file has no audio or video.' })).toBeVisible();
  });
});
