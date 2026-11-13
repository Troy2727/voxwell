/**
 * Cut-in: tells when the user starts talking over the agent, from the microphone level alone.
 *
 * The browser's echo cancellation removes most of the agent's own voice, so a level well above the
 * normal speech threshold, held for a while, is the user. A short quiet gap (a plosive) inside a run
 * does not reset it. Right after playback starts from silence, echo cancellation has not adapted
 * yet, so that moment is ignored. All numbers are starting points to tune with real tests.
 */

export const CUT_IN_THRESHOLD = 0.045; // RMS, full scale 1.0; three times the server's turn threshold
export const CUT_IN_MIN_MS = 250; // how long the level must hold
export const CUT_IN_QUIET_RESET_MS = 60; // a quiet gap longer than this resets the run
export const CUT_IN_GRACE_MS = 300; // ignored after playback starts from silence
export const WINDOW_MS = 20; // one level reading covers this much audio

export class CutInDetector {
  private run = 0;
  private quiet = 0;
  private graceUntil = 0;

  /** Playback started from silence at `now` (ms): ignore what follows for a moment. */
  grace(now: number) {
    this.graceUntil = now + CUT_IN_GRACE_MS;
    this.reset();
  }

  reset() {
    this.run = 0;
    this.quiet = 0;
  }

  /** One window's level at `now` (ms), covering `ms` of audio; true once the user has spoken over the agent long enough. */
  feed(rms: number, now: number, ms: number = WINDOW_MS): boolean {
    if (now < this.graceUntil) {
      this.reset();
      return false;
    }
    if (rms >= CUT_IN_THRESHOLD) {
      this.run += ms;
      this.quiet = 0;
    } else if (this.run > 0) {
      this.quiet += ms;
      if (this.quiet >= CUT_IN_QUIET_RESET_MS) this.reset();
    }
    return this.run >= CUT_IN_MIN_MS;
  }
}
