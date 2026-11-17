import { expect, test } from '@playwright/test';
import { SILENCE_AFTER_MS, SILENCE_POLL_MS, SILENCE_RMS, isSilent } from '../src/lib/microphone';

// The Mic check decision is pure: these feed it level readings directly, no browser needed.

const NEEDED = SILENCE_AFTER_MS / SILENCE_POLL_MS;
const quiet = (n: number) => Array<number>(n).fill(0);

test('digital silence is flagged only once it has lasted long enough', () => {
  expect(isSilent([])).toBe(false);
  expect(isSilent(quiet(NEEDED - 1))).toBe(false);
  expect(isSilent(quiet(NEEDED))).toBe(true);
});

test('a quiet room is not flagged', () => {
  expect(isSilent(Array<number>(NEEDED).fill(0.002))).toBe(false); // about -54 dBFS, noise-suppressed room tone
});

test('sound clears it at once, and only the latest readings count', () => {
  expect(isSilent([...quiet(NEEDED), 0.05])).toBe(false);
  expect(isSilent([0.05, ...quiet(NEEDED)])).toBe(true);
  expect(isSilent([...quiet(NEEDED - 1), SILENCE_RMS * 2])).toBe(false);
  expect(isSilent(quiet(NEEDED).fill(SILENCE_RMS, 3))).toBe(true); // at the threshold still counts as silent
});
