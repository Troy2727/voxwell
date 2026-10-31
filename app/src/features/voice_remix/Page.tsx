import { useEffect, useState } from 'react';
import { Library, Repeat, Save, Wand2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ExampleChips } from '@/components/example-chips';
import { EmptyState, ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { SegmentedControl } from '@/components/segmented-control';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { VoiceSelect } from '@/components/voice-select';

type Strength = 'low' | 'medium' | 'high' | 'max';

const STRENGTHS = [
  { value: 'low', label: 'Low', description: 'Keeps the voice; takes on the new delivery' },
  { value: 'medium', label: 'Medium', description: 'Halfway between the two voices' },
  { value: 'high', label: 'High', description: 'Mostly the described voice' },
  { value: 'max', label: 'Max', description: 'Entirely the described voice' },
] as const;

const EXAMPLES = [
  'An older man with a deep, raspy voice speaks slowly and calmly. Very clear audio.',
  'A young woman with a bright, high-pitched voice speaks quickly and cheerfully.',
  'A man speaks in a hushed, breathy whisper, very close to the microphone.',
  'A woman with a warm British accent speaks at a moderate pace, like a narrator.',
];

interface Status {
  ready: boolean;
  default_script: string;
}

interface Preview {
  preview_id: string;
  url: string;
}

export default function Page() {
  const [status, setStatus] = useState<Status | null>(null);
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [voiceId, setVoiceId] = useState('');
  const [prompt, setPrompt] = useState('');
  const [strength, setStrength] = useState<Strength>('medium');
  const [script, setScript] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Voice | null>(null);
  const [error, setError] = useState('');

  const refreshVoices = () => listVoices().then(setVoices, (e) => { setVoices([]); setError(message(e)); });
  useEffect(() => {
    api<Status>('/api/voice_remix/status').then(setStatus, (e) => setError(message(e)));
    void refreshVoices();
  }, []);

  const source = voices?.find((v) => v.id === voiceId);

  async function generate() {
    setBusy(true);
    setError('');
    setPreview(null);
    setSaved(null);
    try {
      setPreview(await sendJson<Preview>('/api/voice_remix/preview', 'POST', { voice_id: voiceId, prompt, strength, script: script.trim() || null }));
      if (!name.trim() && source) setName(`${source.name} (remix)`);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!preview) return;
    setSaving(true);
    setError('');
    try {
      const voice = await sendJson<Voice>('/api/voice_remix/save', 'POST', { preview_id: preview.preview_id, name });
      setSaved(voice);
      void refreshVoices();
      toast.success(`Saved "${voice.name}" to your voices.`);
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  }

  function remixFurther() {
    if (!saved) return;
    setVoiceId(saved.id);
    setPreview(null);
    setSaved(null);
    setName('');
  }

  return (
    <PageLayout title="Voice remix" description="Turn one of your saved voices into a new one by describing the voice you want. The original stays as it is.">
      <ErrorAlert message={error} />
      {status && !status.ready && <ErrorAlert message="The voice models are not installed. Run uv sync in the backend folder." />}
      {voices === null && <Skeleton className="h-40 w-full" />}
      {voices?.length === 0 && (
        <EmptyState icon={Library} title="No saved voices yet">
          Clone or design a voice first, then remix it here.
        </EmptyState>
      )}
      {voices && voices.length > 0 && (
        <Section title="Remix a voice">
          <Field label="Voice to start from">
            <VoiceSelect voices={voices} value={voiceId} onChange={setVoiceId} defaultLabel={null} disabled={busy} />
          </Field>
          {source && (
            <div className="flex flex-col gap-1">
              <Muted className="text-xs">Original: {source.name}</Muted>
              <AudioResult src={apiUrl(`/api/voices/${source.id}/audio`)} lazy />
            </div>
          )}
          <Field label="Describe the new voice" htmlFor="remix-prompt" hint="Gender, age, pitch, pace, accent, tone, recording quality. English works best.">
            <Textarea id="remix-prompt" rows={3} maxLength={500} value={prompt} onChange={(e) => setPrompt(e.target.value)} disabled={busy}
              placeholder="An older woman with a low, warm voice speaks slowly" />
          </Field>
          <ExampleChips examples={EXAMPLES} onPick={setPrompt} disabled={busy} />
          <Field label="Strength">
            <SegmentedControl label="Strength" options={STRENGTHS} value={strength} onChange={setStrength} disabled={busy} />
          </Field>
          <Field label="Preview script (optional)" htmlFor="remix-script" hint="English text the preview reads; it also becomes the new voice's reference clip.">
            <Textarea id="remix-script" rows={2} maxLength={500} value={script} onChange={(e) => setScript(e.target.value)} disabled={busy}
              placeholder={status?.default_script} />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={generate} disabled={busy || !voiceId || !prompt.trim() || status?.ready === false}>
              <Wand2 /> {busy ? 'Remixing…' : preview ? 'Remix again' : 'Remix'}
            </Button>
            {busy && <Muted>Designing the voice and blending it with the original. This takes a minute without a GPU.</Muted>}
          </div>
        </Section>
      )}

      {preview && (
        <Section title="Remixed voice">
          <AudioResult src={apiUrl(preview.url)} download="voxwell-remix-preview.wav" autoPlay />
          {saved ? (
            <div className="flex flex-wrap items-center gap-3">
              <Muted className="flex-1">Saved as “{saved.name}”. It works everywhere a saved voice does.</Muted>
              <Button variant="outline" onClick={remixFurther}><Repeat /> Remix this one further</Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Name for the new voice" htmlFor="remix-name" className="min-w-48 flex-1">
                <Input id="remix-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Button onClick={save} disabled={saving || !name.trim()}>
                <Save /> {saving ? 'Saving…' : 'Save to voices'}
              </Button>
            </div>
          )}
        </Section>
      )}
    </PageLayout>
  );
}
