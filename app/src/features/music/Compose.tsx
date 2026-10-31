import { useState, type Dispatch, type SetStateAction } from 'react';
import { Music, Sparkles } from 'lucide-react';
import { formatTime, generate, writeLyrics, type MusicStatus, type Settings, type Track } from './api';
import { ChoiceSelect } from '@/components/choice-select';
import { ExampleChips } from '@/components/example-chips';
import { FileDrop } from '@/components/file-drop';
import { LyricsEditor } from '@/components/lyrics-editor';
import { ErrorAlert, Field, message, Muted, Section } from '@/components/page';
import { SegmentedControl } from '@/components/segmented-control';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { Textarea } from '@/components/ui/textarea';

const EXAMPLES = [
  'Upbeat indie pop, bright electric guitars, punchy drums, warm female vocals',
  'Lo-fi hip hop beat, dusty vinyl, mellow Rhodes piano, relaxed',
  'Epic cinematic orchestral score, big drums, soaring strings, choir',
  'Acoustic folk ballad, fingerpicked guitar, soft male vocals, intimate',
];

export const DEFAULT_SETTINGS: Settings = {
  prompt: '',
  lyrics: '',
  instrumental: false,
  language: 'en',
  duration: 30,
  bpm: '',
  key: '',
  seed: '',
  steps: 8,
};

const AUTO = 'auto';

export function ComposeSection({ status, settings, onChange, onQueued }: {
  status: MusicStatus;
  settings: Settings;
  onChange: Dispatch<SetStateAction<Settings>>;
  onQueued: (track: Track) => void;
}) {
  const [reference, setReference] = useState<File | null>(null);
  const [writing, setWriting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // Applied to the latest settings, so a slow reply (AI lyrics) keeps edits made while it ran.
  const set = (patch: Partial<Settings>) => onChange((current) => ({ ...current, ...patch }));
  const { limits } = status;

  async function aiLyrics() {
    setWriting(true);
    setError('');
    try {
      set({ lyrics: (await writeLyrics(settings.prompt, settings.language)).lyrics });
    } catch (e) {
      setError(message(e));
    } finally {
      setWriting(false);
    }
  }

  async function submit() {
    setBusy(true);
    setError('');
    try {
      // A reused track can carry a key the list does not offer; send "automatic" then, as shown.
      onQueued(await generate({ ...settings, key: status.keys.includes(settings.key) ? settings.key : '' }, reference));
      setReference(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const bpm = Number(settings.bpm);
  const bpmValid = settings.bpm.trim() === '' || (Number.isInteger(bpm) && bpm >= 30 && bpm <= 300);
  const seedValid = settings.seed.trim() === '' || (/^\d+$/.test(settings.seed.trim()) && Number(settings.seed) < 2 ** 32);
  const needsLyrics = !settings.instrumental && !settings.lyrics.trim();
  const ready = settings.prompt.trim() !== '' && !needsLyrics && bpmValid && seedValid;

  return (
    <Section title="Compose" description="Describe the style, add lyrics (or let AI write them) and generate.">
      <Field label="Style" htmlFor="music-prompt" hint={`Genre, mood, instruments, vocals. ${settings.prompt.length} / ${limits.max_prompt}`}>
        <Textarea
          id="music-prompt"
          rows={3}
          maxLength={limits.max_prompt}
          value={settings.prompt}
          onChange={(e) => set({ prompt: e.target.value })}
          placeholder="Dreamy synth-pop with airy female vocals and a driving bassline"
        />
      </Field>
      <ExampleChips examples={EXAMPLES} onPick={(prompt) => set({ prompt })} />

      <div className="flex flex-wrap items-end gap-4">
        <Field label="Vocals">
          <SegmentedControl
            label="Vocals"
            value={settings.instrumental ? 'instrumental' : 'song'}
            onChange={(v) => set({ instrumental: v === 'instrumental' })}
            options={[{ value: 'song', label: 'Song with lyrics' }, { value: 'instrumental', label: 'Instrumental' }]}
          />
        </Field>
        {!settings.instrumental && (
          <Field label="Language" htmlFor="music-language" className="w-44">
            <ChoiceSelect id="music-language" value={settings.language} onChange={(language) => set({ language })} options={Object.entries(status.languages)} />
          </Field>
        )}
      </div>

      {!settings.instrumental && (
        <Field label="Lyrics" htmlFor="music-lyrics">
          <LyricsEditor
            id="music-lyrics"
            value={settings.lyrics}
            onChange={(lyrics) => set({ lyrics })}
            maxLength={limits.max_lyrics}
            disabled={writing}
            actions={
              <Button type="button" variant="secondary" size="sm" disabled={writing || !settings.prompt.trim()} onClick={aiLyrics}>
                <Sparkles /> {writing ? 'Writing…' : 'Write with AI'}
              </Button>
            }
          />
        </Field>
      )}

      <Field label={`Length: ${formatTime(settings.duration)}`} hint={`${formatTime(limits.min_seconds)} to ${formatTime(limits.max_seconds)}`}>
        <Slider
          aria-label="Length in seconds"
          min={limits.min_seconds}
          max={limits.max_seconds}
          step={5}
          value={[settings.duration]}
          onValueChange={([duration]) => set({ duration })}
        />
      </Field>

      <div className="grid gap-4 @md:grid-cols-2 @2xl:grid-cols-4">
        <Field label="Tempo (BPM)" htmlFor="music-bpm" hint="30 to 300; empty: automatic">
          <Input id="music-bpm" inputMode="numeric" placeholder="Auto" value={settings.bpm} onChange={(e) => set({ bpm: e.target.value })} aria-invalid={!bpmValid} />
        </Field>
        <Field label="Key" htmlFor="music-key">
          <ChoiceSelect
            id="music-key"
            value={status.keys.includes(settings.key) ? settings.key : AUTO}
            onChange={(key) => set({ key: key === AUTO ? '' : key })}
            options={[[AUTO, 'Automatic'], ...status.keys.map((k) => [k, k] as const)]}
          />
        </Field>
        <Field label="Seed" htmlFor="music-seed" hint="Reuse a seed to repeat a result">
          <Input id="music-seed" inputMode="numeric" placeholder="Random" value={settings.seed} onChange={(e) => set({ seed: e.target.value })} aria-invalid={!seedValid} />
        </Field>
        <Field label={`Quality steps: ${settings.steps}`} hint="More is slower">
          <Slider aria-label="Quality steps" min={4} max={20} step={1} value={[settings.steps]} onValueChange={([steps]) => set({ steps })} />
        </Field>
      </div>

      <Field label="Style reference (optional)" hint="A short clip whose sound, instruments and tempo the track should follow. It is not copied.">
        <FileDrop file={reference} onFile={setReference} accept="audio/*" hint="WAV, MP3, FLAC or OGG, up to 2 minutes" />
      </Field>

      <ErrorAlert message={error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={submit} disabled={busy || !ready}>
          <Music /> {busy ? 'Queuing…' : 'Generate'}
        </Button>
        {needsLyrics && settings.prompt.trim() && <Muted>Add lyrics, write them with AI, or choose instrumental.</Muted>}
        {status.device === 'cpu' && !needsLyrics && <Muted>No GPU found: generating runs on the processor and takes several minutes.</Muted>}
      </div>
    </Section>
  );
}
