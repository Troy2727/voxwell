import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { api, apiUrl, listVoices, Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { LANGUAGES } from './languages';

export default function Page() {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [voiceId, setVoiceId] = useState('');
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [text, setText] = useState('');
  const [language, setLanguage] = useState('en');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [audioUrl, setAudioUrl] = useState('');

  const refresh = () =>
    listVoices().then(setVoices, (e: Error) => {
      setVoices([]);
      setError(e.message);
    });
  useEffect(() => {
    void refresh();
  }, []);

  async function upload() {
    if (!file || !name.trim()) return;
    setUploading(true);
    setError('');
    try {
      const body = new FormData();
      body.append('name', name.trim());
      body.append('file', file);
      const voice = await api<Voice>('/api/voice_cloning/voices', { method: 'POST', body });
      await refresh();
      setVoiceId(voice.id);
      setName('');
      setFile(null);
      toast.success(`Saved "${voice.name}"`);
    } catch (e) {
      setError(message(e));
    } finally {
      setUploading(false);
    }
  }

  async function generate() {
    setBusy(true);
    setError('');
    setAudioUrl('');
    try {
      const res = await api<{ id: string; url: string }>('/api/voice_cloning/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language, voice_id: voiceId || null }),
      });
      setAudioUrl(apiUrl(res.url));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageLayout title="Voice cloning" description="Clone a voice from a short clip, then make it say anything.">
      <Section title="Add a voice" description="A few seconds of clean speech: WAV, MP3, FLAC or OGG.">
        <Field label="Name" htmlFor="clone-name">
          <Input id="clone-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="My voice" />
        </Field>
        <Field label="Reference clip">
          <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={uploading} />
        </Field>
        <div>
          <Button disabled={uploading || !file || !name.trim()} onClick={upload}>
            {uploading ? 'Uploading…' : 'Upload voice'}
          </Button>
        </div>
      </Section>

      <Section title="Generate speech">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Voice" hint={voices !== null && voices.length === 0 ? 'No saved voices yet. Upload one above.' : undefined}>
            <VoiceSelect voices={voices} value={voiceId} onChange={setVoiceId} disabled={voices === null} />
          </Field>
          <Field label="Language">
            <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
          </Field>
        </div>
        <Field label="Text" htmlFor="clone-text" hint={`${text.length} / 2000`}>
          <Textarea id="clone-text" rows={5} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} placeholder="Type what the voice should say…" />
        </Field>
        <div>
          <Button disabled={busy || !text.trim()} onClick={generate}>
            {busy ? 'Generating…' : 'Generate'}
          </Button>
        </div>
        <ErrorAlert message={error} />
        {audioUrl && <AudioResult src={audioUrl} download="voxwell-speech.wav" />}
      </Section>
    </PageLayout>
  );
}
