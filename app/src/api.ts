export const BACKEND_URL = window.voxwell?.backendUrl ?? 'http://127.0.0.1:8765';

/** Absolute backend URL, e.g. for an <audio src>. */
export function apiUrl(path: string): string {
  return BACKEND_URL + path;
}

/** Fetch JSON from the backend; throws with the server's message on a non-2xx status. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
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
  source: 'upload' | 'design';
}

export const listVoices = () => api<Voice[]>('/api/voices');
