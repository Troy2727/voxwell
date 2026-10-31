import { api, sendJson } from '../../api';

export interface InstallState {
  state: 'idle' | 'installing' | 'failed';
  step: string;
  percent: number;
  detail: string;
  error: string;
}

export interface MusicStatus {
  installed: boolean;
  install: InstallState;
  engine: 'stopped' | 'starting' | 'ready';
  device: 'cuda' | 'mps' | 'cpu';
  languages: Record<string, string>;
  keys: string[];
  limits: { min_seconds: number; max_seconds: number; max_prompt: number; max_lyrics: number };
}

export interface Track {
  id: string;
  title: string;
  prompt: string;
  lyrics: string;
  instrumental: boolean;
  language: string;
  duration: number;
  bpm: number | null;
  key: string;
  seed: number;
  steps: number;
  created: number;
  status: 'queued' | 'generating' | 'done' | 'failed';
  progress: number;
  stage: string;
  error: string;
  parent_id: string | null;
  edit_start: number | null;
  edit_end: number | null;
  has_reference: boolean;
  stems: boolean;
  url?: string;
  vocals_url?: string;
  instrumental_url?: string;
}

/** What the compose form sends; also what "Reuse settings" copies back into it. */
export interface Settings {
  prompt: string;
  lyrics: string;
  instrumental: boolean;
  language: string;
  duration: number;
  bpm: string;
  key: string;
  seed: string;
  steps: number;
}

export const getStatus = () => api<MusicStatus>('/api/music/status');
export const listTracks = () => api<Track[]>('/api/music/tracks');
export const installEngine = () => sendJson<{ started: boolean }>('/api/music/install', 'POST');
export const writeLyrics = (description: string, language: string) =>
  sendJson<{ lyrics: string }>('/api/music/lyrics', 'POST', { description, language });
export const editSection = (id: string, body: { start: number; end: number; prompt: string; lyrics: string }) =>
  sendJson<Track>(`/api/music/tracks/${id}/edit`, 'POST', body);
export const splitStems = (id: string) => sendJson<Track>(`/api/music/tracks/${id}/stems`, 'POST');
export const renameTrack = (id: string, title: string) => sendJson<Track>(`/api/music/tracks/${id}`, 'PATCH', { title });
export const deleteTrack = (id: string) => sendJson(`/api/music/tracks/${id}`, 'DELETE');

export function generate(settings: Settings, reference: File | null): Promise<Track> {
  const form = new FormData();
  form.set('prompt', settings.prompt);
  form.set('lyrics', settings.instrumental ? '' : settings.lyrics);
  form.set('instrumental', String(settings.instrumental));
  form.set('language', settings.language);
  form.set('duration', String(settings.duration));
  form.set('steps', String(settings.steps));
  if (settings.bpm.trim()) form.set('bpm', settings.bpm.trim());
  if (settings.key) form.set('key', settings.key);
  if (settings.seed.trim()) form.set('seed', settings.seed.trim());
  if (reference) form.set('file', reference);
  return api<Track>('/api/music/generate', { method: 'POST', body: form });
}

export const formatTime = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
