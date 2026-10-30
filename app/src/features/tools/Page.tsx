import { useEffect, useState } from 'react';
import { ArrowRightLeft, AudioLines, Plus, Sparkles, Timer, Trash2, Volume2 } from 'lucide-react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Muted, Page as PageLayout } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { LANGUAGES } from '../voice_cloning/languages';

const TOOLS = [
  { id: 'convert', title: 'Convert voice', hint: 'Re-speak a recording in one of your saved voices. The words and timing stay the same.' },
  { id: 'isolate', title: 'Isolate voice', hint: 'Split a recording into the voice alone and everything else: music, noise and effects.' },
  { id: 'direct', title: 'AI direction', hint: 'Say how a line should sound, in your own words. A local AI turns it into settings you can adjust.' },
  { id: 'compare', title: 'Compare voices', hint: 'Hear the same sentence in several voices, side by side.' },
  { id: 'fit', title: 'Fit length', hint: 'Speed audio up or slow it down to an exact length, without changing the pitch.' },
  { id: 'probe', title: 'File info', hint: 'See the format, length and streams of an audio or video file.' },
] as const;

type ToolId = (typeof TOOLS)[number]['id'];

export default function Page() {
  const [tool, setTool] = useState<ToolId>('convert');
  const [voices, setVoices] = useState<Voice[]>([]);
  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
  }, []);

  return (
    <PageLayout title="Tools" description="Small jobs for audio you already have.">
      <Tabs value={tool} onValueChange={(v) => setTool(v as ToolId)}>
        {/* Wraps onto more rows on a phone; the list's own height must follow, and so must the tabs'. */}
        <TabsList className="flex-wrap group-data-[orientation=horizontal]/tabs:h-auto">
          {TOOLS.map((t) => (
            <TabsTrigger key={t.id} value={t.id} className="h-8 flex-none">{t.title}</TabsTrigger>
          ))}
        </TabsList>
        {TOOLS.map((t) => (
          <TabsContent key={t.id} value={t.id}>
            <Card>
              <CardHeader>
                <CardTitle>{t.title}</CardTitle>
                <CardDescription>{t.hint}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {t.id === 'convert' && <Convert voices={voices} />}
                {t.id === 'isolate' && <Isolate />}
                {t.id === 'direct' && <Direct voices={voices} />}
                {t.id === 'compare' && <Compare voices={voices} />}
                {t.id === 'fit' && <Fit />}
                {t.id === 'probe' && <Probe />}
              </CardContent>
            </Card>
          </TabsContent>
        ))}
      </Tabs>
    </PageLayout>
  );
}

const Result = ({ url, name }: { url: string; name: string }) => <AudioResult src={apiUrl(url)} download={name} />;

function Convert({ voices }: { voices: Voice[] }) {
  const [file, setFile] = useState<File | null>(null);
  const [voice, setVoice] = useState('');
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setUrl('');
    const form = new FormData();
    form.append('file', file);
    form.append('voice_id', voice);
    try {
      setUrl((await api<{ url: string }>('/api/tools/convert', { method: 'POST', body: form })).url);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Recording" hint="WAV, MP3, FLAC or OGG">
        <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={busy} />
      </Field>
      <Field label="New voice" hint={voices.length === 0 ? 'Add a voice in Voice cloning, Voice design or Gallery first.' : undefined}>
        <VoiceSelect voices={voices} value={voice} onChange={setVoice} defaultLabel={null} />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy || !file || !voice} onClick={run}>
          <ArrowRightLeft /> {busy ? 'Converting…' : 'Convert'}
        </Button>
        {busy && <Muted>The first time downloads the conversion model.</Muted>}
      </div>
      <ErrorAlert message={error} />
      {url && <Result url={url} name="converted.wav" />}
    </>
  );
}

type Isolated = { voice: { url: string }; background: { url: string }; seconds: number };

function Isolate() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Isolated | null>(null);
  const [error, setError] = useState('');

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    const form = new FormData();
    form.append('file', file);
    try {
      setResult(await api<Isolated>('/api/tools/isolate', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Recording" hint="WAV, MP3, FLAC or OGG, up to 10 minutes">
        <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={busy} />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy || !file} onClick={run}>
          <AudioLines /> {busy ? 'Isolating…' : 'Isolate voice'}
        </Button>
        {busy && <Muted>The first time downloads the isolation model (84 MB). A minute of audio takes about 20 seconds on a CPU.</Muted>}
      </div>
      <ErrorAlert message={error} />
      {result && (
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Voice">
            <Result url={result.voice.url} name="voice.wav" />
          </Field>
          <Field label="Background">
            <Result url={result.background.url} name="background.wav" />
          </Field>
        </div>
      )}
    </>
  );
}

