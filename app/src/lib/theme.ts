import { useSyncExternalStore } from 'react';

/** Dark (default) or light, remembered per computer. Applied as the `dark` class on <html>. */
export type Theme = 'dark' | 'light';

const KEY = 'voxwell-theme';
const listeners = new Set<() => void>();

function read(): Theme {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

let current = read();

export function applyTheme(theme: Theme = current) {
  current = theme;
  document.documentElement.classList.toggle('dark', theme === 'dark');
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // storage blocked: the choice just isn't remembered
  }
  listeners.forEach((l) => l());
}

export function useTheme() {
  const theme = useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
  return { theme, setTheme: applyTheme };
}
