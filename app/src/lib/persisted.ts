import { useState } from 'react';

/** The saved value for `key`, or null if there is none or storage is blocked or holds something unreadable. */
export function readSaved(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? null : JSON.parse(raw);
  } catch {
    return null;
  }
}

export function writeSaved(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage can be blocked; the value still holds until the page closes */
  }
}

/** useState that survives a reload, kept in this browser only. `revive` adapts what was saved to today's shape. */
export function usePersisted<T>(key: string, initial: T, revive: (saved: unknown) => T = (saved) => saved as T) {
  const [value, setValue] = useState<T>(() => {
    const saved = readSaved(key);
    return saved === null ? initial : revive(saved);
  });
  const set = (next: T) => {
    writeSaved(key, next);
    setValue(next);
  };
  return [value, set] as const;
}
