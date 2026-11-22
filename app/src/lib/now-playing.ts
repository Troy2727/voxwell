import { useEffect, useSyncExternalStore } from 'react';

/** What the Now playing bar holds. `nonce` changes on every hand-over, so the same clip starts over. */
export interface NowPlaying {
  src: string;
  title: string;
  source: string;
  nonce: number;
}

let current: NowPlaying | null = null;
let nonce = 0;
const listeners = new Set<() => void>();

function set(next: NowPlaying | null) {
  current = next;
  listeners.forEach((listener) => listener());
}

/** Hand a clip to the Now playing bar, which plays it from the start. */
export const playInBar = (item: Omit<NowPlaying, 'nonce'>) => set({ ...item, nonce: ++nonce });

export const closeBar = () => set(null);

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export const useNowPlaying = () => useSyncExternalStore(subscribe, () => current);

/** One clip at a time in the whole app: when any audio starts, every other audio on the page pauses. */
export function useSingleAudio() {
  useEffect(() => {
    const onPlay = (e: Event) => {
      if (!(e.target instanceof HTMLAudioElement)) return;
      for (const audio of document.querySelectorAll('audio')) if (audio !== e.target && !audio.paused) audio.pause();
    };
    document.addEventListener('play', onPlay, true); // play doesn't bubble; capture sees it
    return () => document.removeEventListener('play', onPlay, true);
  }, []);
}
