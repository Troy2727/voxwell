import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy, Mic, Square, Trash2 } from 'lucide-react';
import { onPhoneOrTablet } from '../../api';
import { ChoiceSelect } from '@/components/choice-select';
import { ErrorAlert, Field, Muted, Page as PageLayout, Section } from '@/components/page';
import { PhoneDictation, savedPhoneAddress } from '@/components/phone-dictation';
import { Button } from '@/components/ui/button';
import { LiveWaveform } from '@/components/ui/live-waveform';
import { MicSelector } from '@/components/ui/mic-selector';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DICTATED_EVENT, dictationChoices, openMicrophone, rememberLanguage, transcribeRecording } from './capture';
import LiveDictation from './LiveDictation';

const LANGUAGES: [string, string][] = [
  ['auto', 'Auto-detect'], ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['ru', 'Russian'], ['zh', 'Chinese'],
  ['ja', 'Japanese'], ['ko', 'Korean'], ['ar', 'Arabic'], ['hi', 'Hindi'], ['tr', 'Turkish'],
];

type Phase = 'idle' | 'recording' | 'transcribing';
type Mode = 'record' | 'live';

const languageName = (code: string) => new Intl.DisplayNames('en', { type: 'language' }).of(code) ?? code;

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export default function Page() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [language, setLanguage] = useState(dictationChoices.language);
  const [device, setDevice] = useState(dictationChoices.device);
  const [muted, setMuted] = useState(false);
  const [text, setText] = useState('');
  const [detected, setDetected] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [mode, setMode] = useState<Mode>('record');
  const [liveActive, setLiveActive] = useState(false);

  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const phaseRef = useRef<Phase>('idle');
  dictationChoices.device = device;

  const setPhaseBoth = (p: Phase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const transcribe = useCallback(async (blob: Blob) => {
    setPhaseBoth('transcribing');
    try {
      const asked = dictationChoices.language;
      const result = await transcribeRecording(blob, asked);
      setText(result.text);
      setDetected(asked === 'auto' ? result.language : '');
      if (result.text) {
        setHistory((h) => [result.text, ...h].slice(0, 20));
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
    async () => {
      setError('');
      setCopied(false);
      let stream: MediaStream;
      try {
        stream = await openMicrophone(dictationChoices.device);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
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
        void transcribe(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }));
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
    () => {
      if (phaseRef.current === 'recording') {
        if (recorder.current?.state === 'recording') recorder.current.stop();
      } else if (phaseRef.current === 'idle') {
        void start();
      }
    },
    [start],
  );

  // The shortcut records in the app shell; show its text here when this page is open.
  useEffect(() => {
    const show = (event: Event) => {
      const dictated = (event as CustomEvent<string>).detail;
      setError('');
      setCopied(false);
      setText(dictated);
      setDetected('');
      setHistory((h) => [dictated, ...h].slice(0, 20));
    };
    window.addEventListener(DICTATED_EVENT, show);
    return () => window.removeEventListener(DICTATED_EVENT, show);
  }, []);
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

  /** The current result is always the top of Recent, so deleting that line clears both. */
  const remove = (index: number) => {
    setHistory((h) => h.filter((_, i) => i !== index));
    if (index === 0) setText('');
  };

  const recording = phase === 'recording';
  const tabs = (
    <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
      <TabsList>
        <TabsTrigger value="record" disabled={liveActive}>Record</TabsTrigger>
        <TabsTrigger value="live" disabled={phase !== 'idle' || (onPhoneOrTablet() && !savedPhoneAddress())}>Live</TabsTrigger>
      </TabsList>
    </Tabs>
  );
  const fields = (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Microphone" hint={muted ? `Muted: unmute it to ${mode === 'live' ? 'start' : 'record'}.` : undefined}>
        <MicSelector value={device} onValueChange={setDevice} muted={muted} onMutedChange={setMuted} disabled={phase !== 'idle' || liveActive} className="w-full justify-start border sm:w-full" />
      </Field>
      <Field label="Language" htmlFor="dictation-language">
        <ChoiceSelect
          id="dictation-language"
          options={LANGUAGES}
          value={language}
          disabled={phase !== 'idle' || liveActive}
          onChange={(choice) => {
            rememberLanguage(choice);
            setLanguage(choice);
          }}
        />
      </Field>
    </div>
  );
  if (mode === 'live') {
    return (
      <PageLayout title="Dictation" description="Speak and get text, all on this computer.">
        <LiveDictation tabs={tabs} fields={fields} device={device} language={language} muted={muted} onActiveChange={setLiveActive} />
      </PageLayout>
    );
  }
  return (
    <PageLayout title="Dictation" description="Speak and get text, all on this computer.">
      {onPhoneOrTablet() && <PhoneDictation />}
      <Section title="Record" action={tabs}>
        <div className="bg-muted/30 flex flex-col items-center gap-4 rounded-xl border p-6">
          <LiveWaveform active={recording} processing={phase === 'transcribing'} deviceId={device || undefined} height={64} mode="static" className="w-full" />
          <div className="flex items-center gap-3">
            <Button
              size="lg"
              variant={recording ? 'destructive' : 'default'}
              className="rounded-full px-6"
              disabled={phase === 'transcribing' || muted}
              onClick={toggle}
            >
              {recording ? <Square /> : <Mic />} {recording ? 'Stop' : 'Record'}
            </Button>
            {recording && <span aria-live="polite" className="text-destructive text-sm tabular-nums">● Recording {fmt(elapsed)}</span>}
            {phase === 'transcribing' && <span aria-live="polite" className="text-muted-foreground text-sm">Transcribing…</span>}
          </div>
        </div>
        {fields}
        <Muted className="text-xs">
          {window.voxwell
            ? 'Press Ctrl/Cmd+Shift+Space anywhere to start and stop; the text is copied for you to paste.'
            : 'The global shortcut is available in the desktop app.'}
        </Muted>
        {onPhoneOrTablet() && !savedPhoneAddress() && <Muted className="text-xs">On a phone, Live needs your computer's private address, saved above.</Muted>}
        <div role="alert">
          <ErrorAlert message={error} />
        </div>
      </Section>

      <Section title="Result">
        {text ? (
          <>
            <p className="leading-relaxed">{text}</p>
            {detected && <Muted className="text-xs">Detected: {languageName(detected)}. If that's wrong, choose your language above.</Muted>}
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => copy(text)}>
                <Copy /> {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button variant="outline" size="sm" onClick={() => remove(0)}>
                <Trash2 /> Delete
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
                <Button variant="ghost" size="sm" onClick={() => remove(i)}>
                  <Trash2 /> Delete
                </Button>
              </div>
            ))}
          </div>
        )}
      </Section>
    </PageLayout>
  );
}
