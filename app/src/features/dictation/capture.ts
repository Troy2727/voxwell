import { apiUrl, errorMessage } from '../../api';

/** The Dictation page's microphone and language, which the global shortcut uses too. */
export const dictationChoices = { language: 'auto', device: '' };

/** Fired on window with the text, when the shortcut finishes, so an open Dictation page can show it. */
export const DICTATED_EVENT = 'voxwell:dictated';

/** Open the microphone; throws with a sentence for the user. */
export async function openMicrophone(device: string): Promise<MediaStream> {
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: device ? { deviceId: { exact: device } } : true });
  } catch (e) {
    const name = e instanceof DOMException ? e.name : '';
    throw new Error(
      name === 'NotAllowedError'
        ? 'Microphone access was denied. Allow it in your system or browser settings and try again.'
        : name === 'NotFoundError'
          ? 'No microphone found.'
          : `Could not open the microphone: ${e instanceof Error ? e.message : String(e)}`,
    );
  }
}

/** Send a recording to the backend and return its text, which is empty when no speech was heard. */
export async function transcribeRecording(blob: Blob, language: string): Promise<string> {
  const form = new FormData();
  form.append('file', blob, 'recording.webm');
  if (language !== 'auto') form.append('language', language);
  const res = await fetch(apiUrl('/api/dictation/transcribe'), { method: 'POST', body: form });
  if (!res.ok) throw new Error(await errorMessage(res));
  return ((await res.json()) as { text: string }).text;
}
