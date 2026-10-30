import { useEffect, useRef, useState } from 'react';
import { Languages, Radio, Square, Trash2 } from 'lucide-react';
import { api, listVoices, type Voice } from '@/api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { EmptyState, ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { LiveWaveform } from '@/components/ui/live-waveform';
import { MicSelector } from '@/components/ui/mic-selector';
import { Skeleton } from '@/components/ui/skeleton';
import { type LiveMessage, useLiveAudio } from '@/hooks/use-live-audio';

interface Status {
  ready: boolean;
  sources: string[];
  targets: string[];
}

interface Turn {
  id: number; // unique on the page; turn indexes restart with each session
  transcript?: string;
  source?: string;
  translation?: string;
  audio?: string; // data: URL
  warning?: string;
  error?: string;
}

const MAX_TURNS = 50; // each turn keeps its audio in memory
const names = new Intl.DisplayNames(['en'], { type: 'language' });
const languageName = (code: string) => {
  try {
    return names.of(code) ?? code;
  } catch {
    return code;
  }
};
const options = (codes: string[]) =>
  codes.map((c) => [c, languageName(c)] as [string, string]).sort((a, b) => a[1].localeCompare(b[1]));
const str = (v: unknown) => (typeof v === 'string' ? v : undefined);

export default function Page() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loadError, setLoadError] = useState('');
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [device, setDevice] = useState('');
  const [muted, setMuted] = useState(false);
  const [source, setSource] = useState('auto');
  const [target, setTarget] = useState('es');
  const [voice, setVoice] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(0);
  const [warning, setWarning] = useState('');
  const [playing, setPlaying] = useState(false);

  const nextId = useRef(0);
  const queue = useRef<string[]>([]);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    api<Status>('/api/translation/status')
      .then((s) => {
        setStatus(s);
        if (!s.targets.includes('es')) setTarget(s.targets[0] ?? '');
      })
      .catch((e) => setLoadError(message(e)));
    listVoices().then(setVoices).catch(() => setVoices([]));
  }, []);

  // Translations play one after another, in turn order. The microphone sends silence meanwhile,
  // so the speakers are not translated back.
  const playNext = () => {
    const src = queue.current.shift();
    if (!src) {
      audio.current = null;
      setPlaying(false);
      live.pause(false);
      return;
    }
    const el = new Audio(src);
    audio.current = el;
    setPlaying(true);
    live.pause(true);
    el.onended = el.onerror = () => playNext();
    el.play().catch(() => playNext());
  };
  const stopPlayback = () => {
    queue.current = [];
    audio.current?.pause();
    audio.current = null;
    setPlaying(false);
    live.pause(false);
  };

  const onMessage = (m: LiveMessage) => {
    if (m.type === 'turn_end' && m.index != null) setPending((p) => p + 1);
    else if (m.type === 'warning') setWarning(m.message ?? '');
    else if ((m.type === 'turn' || m.type === 'error') && m.index != null) {
      setPending((p) => Math.max(0, p - 1));
      const raw = str(m.audio);
      const turn: Turn = {
        id: nextId.current++,
        transcript: str(m.transcript),
        source: str(m.source),
        translation: str(m.translation),
        audio: raw ? `data:audio/wav;base64,${raw}` : undefined,
        warning: str(m.warning),
        error: m.type === 'error' ? m.message : undefined,
      };
      if (turn.error || turn.transcript) setTurns((t) => [...t, turn].slice(-MAX_TURNS));
      if (turn.audio) {
        queue.current.push(turn.audio);
        if (!audio.current) playNext();
      }
    }
  };
  const live = useLiveAudio('/api/translation/live', onMessage);
  const active = live.status !== 'idle';

  useEffect(() => {
    if (!active) setPending(0);
  }, [active]);
  useEffect(() => () => stopPlayback(), []);

  const begin = () => {
    setWarning('');
    stopPlayback();
    void live.start({ source: source === 'auto' ? null : source, target, voice: voice || null }, device || undefined);
  };

  const state =
    live.status === 'connecting' ? 'Connecting…'
      : playing ? 'Playing the translation…'
        : live.status === 'finishing' ? 'Finishing the last turn…'
          : live.status !== 'listening' ? ''
            : live.speaking ? '● Speaking…'
              : pending ? 'Translating…'
                : 'Listening…';

  if (loadError) {
    return (
      <PageLayout title="Live translation" description="Speak in one language and hear it in another.">
        <ErrorAlert message={`Could not load the languages: ${loadError}`} />
      </PageLayout>
    );
  }

  return (
    <PageLayout title="Live translation" description="Speak in one language and hear it in another, turn by turn, all on this computer.">
      <Section title="Speak">
        <div className="bg-muted/30 flex flex-col items-center gap-4 rounded-xl border p-6">
          <LiveWaveform active={live.status === 'listening' && !playing} processing={live.status === 'finishing'} deviceId={device || undefined} height={64} mode="static" className="w-full" />
          <div className="flex items-center gap-3">
            <Button
              size="lg"
              variant={active ? 'destructive' : 'default'}
              className="rounded-full px-6"
              disabled={!status || !target || live.status === 'finishing' || (!active && muted)}
              onClick={active ? live.stop : begin}
            >
              {active ? <Square /> : <Radio />} {active ? 'Stop' : 'Start'}
            </Button>
            {state && (
              <span aria-live="polite" className={live.speaking ? 'text-destructive text-sm' : 'text-muted-foreground text-sm'}>
                {state}
              </span>
            )}
          </div>
        </div>
        {status ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Microphone" hint={muted ? 'Muted: unmute it to start.' : undefined}>
              <MicSelector value={device} onValueChange={setDevice} muted={muted} onMutedChange={setMuted} disabled={active} className="w-full justify-start border sm:w-full" />
            </Field>
            <Field label="Voice">
              <VoiceSelect voices={voices} value={voice} onChange={setVoice} disabled={active} />
            </Field>
            <Field label="I speak">
              <ChoiceSelect options={[['auto', 'Detect automatically'], ...options(status.sources)]} value={source} disabled={active} onChange={setSource} />
            </Field>
            <Field label="Translate to" hint="Languages the speech model can say.">
              <ChoiceSelect options={options(status.targets)} value={target} disabled={active} onChange={setTarget} />
            </Field>
          </div>
        ) : (
          <Skeleton className="h-32 w-full" />
        )}
        <Muted className="text-xs">The microphone pauses while a translation plays. Headphones let you keep talking.</Muted>
        {warning && <Muted className="text-xs">{warning}</Muted>}
        <div role="alert">
          <ErrorAlert message={live.error} />
        </div>
      </Section>

      <Section
        title="Conversation"
        action={
          turns.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setTurns([])} disabled={active}>
              <Trash2 /> Clear
            </Button>
          )
        }
      >
        {turns.length === 0 ? (
          <EmptyState icon={Languages} title="Nothing translated yet">
            Press Start and speak. Each time you pause, you see what you said and hear the translation.
          </EmptyState>
        ) : (
          <div className="divide-y">
            {turns.map((t) => (
              <div className="flex flex-col gap-2 py-3" key={t.id}>
                {t.error ? (
                  <p className="text-destructive text-sm">{t.error}</p>
                ) : (
                  <>
                    <p className="text-muted-foreground text-sm">
                      {t.source ? `${languageName(t.source)}: ` : ''}
                      {t.transcript}
                    </p>
                    <p className="leading-relaxed">{t.translation}</p>
                    {t.audio && <AudioResult src={t.audio} lazy />}
                    {t.warning && <Muted className="text-xs">{t.warning}</Muted>}
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>
    </PageLayout>
  );
}
