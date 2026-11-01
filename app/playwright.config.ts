import { defineConfig, devices } from '@playwright/test';
import type { Mode } from './e2e/fixtures';

/**
 * Two runs of the same specs:
 * - `mock`: the backend is faked (e2e/mock-backend.ts), so it runs anywhere, CI included.
 * - `real`: the running backend with real models (`voxwell serve`, VOXWELL_DATA_DIR pointed at a
 *   scratch folder). Slow on a CPU, so tests get minutes; every run is recorded on video.
 */
export default defineConfig<{ mode: Mode }>({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
    // Headless Chromium cannot show the Local Network Access prompt; the flag stands in for "Allow".
    launchOptions: { args: ['--autoplay-policy=no-user-gesture-required', '--disable-features=LocalNetworkAccessChecks'] },
  },
  projects: [
    { name: 'mock', use: { mode: 'mock' }, timeout: 30_000 },
    {
      name: 'real',
      use: { mode: 'real', video: { mode: 'on', size: { width: 1440, height: 900 } }, trace: 'retain-on-failure' },
      timeout: 15 * 60_000,
      expect: { timeout: 10 * 60_000 },
    },
  ],
  webServer: {
    command: 'npx vite --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    // Sign-in off: the app opens straight to the dashboard when no Supabase project is set.
    env: { VITE_SUPABASE_URL: '', VITE_SUPABASE_PUBLISHABLE_KEY: '' },
  },
});
