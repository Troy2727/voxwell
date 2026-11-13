import { expect, test } from '@playwright/test';
import { CUT_IN_GRACE_MS, CUT_IN_THRESHOLD, CutInDetector, WINDOW_MS } from '../src/features/agents/cutIn';

// The cut-in detector is pure: these feed it level readings directly, no browser needed.

/** Feeds `ms` of windows at `rms` starting at `from`; whether it triggered, and the time after. */
function run(d: CutInDetector, rms: number, ms: number, from: number): [boolean, number] {
  let fired = false;
  let now = from;
  for (let t = 0; t < ms; t += WINDOW_MS) {
    fired = d.feed(rms, now) || fired;
    now += WINDOW_MS;
  }
  return [fired, now];
}

const LOUD = CUT_IN_THRESHOLD * 2;

test('a short burst does not cut in, a long enough one does', () => {
  expect(run(new CutInDetector(), LOUD, 200, 1000)[0]).toBe(false);
  expect(run(new CutInDetector(), LOUD, 260, 1000)[0]).toBe(true);
});

test('a short dip inside speech does not reset it, a longer quiet does', () => {
  const d = new CutInDetector();
  let [, now] = run(d, LOUD, 160, 1000);
  [, now] = run(d, 0, 40, now);
  expect(run(d, LOUD, 100, now)[0]).toBe(true);

  const e = new CutInDetector();
  [, now] = run(e, LOUD, 160, 1000);
  [, now] = run(e, 0, 80, now);
  expect(run(e, LOUD, 100, now)[0]).toBe(false);
});

test('nothing counts just after playback starts', () => {
  const d = new CutInDetector();
  d.grace(1000);
  expect(run(d, LOUD, CUT_IN_GRACE_MS, 1000)[0]).toBe(false);
});

test('the agent own voice below the raised threshold never cuts in', () => {
  expect(run(new CutInDetector(), CUT_IN_THRESHOLD * 0.8, 5000, 1000)[0]).toBe(false);
});