const PACES = ['slow', 'normal', 'fast'] as const;
const PACE_OPTIONS = PACES.map((p) => [p, p[0].toUpperCase() + p.slice(1)] as const);
const EXAMPLE_NOTES = ['whisper it, sad and slow', 'excited, like a game show host', 'bored and tired'];

function Direct({ voices }: { voices: Voice[] }) {
  const [text, setText] = useState('I never thought I would see this place again.');
  const [language, setLanguage] = useState('en');
  const [voice, setVoice] = useState('');
  const [note, setNote] = useState('');
  const [intensity, setIntensity] = useState(0.5);
  const [pace, setPace] = useState<(typeof PACES)[number]>('normal');
  const [summary, setSummary] = useState('');
  const [busy, setBusy] = useState<'interpret' | 'speak' | null>(null);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');

  async function interpret() {
    setBusy('interpret');
    setError('');
    try {
      const s = await sendJson<{ intensity: number; pace: (typeof PACES)[number]; summary: string }>('/api/tools/direction/interpret', 'POST', { note });
      setIntensity(s.intensity);
      setPace(s.pace);
      setSummary(s.summary);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  async function speak() {
    setBusy('speak');
    setError('');
    setUrl('');
    try {
      const res = await sendJson<{ url: string }>('/api/tools/direction/speak', 'POST', { text, language, voice_id: voice || null, intensity, pace });
      setUrl(res.url);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <Field label="Line" htmlFor="direct-line">
        <Textarea id="direct-line" rows={2} maxLength={300} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
        <Field label="Voice">
          <VoiceSelect voices={voices} value={voice} onChange={setVoice} />
        </Field>
        <Field label="Language">
          <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
        </Field>
      </div>
      <Field label="Direction" htmlFor="direct-note">
        <Input id="direct-note" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="e.g. whisper it, sad and slow" />
      </Field>
      <div className="flex flex-wrap gap-2">
        {EXAMPLE_NOTES.map((n) => (
          <Button key={n} variant="secondary" size="sm" onClick={() => setNote(n)}>{n}</Button>
        ))}
        <Button size="sm" disabled={busy !== null || !note.trim()} onClick={interpret}>
          <Sparkles /> {busy === 'interpret' ? 'Thinking…' : 'Interpret'}
        </Button>
      </div>
      {busy === 'interpret' && <Muted className="text-xs">The first time downloads the AI model (about 3 GB).</Muted>}
      {summary && <Muted>The AI heard: “{summary}”. Adjust below if needed.</Muted>}
      <div className="grid gap-4 rounded-lg border p-4 sm:grid-cols-[1fr_200px]">
        <Field label={<>Energy <Badge variant="secondary">{intensity < 0.35 ? 'quiet' : intensity > 0.65 ? 'loud' : 'natural'}</Badge></>}>
          <Slider min={0} max={1} step={0.05} value={[intensity]} onValueChange={([v]) => setIntensity(v)} aria-label="Energy" className="py-2" />
        </Field>
        <Field label="Pace">
          <ChoiceSelect options={PACE_OPTIONS} value={pace} onChange={(v) => setPace(v as (typeof PACES)[number])} />
        </Field>
      </div>
      <div>
        <Button disabled={busy !== null || !text.trim()} onClick={speak}>
          <Volume2 /> {busy === 'speak' ? 'Speaking…' : 'Speak'}
        </Button>
      </div>
      <ErrorAlert message={error} />
      {url && <Result url={url} name="directed.wav" />}
    </>
  );
}

const MAX_COMPARE = 4;

function Compare({ voices }: { voices: Voice[] }) {
  const [text, setText] = useState('The quick brown fox jumps over the lazy dog.');
  const [language, setLanguage] = useState('en');
  const [chosen, setChosen] = useState<string[]>(['', '']);
  const [results, setResults] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState('');

  async function run() {
    setError('');
    setResults({});
    // One voice at a time, so each result appears as soon as it is ready.
    for (const [i, voice_id] of chosen.entries()) {
      setBusy(i);
      try {
        const res = await sendJson<{ url: string }>('/api/tools/speak', 'POST', { text, language, voice_id: voice_id || null });
        setResults((r) => ({ ...r, [i]: res.url }));
      } catch (e) {
        setError(message(e));
        break;
      }
    }
    setBusy(null);
  }

  const name = (id: string) => voices.find((v) => v.id === id)?.name ?? 'Default voice';

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
        <Field label="Text" htmlFor="compare-text">
          <Textarea id="compare-text" rows={2} maxLength={300} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Field label="Language">
          <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {chosen.map((voice, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-lg border p-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Voice {i + 1}</span>
              {busy === i && <Muted className="text-xs">Speaking…</Muted>}
              {chosen.length > 2 && (
                <Button variant="ghost" size="icon" className="ml-auto size-7" aria-label="Remove" disabled={busy !== null} onClick={() => setChosen(chosen.filter((_, j) => j !== i))}>
                  <Trash2 />
                </Button>
              )}
            </div>
            <VoiceSelect voices={voices} value={voice} onChange={(v) => setChosen(chosen.map((c, j) => (j === i ? v : c)))} />
            {results[i] && (
              <div aria-label={name(voice)}>
                <AudioResult src={apiUrl(results[i])} />
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {chosen.length < MAX_COMPARE && (
          <Button variant="outline" disabled={busy !== null} onClick={() => setChosen([...chosen, ''])}>
            <Plus /> Add a voice
          </Button>
        )}
        <Button disabled={busy !== null || !text.trim()} onClick={run}>
          {busy !== null ? 'Comparing…' : 'Compare'}
        </Button>
      </div>
      <ErrorAlert message={error} />
    </>
  );
}

function Fit() {
  const [file, setFile] = useState<File | null>(null);
  const [seconds, setSeconds] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ url: string; original_seconds: number } | null>(null);
  const [error, setError] = useState('');

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    const form = new FormData();
    form.append('file', file);
    form.append('target_seconds', seconds);
    try {
      setResult(await api('/api/tools/fit', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Audio" hint="WAV, MP3, FLAC or OGG">
        <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={busy} />
      </Field>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="New length in seconds" htmlFor="fit-seconds" className="w-48">
          <Input id="fit-seconds" type="number" min={0.1} step={0.1} value={seconds} onChange={(e) => setSeconds(e.target.value)} placeholder="e.g. 12.5" />
        </Field>
        <Button disabled={busy || !file || !(Number(seconds) > 0)} onClick={run}>
          <Timer /> {busy ? 'Fitting…' : 'Fit'}
        </Button>
      </div>
      <ErrorAlert message={error} />
      {result && (
        <>
          <Muted>Was {result.original_seconds.toFixed(2)} s, now {Number(seconds).toFixed(2)} s.</Muted>
          <Result url={result.url} name="fitted.wav" />
        </>
      )}
    </>
  );
}

interface ProbeInfo {
  format: string | null;
  duration: number | null;
  size: number | null;
  bit_rate: number | null;
  streams: { type: string; codec: string; sample_rate?: number; channels?: number; width?: number; height?: number; fps?: number; language?: string }[];
}

const megabytes = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;

function Probe() {
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<ProbeInfo | null>(null);
  const [error, setError] = useState('');

  async function run(file: File) {
    setBusy(true);
    setError('');
    setInfo(null);
    const form = new FormData();
    form.append('file', file);
    try {
      setInfo(await api<ProbeInfo>('/api/tools/probe', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <FileDrop
        file={null}
        onFile={(f) => f && run(f)}
        accept="audio/*,video/*,.mkv"
        disabled={busy}
        label={busy ? 'Reading…' : 'Drop an audio or video file here or click to choose'}
      />
      <ErrorAlert message={error} />
      {info && (
        <div className="flex flex-col gap-1 rounded-lg border p-4 text-sm">
          <span className="font-medium">{info.format}</span>
          <span>
            {info.duration !== null && `${info.duration.toFixed(2)} s`}
            {info.size !== null && ` · ${megabytes(info.size)}`}
            {info.bit_rate !== null && ` · ${Math.round(info.bit_rate / 1000)} kb/s`}
          </span>
          {info.streams.map((s, i) => (
            <span key={i} className="text-muted-foreground">
              {s.type === 'video' ? 'Video' : s.type === 'audio' ? 'Audio' : 'Subtitles'}: {s.codec}
              {s.width && ` · ${s.width}×${s.height}`}
              {s.fps && ` · ${s.fps} fps`}
              {s.sample_rate && ` · ${s.sample_rate} Hz`}
              {s.channels && ` · ${s.channels === 1 ? 'mono' : s.channels === 2 ? 'stereo' : `${s.channels} channels`}`}
              {s.language && ` · ${s.language}`}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
