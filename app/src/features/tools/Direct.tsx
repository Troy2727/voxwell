import { useState } from 'react';
import { Sparkles, Volume2 } from 'lucide-react';
import { apiUrl, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { ErrorAlert, Field, message, Muted } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { Textarea } from '@/components/ui/textarea';
import { LANGUAGES } from '../voice_cloning/languages';

const PACES = ['slow', 'normal', 'fast'] as const;
const PACE_OPTIONS = PACES.map((p) => [p, p[0].toUpperCase() + p.slice(1)] as const);
const EXAMPLE_NOTES = ['whisper it, sad and slow', 'excited, like a game show host', 'bored and tired'];

export function Direct({ voices }: { voices: Voice[] }) {
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
      {url && <AudioResult src={apiUrl(url)} download="directed.wav" />}
    </>
  );
}
