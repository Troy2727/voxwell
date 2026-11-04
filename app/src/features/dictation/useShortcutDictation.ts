import { useEffect } from 'react';
import { DICTATED_EVENT, dictationChoices, openMicrophone, transcribeRecording } from './capture';

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * Records for the global dictation shortcut. It belongs in the app shell: pages unmount when you
 * navigate away, and the shortcut has to work from anywhere. The overlay window only displays what
 * this reports, and sends Stop and Cancel back.
 */
export function useShortcutDictation() {
  useEffect(() => {
    const bridge = window.voxwell?.dictation;
    if (!bridge) return;
    let recorder: MediaRecorder | null = null;
    let busy = false; // opening the microphone or transcribing
    let cancelled = false;
    let disposed = false;

    const transcribe = async (blob: Blob, language: string) => {
      busy = true;
      bridge.setStatus({ phase: 'transcribing' });
      try {
        const text = await transcribeRecording(blob, language);
        if (text) {
          await bridge.deliver(text);
          window.dispatchEvent(new CustomEvent(DICTATED_EVENT, { detail: text }));
          bridge.setStatus({ phase: 'done', text });
        } else {
          bridge.setStatus({ phase: 'error', message: 'No speech detected.' });
        }
      } catch (e) {
        bridge.setStatus({ phase: 'error', message: messageOf(e) });
      } finally {
        busy = false;
      }
    };

    const start = async () => {
      busy = true;
      const { language, device } = dictationChoices;
      let stream: MediaStream;
      try {
        stream = await openMicrophone(device);
      } catch (e) {
        bridge.setStatus({ phase: 'error', message: messageOf(e) });
        busy = false;
        return;
      }
      if (disposed) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (ev) => {
        if (ev.data.size) chunks.push(ev.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        recorder = null;
        if (cancelled) {
          cancelled = false;
          bridge.setStatus(null);
        } else {
          void transcribe(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }), language);
        }
      };
      recorder = rec;
      rec.start();
      busy = false;
      bridge.setStatus({ phase: 'recording', startedAt: Date.now(), deviceId: device || undefined });
    };

    const cancel = () => {
      if (recorder?.state !== 'recording') return;
      cancelled = true;
      recorder.stop();
    };

    const offToggle = bridge.onToggle(() => {
      if (recorder) {
        if (recorder.state === 'recording') recorder.stop();
      } else if (!busy) {
        void start();
      }
    });
    const offCancel = bridge.onCancel(cancel);
    return () => {
      disposed = true;
      offToggle();
      offCancel();
      cancel();
    };
  }, []);
}
