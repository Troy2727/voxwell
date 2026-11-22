import { useSyncExternalStore } from 'react';
import { toast } from 'sonner';
import { api } from '../../api';
import type { EffectsSettings } from '@/components/effects-controls';
import { message } from '@/components/page';

/** What a take says and how, fixed when it is added: later edits on the page don't change it. */
export interface TakeRequest {
  text: string;
  language: string;
  voiceId: string | null;
  voiceName: string;
  effects: EffectsSettings | null;
}

export type TakeStatus = 'waiting' | 'running' | 'done' | 'failed';

export interface Take extends TakeRequest {
  id: number;
  status: TakeStatus;
  url?: string;
  cuesIgnored?: boolean;
  error?: string;
}

export const MAX_WAITING = 50;
const KEEP_FINISHED = 20;

// Module state, not React state: the queue keeps running while the user is on another page.
let takes: Take[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const finishListeners = new Set<(take: Take) => void>();

const isFinished = (t: Take) => t.status === 'done' || t.status === 'failed';

/** The text on one line, cut to 80 characters. */
export function takeLabel(text: string) {
  const chars = Array.from(text.replace(/\s+/g, ' ').trim()); // whole characters, never half an emoji
  return chars.length > 80 ? `${chars.slice(0, 79).join('')}…` : chars.join('');
}

function update(next: Take[]) {
  takes = next;
  listeners.forEach((listener) => listener());
}

function change(id: number, fields: Partial<Take>) {
  update(takes.map((t) => (t.id === id ? { ...t, ...fields } : t)));
}

export const waitingCount = () => takes.filter((t) => t.status === 'waiting').length;

/** Puts a take at the end of the queue and starts it if nothing is running; false when the queue is full. */
export function addTake(request: TakeRequest): boolean {
  if (waitingCount() >= MAX_WAITING) return false;
  const finished = takes.filter(isFinished);
  const dropped = new Set(finished.slice(0, Math.max(0, finished.length - KEEP_FINISHED)).map((t) => t.id));
  update([...takes.filter((t) => !dropped.has(t.id)), { ...request, id: nextId++, status: 'waiting' }]);
  runNext();
  return true;
}

export const removeTake = (id: number) => update(takes.filter((t) => t.id !== id || t.status !== 'waiting'));
export const removeWaiting = () => update(takes.filter((t) => t.status !== 'waiting'));
export const clearFinished = () => update(takes.filter((t) => !isFinished(t)));

/** Called with each take that finishes well, while subscribed; returns the unsubscribe. */
export function onFinished(listener: (take: Take) => void) {
  finishListeners.add(listener);
  return () => {
    finishListeners.delete(listener);
  };
}

function runNext() {
  if (takes.some((t) => t.status === 'running')) return;
  const take = takes.find((t) => t.status === 'waiting');
  if (!take) return;
  change(take.id, { status: 'running' });
  api<{ url: string; cues_ignored?: boolean }>('/api/voice_cloning/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: take.text, language: take.language, voice_id: take.voiceId, effects: take.effects }),
  })
    .then(
      (res) => {
        change(take.id, { status: 'done', url: res.url, cuesIgnored: res.cues_ignored });
        const done = takes.find((t) => t.id === take.id);
        toast.success(`Take ready: ${takeLabel(take.text)}`);
        if (done) finishListeners.forEach((listener) => listener(done));
      },
      (e: unknown) => {
        change(take.id, { status: 'failed', error: message(e) });
        toast.error(`Take failed: ${takeLabel(take.text)}`); // the page may not be open
      },
    )
    .finally(runNext);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The queue, oldest first; the page re-renders when it changes. */
export const useTakes = () => useSyncExternalStore(subscribe, () => takes);
