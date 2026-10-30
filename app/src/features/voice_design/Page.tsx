import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { api, apiUrl, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ErrorAlert, Field, message, Page as PageLayout, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

const EXAMPLES = [
  'Warm, low female voice, slight British accent, calm pace',
  'Energetic young male narrator, clear and upbeat',
  'Deep, gravelly older man, slow and thoughtful',
];

interface Preview {
  preview_id: string;
  url: string;
}

const post = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export default function Page() {
  const [description, setDescription] = useState('');
  const [sampleText, setSampleText] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function generate() {
    setLoading(true);
    setError('');
    try {
      setPreview(await post<Preview>('/api/voice_design/preview', { description, sample_text: sampleText || undefined }));
    } catch (e) {
      setError(message(e));
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!preview) return;
    setSaving(true);
    setError('');
    try {
      const saved = await post<Voice>('/api/voice_design/save', { preview_id: preview.preview_id, name });
      toast.success(`Saved "${saved.name}" to your voices.`);
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <PageLayout title="Voice design" description="Describe a voice in words and Voxwell creates it.">
      <Section title="Describe the voice">
        <Field label="Description" htmlFor="design-description">
          <Textarea id="design-description" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Age, gender, accent, tone, pace…" />
        </Field>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <Button key={ex} type="button" variant="secondary" size="sm" className="h-auto max-w-full py-1.5 text-left whitespace-normal" onClick={() => setDescription(ex)}>
              {ex}
            </Button>
          ))}
        </div>
        <Field label="Sample text (optional)" htmlFor="design-sample">
          <Textarea id="design-sample" rows={2} value={sampleText} onChange={(e) => setSampleText(e.target.value)} />
        </Field>
        <div>
          <Button onClick={generate} disabled={loading || !description.trim()}>
            <Sparkles /> {loading ? 'Generating…' : preview ? 'Regenerate' : 'Preview'}
          </Button>
        </div>
      </Section>
      <ErrorAlert message={error} />
      {preview && (
        <Section title="Preview">
          <AudioResult src={apiUrl(preview.url)} download="voxwell-voice-preview.wav" />
          <div className="flex items-end gap-2">
            <Field label="Voice name" htmlFor="design-name" className="flex-1">
              <Input id="design-name" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Button onClick={save} disabled={saving || !name.trim()}>
              {saving ? 'Saving…' : 'Save to voices'}
            </Button>
          </div>
        </Section>
      )}
    </PageLayout>
  );
}
