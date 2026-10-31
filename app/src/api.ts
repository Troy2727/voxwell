export const BACKEND_URL = window.voxwell?.backendUrl ?? 'http://127.0.0.1:8765';

/** Absolute backend URL, e.g. for an <audio src>. */
export function apiUrl(path: string): string {
  return BACKEND_URL + path;
}

/** Backend WebSocket URL (ws://), for the live features. */
export function wsUrl(path: string): string {
  return BACKEND_URL.replace(/^http/, 'ws') + path;
}

/** The server's sentence for a failed response: FastAPI's `detail` (a string, or a list for invalid input). */
export async function errorMessage(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const detail = JSON.parse(text).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(' ');
  } catch {
    /* not JSON */
  }
  return text || `Request failed (${res.status}).`;
}

/** Fetch JSON from the backend; throws with the server's message on a non-2xx status. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init);
  if (!res.ok) throw new Error(await errorMessage(res));
  return (await res.json()) as T;
}

/** Send a JSON body (or none) with the given method; same error handling as api(). */
export const sendJson = <T,>(path: string, method: string, body?: unknown) =>
  api<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export interface Voice {
  id: string;
  name: string;
  source: 'upload' | 'design' | 'remix';
}

export const voiceSourceLabel = (source: Voice['source']) => ({ upload: 'Uploaded', design: 'Designed', remix: 'Remixed' })[source];

export const listVoices = () => api<Voice[]>('/api/voices');

export interface VoiceCollection {
  id: string;
  name: string;
  voice_ids: string[];
}

export const listVoiceCollections = () => api<VoiceCollection[]>('/api/voice_collections');
