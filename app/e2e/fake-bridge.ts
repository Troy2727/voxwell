import type { Page } from '@playwright/test';

// The desktop bridge, faked: records what the renderer reports and lets a test fire events at it.
declare global {
  interface Window {
    fakeBridge: FakeBridge;
  }
}

interface FakeBridge {
  statuses: ({ phase: string } | null)[];
  delivered: string[];
  pasteInPlace: boolean[];
  actions: string[];
  fire(event: string, value?: unknown): void;
}

export function installBridge() {
  const listeners: Record<string, ((value?: unknown) => void)[]> = {};
  const on = (event: string) => (callback: (value?: unknown) => void) => {
    (listeners[event] ??= []).push(callback);
    return () => {
      listeners[event] = listeners[event].filter((c) => c !== callback);
    };
  };
  const state: FakeBridge = {
    statuses: [],
    delivered: [],
    pasteInPlace: [],
    actions: [],
    fire: (event, value) => listeners[event]?.forEach((c) => c(value)),
  };
  Object.assign(window, {
    fakeBridge: state,
    voxwell: {
      backendUrl: 'http://127.0.0.1:8765',
      dictation: {
        onToggle: on('toggle'),
        onCancel: on('cancel'),
        onStatus: on('status'),
        deliver: async (text: string, pasteInPlace: boolean) => {
          state.delivered.push(text);
          state.pasteInPlace.push(pasteInPlace);
          return { pasted: pasteInPlace };
        },
        setStatus: (status: { phase: string } | null) => void state.statuses.push(status),
        overlayAction: (action: string) => void state.actions.push(action),
      },
      auth: { onCallback: () => () => {}, openExternal: async () => {} },
    },
  });
}

export const fire = (page: Page, event: string, value?: unknown) =>
  page.evaluate(([e, v]) => window.fakeBridge.fire(e as string, v), [event, value] as const);
export const lastPhase = (page: Page) => page.evaluate(() => window.fakeBridge.statuses.at(-1)?.phase ?? null);

export async function openWithBridge(page: Page) {
  await page.addInitScript(installBridge);
  await page.reload();
}
