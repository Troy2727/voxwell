import { apiUrl, backendUnreachable, errorMessage, onPhoneOrTablet } from '../../api';
import { savedPhoneAddress } from '@/components/phone-dictation';

const LANGUAGE_KEY = 'voxwell.dictation.language';

function savedLanguage() {
  try {
    return localStorage.getItem(LANGUAGE_KEY) || 'auto';
  } catch {
    return 'auto'; // storage can be blocked
  }
}

/** The Dictation page's microphone and language, which the global shortcut uses too. */
export const dictationChoices = { language: savedLanguage(), device: '' };

/** Auto-detect can pick the wrong language in a noisy room, so a chosen language is kept for next time. */
export function rememberLanguage(language: string) {
  dictationChoices.language = language;
  try {
    localStorage.setItem(LANGUAGE_KEY, language);
  } catch {
    /* storage can be blocked; the choice still holds until the page closes */
  }
}

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

const PHONE_UNREACHABLE = "Can't reach your computer. Check that it's on, Voxwell is running with --remote, and Tailscale is on here.";
const PHONE_NEEDS_ADDRESS = "Voxwell runs on your computer. To dictate from this phone, Save your computer's private address above.";
const BACKEND_WAIT_MS = 30_000;
const BACKEND_RETRY_MS = 1_000;

/**
 * fetch only rejects when the backend can't be reached. The desktop app starts its own backend, so
 * it may just be starting: keep trying rather than lose what the user said. A browser has nothing
 * to wait for unless the user starts one.
 */
async function postRecording(form: FormData): Promise<Response> {
  const deadline = Date.now() + (window.voxwell ? BACKEND_WAIT_MS : 0);
  // A phone's own 127.0.0.1 has no Voxwell, so a phone sends it to the computer's private address.
  const onPhone = !window.voxwell && onPhoneOrTablet();
  const phone = onPhone ? savedPhoneAddress() : '';
  for (;;) {
    try {
      return await fetch(`${phone || apiUrl('')}/api/dictation/transcribe`, { method: 'POST', body: form });
    } catch {
      if (Date.now() >= deadline) throw new Error(phone ? PHONE_UNREACHABLE : onPhone ? PHONE_NEEDS_ADDRESS : backendUnreachable());
      await new Promise((resolve) => window.setTimeout(resolve, BACKEND_RETRY_MS));
    }
  }
}

/** Send a recording to the backend. Its text is empty when no speech was heard. */
export async function transcribeRecording(blob: Blob, language: string): Promise<{ text: string; language: string }> {
  const form = new FormData();
  form.append('file', blob, 'recording.webm');
  if (language !== 'auto') form.append('language', language);
  const res = await postRecording(form);
  if (!res.ok) throw new Error(await errorMessage(res));
  return (await res.json()) as { text: string; language: string };
}
