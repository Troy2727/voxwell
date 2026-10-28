import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy, Mic, Square } from 'lucide-react';
import { apiUrl, errorMessage } from '../../api';
import { ChoiceSelect } from '@/components/choice-select';
import { ErrorAlert, Field, Muted, Page as PageLayout, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { LiveWaveform } from '@/components/ui/live-waveform';
import { MicSelector } from '@/components/ui/mic-selector';

interface TranscribeResult {
  text: string;
  language: string;
}

const LANGUAGES: [string, string][] = [
  ['auto', 'Auto-detect'], ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['ru', 'Russian'], ['zh', 'Chinese'],
  ['ja', 'Japanese'], ['ko', 'Korean'], ['ar', 'Arabic'], ['hi', 'Hindi'], ['tr', 'Turkish'],
];

type Phase = 'idle' | 'recording' | 'transcribing';

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export default function Page() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [language, setLanguage] = useState('auto');
  const [device, setDevice] = useState('');
  const [muted, setMuted] = useState(false);
  const [text, setText] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const viaShortcut = useRef(false);
  const phaseRef = useRef<Phase>('idle');
  const languageRef = useRef(language);
  languageRef.current = language;
  const deviceRef = useRef(device);
  deviceRef.current = device;

  const setPhaseBoth = (p: Phase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const transcribe = useCallback(async (blob: Blob, deliver: boolean) => {
    setPhaseBoth('transcribing');
    try {
      const form = new FormData();
      form.append('file', blob, 'recording.webm');
      if (languageRef.current !== 'auto') form.append('language', languageRef.current);
      const res = await fetch(apiUrl('/api/dictation/transcribe'), { method: 'POST', body: form });
      if (!res.ok) throw new Error(await errorMessage(res));
      const result = (await res.json()) as TranscribeResult;
      setText(result.text);
      if (result.text) {
        setHistory((h) => [result.text, ...h].slice(0, 20));
        if (deliver) await window.voxwell?.dictation.deliver(result.text);
      } else {
        setError('No speech detected.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPhaseBoth('idle');
    }
  }, []);

  const start = useCallback(
    async (fromShortcut: boolean) => {
      setError('');
      setCopied(false);
      viaShortcut.current = fromShortcut;
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: deviceRef.current ? { deviceId: { exact: deviceRef.current } } : true });
      } catch (e) {
        const name = e instanceof DOMException ? e.name : '';
        setError(
          name === 'NotAllowedError'
            ? 'Microphone access was denied. Allow it in your system or browser settings and try again.'
            : name === 'NotFoundError'
              ? 'No microphone found.'
              : `Could not open the microphone: ${e instanceof Error ? e.message : String(e)}`,
        );
        return;
      }
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (ev) => {
        if (ev.data.size) chunks.push(ev.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        window.clearInterval(timer.current);
        void transcribe(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }), viaShortcut.current);
      };
      recorder.current = rec;
      rec.start();
      setElapsed(0);
      timer.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
      setPhaseBoth('recording');
    },
    [transcribe],
  );

  const toggle = useCallback(
    (fromShortcut: boolean) => {
      if (phaseRef.current === 'recording') {
        if (recorder.current?.state === 'recording') recorder.current.stop();
      } else if (phaseRef.current === 'idle') {
        void start(fromShortcut);
      }
    },
    [start],
  );

  useEffect(() => window.voxwell?.dictation.onToggle(() => toggle(true)), [toggle]);
  useEffect(
    () => () => {
      window.clearInterval(timer.current);
      const rec = recorder.current;
      if (rec?.state === 'recording') {
        rec.onstop = null;
        rec.stream.getTracks().forEach((t) => t.stop());
        rec.stop();
      }
    },
    [],
  );

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setError('Could not copy to the clipboard.');
    }
  };

  const recording = phase === 'recording';
  return (
    <PageLayout title="Dictation" description="Speak and get text, all on this computer.">
      <Section title="Record">
        <div className="bg-muted/30 flex flex-col items-center gap-4 rounded-xl border p-6">
          <LiveWaveform active={recording} processing={phase === 'transcribing'} deviceId={device || undefined} height={64} mode="static" className="w-full" />
          <div className="flex items-center gap-3">
            <Button
              size="lg"
              variant={recording ? 'destructive' : 'default'}
              className="rounded-full px-6"
              disabled={phase === 'transcribing' || muted}
              onClick={() => toggle(false)}
            >
              {recording ? <Square /> : <Mic />} {recording ? 'Stop' : 'Record'}
            </Button>
            {recording && <span aria-live="polite" className="text-destructive text-sm tabular-nums">● Recording {fmt(elapsed)}</span>}
            {phase === 'transcribing' && <span aria-live="polite" className="text-muted-foreground text-sm">Transcribing…</span>}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Microphone" hint={muted ? 'Muted: unmute it to record.' : undefined}>
            <MicSelector value={device} onValueChange={setDevice} muted={muted} onMutedChange={setMuted} disabled={phase !== 'idle'} className="w-full justify-start border sm:w-full" />
          </Field>
          <Field label="Language">
            <ChoiceSelect options={LANGUAGES} value={language} disabled={phase !== 'idle'} onChange={setLanguage} />
          </Field>
        </div>
        <Muted className="text-xs">
          {window.voxwell
            ? 'Press Ctrl/Cmd+Shift+Space anywhere to start and stop; the text is copied for you to paste.'
            : 'The global shortcut is available in the desktop app.'}
        </Muted>
        <div role="alert">
          <ErrorAlert message={error} />
        </div>
      </Section>

      <Section title="Result">
        {text ? (
          <>
            <p className="leading-relaxed">{text}</p>
            <div>
              <Button variant="outline" size="sm" onClick={() => copy(text)}>
                <Copy /> {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
          </>
        ) : (
          <Muted>Nothing yet. Press Record and speak.</Muted>
        )}
      </Section>

      <Section title="Recent">
        {history.length === 0 ? (
          <Muted>No transcripts yet.</Muted>
        ) : (
          <div className="divide-y">
            {history.map((h, i) => (
              <div className="flex items-start gap-3 py-2 text-sm" key={i}>
                <span className="flex-1">{h}</span>
                <Button variant="ghost" size="sm" onClick={() => copy(h)}>
                  <Copy /> Copy
                </Button>
              </div>
            ))}
          </div>
        )}
      </Section>
    </PageLayout>
  );
}
